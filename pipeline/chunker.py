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
    i = 0
    total_segments = len(segments)

    logger.info(f"Assembling sliding contextual text windows for video: {video_id}")

    # Slide across all segments using lookahead accumulation loop
    while i < total_segments:
        window_segments = []
        current_duration = 0.0
        
        # Start anchoring positions
        window_start_s = segments[i]["start_s"]
        
        # Accumulate segments until window targets (~30-60s) are met
        j = i
        while j < total_segments:
            seg = segments[j]
            window_segments.append(seg)
            window_end_s = seg["end_s"]
            current_duration = window_end_s - window_start_s
            
            # Break if adding more text exceeds our maximum semantic boundary
            if current_duration >= 45.0 or (current_duration >= 30.0 and j - i >= 3):
                break
            j += 1
            
        # If lookahead hit terminal file boundaries, clamp the indices securely
        if j >= total_segments:
            j = total_segments - 1
            window_end_s = segments[j]["end_s"]

        # Synthesize the text payload paragraph contract
        combined_text = " ".join([s["text"] for s in window_segments])
        
        semantic_windows.append({
            "window_index": len(semantic_windows),
            "start_s": round(window_start_s, 2),
            "end_s": round(window_end_s, 2),
            "duration_s": round(window_end_s - window_start_s, 2),
            "text": combined_text
        })

        # CRITICAL RULE: Advance step index with exactly 1-segment tracking overlap
        # This guarantees contextual continuity across window frames
        advance_step = max(1, j - i)
        i += advance_step

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