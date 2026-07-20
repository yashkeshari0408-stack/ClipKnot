import os
import json
import logging
import time
import glob
import subprocess
from dotenv import load_dotenv
from groq import Groq
from groq import RateLimitError, APIStatusError, APITimeoutError, APIConnectionError

# Sarvam (Hindi/Hinglish) path lives in a sibling module so the Groq specifics here
# stay isolated. The import is safe without a Sarvam key — SARVAM_API_KEY is only
# required INSIDE transcribe_sarvam_batch at call time, so English/Groq-only runs
# don't need it set. Dual-import so it resolves both as a script
# (`python pipeline/transcribe.py`, pipeline/ on sys.path -> bare import) and as a
# module (`python -m pipeline.transcribe` -> package-qualified import).
try:
    from transcribe_sarvam import transcribe_sarvam_batch
except ModuleNotFoundError:
    from pipeline.transcribe_sarvam import transcribe_sarvam_batch

load_dotenv()  # make the script self-sufficient — loads GROQ_API_KEY from .env

# Monorepo absolute path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")
TRANSCRIPTS_DIR = os.path.join(PROJECT_ROOT, "data", "transcripts")

# Languages that route to Sarvam (saaras:v3 codemix); everything else -> Groq Whisper.
SARVAM_LANGUAGES = {"hi", "hi-in"}

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


def resolve_engine(video_id: str) -> str:
    """
    Pick the ASR engine for a video from its ingest metadata language tag.
    Reads data/raw/{video_id}.json -> "language": hi / hi-IN route to Sarvam,
    everything else (and any missing/unreadable tag) routes to Groq. We route on a
    RECORDED tag rather than auto-detecting, which would burn a wasted ASR call.
    """
    meta_path = os.path.join(RAW_DIR, f"{video_id}.json")
    language = "en"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                language = json.load(f).get("language") or "en"
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read language from %s (%s); defaulting to Groq.", meta_path, exc)
    else:
        logger.warning("No ingest metadata at %s; defaulting language to 'en' (Groq).", meta_path)

    engine = "sarvam" if language.lower() in SARVAM_LANGUAGES else "groq"
    logger.info("Video %s tagged language='%s' -> %s engine.", video_id, language, engine)
    return engine


def transcribe_chunk_routed(chunk_file_path: str, engine: str) -> dict:
    """
    Engine-agnostic transcription front door. BOTH branches return the SAME
    Groq-cache contract so merge.py never learns which engine ran (ADR-001):
        {language, segments: [{start, end, text, avg_logprob,
                               no_speech_prob, confidence_source}, ...]}

    - Sarvam: transcribe_sarvam_batch already emits this shape (confidence fields
      are None + "sarvam_none" — Sarvam exposes no logprob equivalent).
    - Groq: the raw verbose_json already carries start/end/text/avg_logprob/
      no_speech_prob; we only STAMP confidence_source="groq" per segment so the
      cached contract matches the Sarvam path field-for-field. The raw footprint
      is otherwise preserved (setdefault won't clobber anything Groq returns).
    """
    if engine == "sarvam":
        return transcribe_sarvam_batch(chunk_file_path)

    payload = transcribe_chunk(chunk_file_path)  # Groq raw verbose_json dump
    for seg in payload.get("segments", []):
        seg.setdefault("confidence_source", "groq")
    return payload


def transcribe_video(video_id: str) -> dict:
    """
    Transcribe every chunk of ONE video, given its id. Reads the chunk manifest at
    data/chunks/{video_id}/manifest.json, resolves the ASR engine once, and caches
    each chunk's raw API response to data/transcripts/{video_id}/. Idempotent:
    chunks with an existing cached snapshot are skipped (no re-billing).

    Extracted verbatim from the former per-video loop body so process_chunks_directory
    (the batch entry point) and the async worker share one code path. Per-chunk errors
    are logged and skipped — a single bad chunk does not abort the video — preserving
    the original batch behavior.
    """
    manifest_path = os.path.join(CHUNKS_DIR, video_id, "manifest.json")
    if not os.path.exists(manifest_path):
        logger.warning(f"No chunk manifest for {video_id} at {manifest_path}. Run split.py first.")
        return {"status": "error", "video_id": video_id, "message": "missing chunk manifest"}

    video_transcript_dir = os.path.join(TRANSCRIPTS_DIR, video_id)
    os.makedirs(video_transcript_dir, exist_ok=True)

    # Load the chunk mapping file data contract
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest_data = json.load(f)

    logger.info(f"Processing transcript pipeline for video session: {video_id}")

    # Resolve the ASR engine ONCE per video from its language tag, then reuse it
    # for every chunk of this video.
    engine = resolve_engine(video_id)

    transcribed = skipped = missing = failed = 0

    for chunk_meta in manifest_data["chunks"]:
        chunk_file_name = chunk_meta["chunk_file"]
        raw_chunk_path = os.path.join(CHUNKS_DIR, video_id, chunk_file_name)

        # Target file anchor for the raw API response cache snapshot
        response_cache_name = f"{os.path.splitext(chunk_file_name)[0]}_response.json"
        response_cache_path = os.path.join(video_transcript_dir, response_cache_name)

        # Idempotency: don't re-bill Groq audio-seconds if the snapshot already exists.
        if os.path.exists(response_cache_path):
            logger.info(f"Cached API snapshot discovered for {chunk_file_name}. Skipping API transmission.")
            skipped += 1
            continue

        if os.path.exists(raw_chunk_path):
            start_time = time.time()
            logger.info(f"Transmitting stream chunk to cloud gateway: {chunk_file_name}")

            try:
                raw_api_payload = transcribe_chunk_routed(raw_chunk_path, engine)

                # Store the exact primitive JSON footprint to local disk
                with open(response_cache_path, 'w', encoding='utf-8') as cache_f:
                    json.dump(raw_api_payload, cache_f, indent=2)

                duration = round(time.time() - start_time, 2)
                logger.info(f"Successfully transcribed {chunk_file_name} via {engine} in {duration}s.")
                transcribed += 1

            except Exception as e:
                logger.error(f"Terminal pipeline interruption while transcribing chunk {chunk_file_name}: {e}")
                failed += 1
        else:
            logger.warning(f"Manifest declared asset target {chunk_file_name} but file is missing on local drive.")
            missing += 1

    return {
        "status": "success",
        "video_id": video_id,
        "engine": engine,
        "transcribed": transcribed,
        "skipped": skipped,
        "missing": missing,
        "failed": failed,
    }


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
        transcribe_video(video_id)


if __name__ == "__main__":
    process_chunks_directory()