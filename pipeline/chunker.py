import os
import json
import logging
import glob

# Strict monorepo path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
TRANSCRIPTS_DIR = os.path.join(PROJECT_ROOT, "data", "transcripts")
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Chunker")

# Tight sliding-window shape — mirrors tight_windows(size=4, step=2) from the
# tight-vs-wide A/B (stage2_spec.md priority #1). SIZE segments per window, advance
# by STEP => overlap = SIZE - STEP = 2 segments. Replaces the former ~30-45s duration
# target, which produced semantically diluted (blurry) windows that capped relevance.
WINDOW_SIZE = 4
WINDOW_STEP = 2

def build_semantic_windows(video_id: str) -> dict:
    """
    [Phase A - Step 8 Semantic Windowing]
    Slides over chronologically absolute transcript blocks grouping text elements 
    into dense vector-optimized search contexts with a 1-segment overlap.
    """
    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"{video_id}.json")
    output_semantic_path = os.path.join(CHUNKS_DIR, f"{video_id}_semantic.json")

    if not os.path.exists(transcript_path):
        return {"status": "error", "message": f"Source transcript mapping missing for {video_id}"}

    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript_data = json.load(f)

    segments = transcript_data.get("segments", [])
    if not segments:
        logger.warning(f"No text blocks found inside transcript metadata for {video_id}.")
        return {"status": "skipped", "message": "Empty segment array"}

    semantic_windows = []
    total_segments = len(segments)

    logger.info(f"Assembling tight sliding text windows for video: {video_id}")

    # Fixed segment-count sliding window (SIZE=4, STEP=2 => 2-segment overlap),
    # mirroring the tight_windows shape that scored best in the A/B. Each window's
    # timestamps are inherited directly from its member segments (already absolute
    # post-merge), so the output contract — start_s / end_s / duration_s / text —
    # is unchanged; this is a windowing-parameter change, not a schema change.
    for i in range(0, total_segments, WINDOW_STEP):
        window_segments = segments[i:i + WINDOW_SIZE]
        if not window_segments:
            break

        window_start_s = window_segments[0]["start_s"]
        window_end_s = window_segments[-1]["end_s"]
        combined_text = " ".join(s["text"] for s in window_segments if s.get("text"))

        semantic_windows.append({
            "window_index": len(semantic_windows),
            "start_s": round(window_start_s, 2),
            "end_s": round(window_end_s, 2),
            "duration_s": round(window_end_s - window_start_s, 2),
            "text": combined_text
        })

        # Stop once this window already reaches the final segment — mirrors the A/B
        # script's `if i + size >= n: break`, avoiding redundant tail windows.
        if i + WINDOW_SIZE >= total_segments:
            break

    # Save output dataset contract package securely to disk
    with open(output_semantic_path, 'w', encoding='utf-8') as out_f:
        json.dump({
            "video_id": video_id,
            "total_windows": len(semantic_windows),
            "windows": semantic_windows
        }, out_f, indent=2)

    logger.info(f"Semantic packing locked. Formatted {len(semantic_windows)} dense windows for vector indexing.")
    return {"status": "success", "output_path": output_semantic_path}

def scan_and_chunk_transcripts():
    """Scans for master video transcripts to transform into text windows."""
    transcript_files = glob.glob(os.path.join(TRANSCRIPTS_DIR, "*.json"))
    for file_path in transcript_files:
        video_id = os.path.splitext(os.path.basename(file_path))[0]
        if video_id.startswith("chunk_"):
            continue
        result = build_semantic_windows(video_id)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    scan_and_chunk_transcripts()