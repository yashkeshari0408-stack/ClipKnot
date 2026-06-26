import os
import json
import logging
import subprocess
import time
import glob

# Monorepo absolute structural path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.SplitNaive")

os.makedirs(CHUNKS_DIR, exist_ok=True)

def split_flac_naive(video_id: str, input_flac_path: str) -> dict:
    """
    [Phase A - Step 4 Naive]
    Splits master FLAC into static 10-minute segments using native FFmpeg.
    Generates the manifest mapping absolute timeline offsets to prevent drift bugs.
    """
    start_time = time.time()
    video_chunk_dir = os.path.join(CHUNKS_DIR, video_id)
    manifest_path = os.path.join(video_chunk_dir, "manifest.json")
    
    # Idempotency Gate: Skip heavy system sub-processing if manifest exists
    if os.path.exists(manifest_path):
        logger.info(f"Chunks and manifest for {video_id} already exist. Skipping split.")
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return {"status": "skipped", "manifest": json.load(f)}

    os.makedirs(video_chunk_dir, exist_ok=True)
    logger.info(f"Executing naive size/time split for: {video_id}.flac")

    # Segment template naming target
    output_template = os.path.join(video_chunk_dir, "chunk_%02d.flac")
    
    # -f segment: uses internal segment muxer
    # -segment_time 600: sets target chunk length to 10 minutes (600s)
    # -reset_timestamps 1: forces each chunk's internal timeline container to start at 0s for Groq
    # -c:a flac: RE-ENCODE each segment (NOT -c copy). Stream-copy clones the master's FLAC
    #   STREAMINFO header into every chunk, so each chunk advertises the full 2184s duration
    #   while containing only ~600s of frames -> Groq reads the lying header, reports
    #   input_audio_seconds=2184, and 500/502s on the header/stream mismatch. Re-encoding
    #   writes a correct per-chunk header (and true zero-based timestamps). Cheap at 16kHz mono.
    command = [
        "ffmpeg", "-y",
        "-i", input_flac_path,
        "-f", "segment",
        "-segment_time", "600",
        "-reset_timestamps", "1",
        "-c:a", "flac",
        output_template
    ]

    try:
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        
        # Scan filesystem for generated chunk file footprints
        generated_chunks = sorted(glob.glob(os.path.join(video_chunk_dir, "chunk_*.flac")))
        chunks_manifest = []
        
        for index, chunk_path in enumerate(generated_chunks):
            # Size verification guard to check for API threshold compliance
            file_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
            if file_size_mb > 24.0:
                logger.error(f"CRITICAL: Chunk {os.path.basename(chunk_path)} ({file_size_mb:.2f}MB) exceeds 24MB cap!")
            
            # Absolute timeline start position calculation
            start_offset = float(index * 600)
            chunks_manifest.append({
                "chunk_file": os.path.basename(chunk_path),
                "start_offset_sec": start_offset,
                "file_size_mb": round(file_size_mb, 2)
            })

        manifest_data = {
            "video_id": video_id,
            "total_chunks": len(chunks_manifest),
            "chunks": chunks_manifest
        }

        # Save absolute manifest contract data snapshot
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, indent=2)

        duration = round(time.time() - start_time, 2)
        logger.info(f"Split complete for {video_id}. Generated {len(chunks_manifest)} chunks in {duration}s.")
        return {"status": "success", "manifest": manifest_data}

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg segmentation execution failed: {e.stderr}")
        return {"status": "error", "message": f"FFmpeg error: {e.stderr}"}
    except Exception as e:
        logger.error(f"System failure during splitting execution: {str(e)}")
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

def process_raw_directory():
    """Scans raw data folder for existing FLAC assets ready for chunk segmentation."""
    flac_files = glob.glob(os.path.join(RAW_DIR, "*.flac"))
    if not flac_files:
        logger.warning("No master FLAC assets discovered. Execute ingest.py first.")
        return

    for path in flac_files:
        video_id = os.path.splitext(os.path.basename(path))[0]
        result = split_flac_naive(video_id, path)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    process_raw_directory()