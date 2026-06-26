import os
import json
import logging
import time
import csv
import subprocess
from typing import Optional
import yt_dlp

# Strict monorepo path anchoring based on script position
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
CSV_PATH = os.path.join(PROJECT_ROOT, "data", "sample", "videos_urls.csv")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Ingest")

os.makedirs(RAW_DIR, exist_ok=True)

def extract_youtube_id(url: str) -> Optional[str]:
    """Safely extracts the unique 11-character YouTube video ID."""
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return info.get('id')
        except Exception:
            return None

def ingest_and_convert(url: str) -> dict:
    """
    [Step 1 & 2 Combined]
    Downloads YouTube audio, downsamples it to 16kHz mono FLAC via FFmpeg,
    applies an 80Hz highpass filter, and records metadata. Completely idempotent.
    """
    start_time = time.time()
    video_id = extract_youtube_id(url)
    
    if not video_id:
        return {"status": "error", "message": f"Invalid or inaccessible URL: {url}"}
    
    metadata_path = os.path.join(RAW_DIR, f"{video_id}.json")
    output_flac_path = os.path.join(RAW_DIR, f"{video_id}.flac")
    
    # Idempotency Gate: If both the JSON contract and FLAC exist, skip entirely
    if os.path.exists(metadata_path) and os.path.exists(output_flac_path):
        logger.info(f"Artifacts for {video_id} already exist. Skipping ingest/convert.")
        with open(metadata_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        return {"status": "skipped", "video_id": video_id, "metadata": meta}

    # Temporary download path for the raw stream asset
    temp_download_template = os.path.join(RAW_DIR, f"{video_id}_temp.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_download_template,
        'quiet': True,
        'no_warnings': True,
        'remote_components': ['ejs:github'], # 2026 signature engine bypass
    }

    try:
        logger.info(f"Downloading audio stream for: {video_id}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            # Find the actual file path yt-dlp generated (handles dynamic webm/m4a extensions)
            temp_file_path = ydl.prepare_filename(info_dict)

        logger.info(f"Converting to Whisper-spec (16kHz mono FLAC, highpass=80)...")
        # Run conversion synchronously via native FFmpeg execution
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", temp_file_path,
            "-ac", "1",
            "-ar", "16000",
            "-sample_fmt", "s16",
            "-af", "highpass=f=80",
            output_flac_path
        ]
        subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

        # Cleanup the temporary downloaded asset to preserve laptop disk space
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        # Build clean data contract metadata
        metadata = {
            "video_id": video_id,
            "source_url": url,
            "title": info_dict.get("title"),
            "channel": info_dict.get("uploader"),
            "duration_s": info_dict.get("duration"),
            "upload_date": info_dict.get("upload_date")
        }
        
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        duration = round(time.time() - start_time, 2)
        logger.info(f"Ingest and conversion complete for {video_id} in {duration}s")
        return {"status": "success", "video_id": video_id, "metadata": metadata, "duration_s": duration}

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download failed politely: {str(e)}")
        return {"status": "error", "message": f"Download failed: {str(e)}"}
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed: {e.stderr}")
        return {"status": "error", "message": "FFmpeg transformation failure."}
    except Exception as e:
        logger.error(f"Unexpected pipeline error: {str(e)}")
        return {"status": "error", "message": f"System error: {str(e)}"}

if __name__ == "__main__":
    logger.info(f"Evaluating dataset source list at: {CSV_PATH}")
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None) # Skip header
            for row in reader:
                if not row or not row[0].strip().startswith("http"):
                    continue
                target_url = row[0].strip()
                logger.info(f"Processing target from CSV: {target_url}")
                result = ingest_and_convert(target_url)
                print(json.dumps(result, indent=2))
    else:
        logger.error("Source list 'videos_urls.csv' is missing from data/sample/. Aborting.")