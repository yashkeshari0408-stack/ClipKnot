import os
import sys
import json
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Diagnosis")

# Mirror of merge.py's GATE_LOGPROB_THRESHOLD (ADR-010). avg_logprob is the ONLY
# gate metric — no_speech_prob and compression_ratio were dropped after they
# flagged 166/299 segments on the baseline video vs 9 for avg_logprob alone.
# Kept as a literal so this stays a standalone, dependency-free sanity check.
GATE_LOGPROB_THRESHOLD = -1.0

# Default target for backward-compatible bare `python diagnose_gate.py` runs.
DEFAULT_VIDEO_ID = "HK0ZkdwrNUM"

def analyze_confidence_metrics(video_id: str = DEFAULT_VIDEO_ID):
    # Read the merged transcript for this video explicitly — no "first file wins"
    # guessing, which silently picks the wrong video once more than one exists.
    transcript_dir = os.path.join(PROJECT_ROOT, "data", "transcripts")
    target_file = os.path.join(transcript_dir, f"{video_id}.json")
    if not os.path.exists(target_file):
        logger.error(f"No merged transcript found for video '{video_id}' at {target_file}")
        return

    logger.info(f"Opening merged transcript for diagnostics: {target_file}")

    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Standardizing for unexpected structures
    segments = data.get("segments", [])
    if not segments and "chunks" in data:
        segments = data.get("chunks", [])

    print("\n" + "="*60)
    print("🚨 TELEMETRY GAP ANALYSIS: CONFIDENCE GATE")
    print("="*60)
    
    flagged_count = 0
    total_segments = len(segments)
    
    for idx, seg in enumerate(segments):
        # avg_logprob is the sole gate metric. Sarvam segments carry None here
        # (no logprob exists) and bypass the gate — mirrors merge.py exactly.
        avg_logprob = seg.get("avg_logprob", 0.0)
        text = seg.get("text", "")

        is_flagged = avg_logprob is not None and avg_logprob < GATE_LOGPROB_THRESHOLD

        if is_flagged:
            flagged_count += 1
            print(f"⚠️ Segment [{idx}]: FLAGGED (avg_logprob < {GATE_LOGPROB_THRESHOLD})")
            print(f"   ↳ Text snippet: \"{text[:60]}...\"")
            print(f"   ↳ avg_logprob: {avg_logprob:.4f}\n")

    print("-"*60)
    print(f"📊 Summary Analysis: {flagged_count} out of {total_segments} segments fell below the avg_logprob gate.")
    print("="*60 + "\n")

if __name__ == "__main__":
    video_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO_ID
    analyze_confidence_metrics(video_id)