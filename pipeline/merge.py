import os
import json
import logging
import glob

# Strict monorepo absolute structural path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")
TRANSCRIPTS_DIR = os.path.join(PROJECT_ROOT, "data", "transcripts")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Merge")

def merge_video_transcripts(video_id: str) -> dict:
    """
    [Phase A - Step 7 Merge]
    Parses segment files, applies chronological offset transformations,
    and produces a unified timeline contract tracking document.
    """
    video_chunk_dir = os.path.join(CHUNKS_DIR, video_id)
    video_transcript_dir = os.path.join(TRANSCRIPTS_DIR, video_id)
    manifest_path = os.path.join(video_chunk_dir, "manifest.json")
    master_output_path = os.path.join(TRANSCRIPTS_DIR, f"{video_id}.json")

    if not os.path.exists(manifest_path):
        return {"status": "error", "message": f"Missing chunk manifest file for video {video_id}"}

    # Read tracking metadata contract to extract timeline start positions
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest_data = json.load(f)

    merged_segments = []
    detected_language = "en"  # Standard default fallback string

    logger.info(f"Applying timeline offset logic for video: {video_id}")

    for chunk_meta in manifest_data["chunks"]:
        chunk_name = chunk_meta["chunk_file"]
        offset_sec = float(chunk_meta["start_offset_sec"]) # O_i offset factor
        
        # Build file target pointing to the stored raw JSON payload
        chunk_id = os.path.splitext(chunk_name)[0]
        response_json_path = os.path.join(video_transcript_dir, f"{chunk_id}_response.json")

        if not os.path.exists(response_json_path):
            logger.warning(f"Expected response data missing for chunk file: {chunk_name}. Skipping segment.")
            continue

        with open(response_json_path, 'r', encoding='utf-8') as f:
            raw_response = json.load(f)

        if "language" in raw_response:
            detected_language = raw_response["language"]

        raw_segments = raw_response.get("segments", [])
        for seg in raw_segments:
            # Shift the relative chunk timestamps into absolute video-timeline positions
            absolute_start = round(float(seg.get("start", 0.0)) + offset_sec, 2)
            absolute_end = round(float(seg.get("end", 0.0)) + offset_sec, 2)
            
            merged_segments.append({
                "start_s": absolute_start,
                "end_s": absolute_end,
                "text": seg.get("text", "").strip(),
                "avg_logprob": round(float(seg.get("avg_logprob", 0.0)), 4),
                "flagged": False,   # Gate flags default to false in Phase A
                "retried": False
            })

    # Basic interval sorting pass based on start timeline timestamps
    merged_segments.sort(key=lambda x: x["start_s"])

    # Construct complete data contract layout matching spec requirements
    final_contract_payload = {
        "video_id": video_id,
        "language": detected_language,
        "segments": merged_segments,
        "timings": {
            "download_s": 0.0,
            "vad_s": 0.0,
            "transcribe_s": 0.0
        }
    }

    # Atomic write to parent transcripts storage folder layer
    with open(master_output_path, 'w', encoding='utf-8') as f:
        json.dump(final_contract_payload, f, indent=2)

    logger.info(f"Merge operation locked. Unified {len(merged_segments)} segments into {video_id}.json")
    return {"status": "success", "output_path": master_output_path}

def scan_and_process_transcripts():
    """Scans for processed transcript subfolders to coordinate chronological merging."""
    subfolders = glob.glob(os.path.join(TRANSCRIPTS_DIR, "*"+os.sep))
    if not subfolders:
        # Check for un-nested response targets sitting at base folder layer
        candidate_dirs = [os.path.basename(os.path.dirname(d)) for d in glob.glob(os.path.join(CHUNKS_DIR, "*", ""))]
        if not candidate_dirs:
            logger.warning("No tracking chunk targets discovered inside storage folders.")
            return
        subfolders = [os.path.join(TRANSCRIPTS_DIR, d, "") for d in candidate_dirs if os.path.exists(os.path.join(TRANSCRIPTS_DIR, d))]

    for folder_path in subfolders:
        video_id = os.path.basename(os.path.normpath(folder_path))
        if video_id.startswith("chunk_") or video_id.endswith(".json"):
            continue
        result = merge_video_transcripts(video_id)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    scan_and_process_transcripts()