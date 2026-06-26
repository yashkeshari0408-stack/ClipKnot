import os
import json
import logging
import time
import glob
import subprocess
from dotenv import load_dotenv
from groq import Groq
from groq import RateLimitError, APIStatusError, APITimeoutError, APIConnectionError

load_dotenv()  # make the script self-sufficient — loads GROQ_API_KEY from .env

# Monorepo absolute path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")
TRANSCRIPTS_DIR = os.path.join(PROJECT_ROOT, "data", "transcripts")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Transcribe")

os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

# Generous timeout: the 60s default was too short for ~10MB uploads and caused
# client-side 499s (we hung up while Groq was still transcribing).
# max_retries=0: disable the SDK's own retry layer so transcribe_chunk_with_backoff
# is the SOLE retry authority. Otherwise the SDK's default 2 internal retries stack
# multiplicatively with our 5-attempt loop — chunk_03 hit Groq ~15× instead of 5.
client = Groq(timeout=300.0, max_retries=0)


def transcribe_chunk_with_backoff(chunk_file_path: str, max_retries: int = 5) -> dict:
    """
    Sends a single audio chunk to Groq Whisper Large v3.
    Retry policy maps onto transient-vs-permanent failure:
      timeouts / connection / 5xx / 429 -> transient -> back off + retry
      4xx                                -> permanent -> abort immediately
    """
    retry_delay = 2.0  # base delay in seconds
    last_error = None

    for attempt in range(max_retries):
        try:
            with open(chunk_file_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    file=(os.path.basename(chunk_file_path), audio_file.read()),
                    model="whisper-large-v3",
                    response_format="verbose_json"  # per-segment timestamps + confidence fields
                )
            # SDK returns an object; cast down to a raw primitive dict contract
            return response.model_dump()

        except (APITimeoutError, APIConnectionError) as net_err:
            last_error = net_err
            logger.warning(
                f"Transient network error on attempt {attempt + 1}/{max_retries}: "
                f"{type(net_err).__name__}. Backing off {retry_delay}s..."
            )

        except RateLimitError as rate_err:
            last_error = rate_err
            logger.warning(
                f"HTTP 429 rate limit on attempt {attempt + 1}/{max_retries}. "
                f"Backing off {retry_delay}s... Details: {rate_err}"
            )

        except APIStatusError as api_err:
            last_error = api_err
            if api_err.status_code >= 500:
                logger.warning(
                    f"Groq server error {api_err.status_code} on attempt "
                    f"{attempt + 1}/{max_retries}. Backing off {retry_delay}s..."
                )
            else:
                # 4xx: a malformed/invalid request fails identically every retry — abort now.
                logger.error(
                    f"Non-retryable client error {api_err.status_code}: {api_err.message}"
                )
                raise

        # Back off BETWEEN attempts, not after the final one (avoids a pointless
        # trailing sleep before reporting total failure).
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
            retry_delay *= 2  # exponential progression

    raise RuntimeError(
        f"API transaction failed after {max_retries} attempts for {chunk_file_path}; "
        f"last error: {type(last_error).__name__}: {last_error}"
    ) from last_error


def transcribe_chunk(chunk_file_path: str) -> dict:
    """
    Transcribe a chunk via the backoff loop, with a FLAC->WAV last resort.

    Observed: Groq's FLAC decoder reproducibly 500s on *some* chunks while the
    identical audio samples succeed as WAV (a server-side FLAC-decode edge case,
    not a bad file). So ONLY after the normal backoff retries are exhausted on a
    persistent 5xx, re-encode the chunk to WAV and try ONCE more. A 429/4xx/network
    failure is not re-attempted as WAV — a different container can't fix those.
    """
    try:
        return transcribe_chunk_with_backoff(chunk_file_path)
    except RuntimeError as exc:
        # The loop wraps the underlying API error as __cause__; only a persistent
        # server error (5xx) is worth the WAV re-encode.
        status_code = getattr(exc.__cause__, "status_code", None)
        if status_code is None or status_code < 500:
            raise

        logger.warning(
            f"Persistent {status_code} after backoff on {os.path.basename(chunk_file_path)}; "
            f"re-encoding to WAV and retrying once (suspected Groq FLAC-decode edge case)."
        )
        wav_path = f"{os.path.splitext(chunk_file_path)[0]}_fallback.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", chunk_file_path, "-c:a", "pcm_s16le", wav_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
            )
            # max_retries=1: the WAV is the last resort; one clean attempt, no storm.
            result = transcribe_chunk_with_backoff(wav_path, max_retries=1)
            logger.info(f"WAV fallback SUCCEEDED for {os.path.basename(chunk_file_path)}.")
            return result
        finally:
            # Never leave a stray diagnostic WAV behind, success or failure.
            if os.path.exists(wav_path):
                os.remove(wav_path)


def process_chunks_directory():
    """Scans chunk manifest directories and coordinates consecutive file stream transmissions."""
    logger.info("Scanning data/chunks for un-transcribed segment blocks...")

    # Locate all active manifest files
    manifests = glob.glob(os.path.join(CHUNKS_DIR, "*", "manifest.json"))

    if not manifests:
        logger.warning("No segment manifests discovered. Execute split.py first.")
        return

    for manifest_path in manifests:
        video_id = os.path.basename(os.path.dirname(manifest_path))
        video_transcript_dir = os.path.join(TRANSCRIPTS_DIR, video_id)
        os.makedirs(video_transcript_dir, exist_ok=True)

        # Load the chunk mapping file data contract
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        logger.info(f"Processing transcript pipeline for video session: {video_id}")

        for chunk_meta in manifest_data["chunks"]:
            chunk_file_name = chunk_meta["chunk_file"]
            raw_chunk_path = os.path.join(CHUNKS_DIR, video_id, chunk_file_name)

            # Target file anchor for the raw API response cache snapshot
            response_cache_name = f"{os.path.splitext(chunk_file_name)[0]}_response.json"
            response_cache_path = os.path.join(video_transcript_dir, response_cache_name)

            # Idempotency: don't re-bill Groq audio-seconds if the snapshot already exists.
            if os.path.exists(response_cache_path):
                logger.info(f"Cached API snapshot discovered for {chunk_file_name}. Skipping API transmission.")
                continue

            if os.path.exists(raw_chunk_path):
                start_time = time.time()
                logger.info(f"Transmitting stream chunk to cloud gateway: {chunk_file_name}")

                try:
                    raw_api_payload = transcribe_chunk(raw_chunk_path)

                    # Store the exact primitive JSON footprint to local disk
                    with open(response_cache_path, 'w', encoding='utf-8') as cache_f:
                        json.dump(raw_api_payload, cache_f, indent=2)

                    duration = round(time.time() - start_time, 2)
                    logger.info(f"Successfully transcribed {chunk_file_name} via Groq Cloud in {duration}s.")

                except Exception as e:
                    logger.error(f"Terminal pipeline interruption while transcribing chunk {chunk_file_name}: {e}")
            else:
                logger.warning(f"Manifest declared asset target {chunk_file_name} but file is missing on local drive.")


if __name__ == "__main__":
    process_chunks_directory()