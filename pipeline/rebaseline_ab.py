import os
import re
import json
import logging
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import torch
from sentence_transformers import SentenceTransformer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Rebaseline")

# The sync Sarvam REST endpoint we called (saaras:v3) returns NO timestamps, and
# test_sarvam_ab.py joined its 30s slices back into one transcript per FLAC file,
# so per-slice timing is gone. We reconstruct an *estimated* timeline from the
# known audio geometry: 4 contiguous transport chunks covering 0-2183.9s.
# data/raw/HK0ZkdwrNUM.flac is the whole video re-transcribed (a duplicate that
# the glob in test_sarvam_ab.py swept up) — it is dropped, not offset.
# Real per-word timing would require re-transcribing via Sarvam's Batch API
# (with_timestamps=True) — a follow-up only if Sarvam wins the A/B.
SARVAM_CHUNK_DURATIONS_S = {
    "chunk_00.flac": 600.0,
    "chunk_01.flac": 600.0,
    "chunk_02.flac": 600.0,
    "chunk_03.flac": 383.9,
}
# Split on Devanagari purna virama (।) as well as ASCII period — the ASR output
# is Hindi, where । is the sentence terminator, so `.split(". ")` never fired.
SENTENCE_SPLIT_RE = re.compile(r"[।.]")

BENCHMARK_QUERIES = [
    "भारतीय अर्थव्यवस्था की स्थिति", 
    "Prime Minister speech on infrastructure",
    "चुनाव प्रचार रणनीति और गठबंधन"
]

def build_accurate_windows(segments, window_size=4, step=2):
    """
    Builds sliding windows over raw text segments while strictly inheriting
    and tracking true video timeline boundaries (start_s and end_s).
    """
    windows = []
    total = len(segments)
    
    for i in range(0, total, step):
        end_idx = min(i + window_size, total)
        window_segs = segments[i:end_idx]
        
        if not window_segs:
            break
            
        combined_text = " ".join([s.get("text", "").strip() for s in window_segs if s.get("text")])
        
        # FIXED: Mapped keys straight to start_s and end_s from the dictionary check
        start_time = window_segs[0].get("start_s", 0.0)
        end_time = window_segs[-1].get("end_s", 0.0)
        
        if combined_text.strip():
            windows.append({
                "text": combined_text,
                "start": round(start_time, 2),
                "end": round(end_time, 2)
            })
            
        if end_idx == total:
            break
    return windows

def build_sarvam_segments(sarvam_data):
    """
    Reconstruct an estimated per-sentence timeline for the cached Sarvam
    transcripts (which carry no real timestamps).

    - Keeps only the 4 real transport chunks (drops the duplicate full-file row).
    - Anchors each chunk to its true cumulative offset on the video timeline
      (0 / 600 / 1200 / 1800s), computed from real audio durations.
    - Within a chunk, distributes sentence timestamps proportionally by character
      position — a long sentence spans proportionally more of the chunk's audio
      than a short one, instead of a flat per-sentence guess.
    """
    # Deterministic order → correct cumulative offsets regardless of JSON order.
    chunks = [
        c for c in sarvam_data.get("chunks", [])
        if c.get("chunk_file") in SARVAM_CHUNK_DURATIONS_S
    ]
    chunks.sort(key=lambda c: c["chunk_file"])

    segments = []
    chunk_offset = 0.0
    for chunk in chunks:
        duration = SARVAM_CHUNK_DURATIONS_S[chunk["chunk_file"]]

        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(chunk["transcript"]) if s.strip()]
        total_chars = sum(len(s) for s in sentences)

        if total_chars == 0:
            chunk_offset += duration
            continue

        char_cursor = 0
        for sentence in sentences:
            start_s = chunk_offset + (char_cursor / total_chars) * duration
            char_cursor += len(sentence)
            end_s = chunk_offset + (char_cursor / total_chars) * duration
            segments.append({
                "text": sentence,
                "start_s": round(start_s, 2),
                "end_s": round(end_s, 2),
            })

        chunk_offset += duration

    return segments


def evaluate_dataset(model, query_embeddings, windows, label):
    print("\n" + "="*60)
    print(f"📊 EVALUATION MATRIX: {label.upper()} ENGINE")
    print("="*60)
    
    doc_texts = [w["text"] for w in windows]
    doc_embeddings = model.encode(doc_texts, convert_to_tensor=True)
    
    for q_idx, query in enumerate(BENCHMARK_QUERIES):
        similarities = torch.nn.functional.cosine_similarity(query_embeddings[q_idx].unsqueeze(0), doc_embeddings)
        best_idx = torch.argmax(similarities).item()
        best_score = similarities[best_idx].item()
        best_window = windows[best_idx]
        
        print(f"🔍 Query: '{query}'")
        print(f"   📈 Score: {best_score:.4f} | ⏱️ Timeline: {best_window['start']}s - {best_window['end']}s")
        print(f"   📝 Text: \"{best_window['text'][:150]}...\"\n")
        print("-" * 50)

def run_rebaseline():
    groq_path = os.path.join(PROJECT_ROOT, "data", "transcripts", "HK0ZkdwrNUM.json")
    sarvam_raw_path = os.path.join(PROJECT_ROOT, "data", "chunks", "sarvam_ab_raw.json")

    # Load Groq Baseline
    with open(groq_path, "r", encoding="utf-8") as f:
        groq_data = json.load(f)
    groq_segments = groq_data.get("segments", [])
    
    # Load Sarvam Data
    with open(sarvam_raw_path, "r", encoding="utf-8") as f:
        sarvam_data = json.load(f)
        
    # Reconstruct Sarvam's estimated timeline (see build_sarvam_segments docstring)
    sarvam_segments = build_sarvam_segments(sarvam_data)

    # Process both sets through the identical windowing geometry
    groq_windows = build_accurate_windows(groq_segments, window_size=4, step=2)
    sarvam_windows = build_accurate_windows(sarvam_segments, window_size=4, step=2)
    
    logger.info("Initializing shared BGE-M3 instance...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    
    query_embeddings = model.encode(BENCHMARK_QUERIES, convert_to_tensor=True)
    
    # Execute fair comparison
    evaluate_dataset(model, query_embeddings, groq_windows, "Groq Whisper")
    evaluate_dataset(model, query_embeddings, sarvam_windows, "Sarvam Saaras")

if __name__ == "__main__":
    run_rebaseline()
 