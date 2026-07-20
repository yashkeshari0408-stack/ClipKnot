import os
import re
import json
import glob
import shutil
import logging
import tempfile

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()  # self-sufficient: pulls SARVAM_API_KEY from the root .env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.TranscribeSarvam")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

# --- Sarvam engine config -------------------------------------------------------
# saaras:v3 + mode="codemix" is the Hindi/Hinglish path (same combo the A/B test used).
# with_timestamps=True is what makes the batch job emit the word-level TimestampsModel
# (words[] / start_time_seconds[] / end_time_seconds[]); without it there are NO
# boundaries to build segments from. language_code is intentionally left unset so
# Sarvam detects the language AND populates language_probability (per the SDK docstring
# it returns null the moment you pin an explicit language_code).
SARVAM_MODEL = "saaras:v3"
SARVAM_MODE = "codemix"

POLL_INTERVAL_S = 5
JOB_TIMEOUT_S = 600

def _normalize(text: str) -> str:
    """Trim and collapse internal whitespace runs in a segment's text."""
    return re.sub(r"\s{2,}", " ", (text or "")).strip()


def _synthesize_segments(words, starts, ends) -> list[dict]:
    """
    Map Sarvam's timestamp arrays 1:1 to segments — one array entry IS one segment.

    Despite the SDK typing the field as `words: List[str]`, saaras:v3 batch + codemix
    returns UTTERANCE/paragraph-level entries (measured: ~15s and ~60 words each,
    already sentence-segmented and contiguous). There are no individual words to
    regroup, so any word-grouping/gap/duration heuristic here would be fiction. We
    therefore pass each entry straight through.

    Returns a list of {start, end, text, avg_logprob, no_speech_prob,
    confidence_source} dicts with CHUNK-RELATIVE timestamps (merge.py adds the
    per-chunk offset downstream, exactly as it does for Groq segments).

    Confidence is None + an explicit 'sarvam_none' marker, NOT a fabricated 0.0:
    Sarvam exposes no avg_logprob / no_speech_prob equivalent, so the Stage 2 gate
    must branch on this marker instead of thresholding a fake value.
    """
    words = words or []
    starts = starts or []
    ends = ends or []

    n = min(len(words), len(starts), len(ends))
    if not (len(words) == len(starts) == len(ends)):
        logger.warning(
            "Sarvam timestamp arrays are ragged (words=%d, starts=%d, ends=%d); "
            "truncating to %d to keep them aligned.",
            len(words), len(starts), len(ends), n,
        )

    segments: list[dict] = []
    for k in range(n):
        text = _normalize(words[k])
        if not text:
            continue  # skip blank/whitespace-only entries
        segments.append({
            "start": round(starts[k], 3),
            "end": round(ends[k], 3),
            "text": text,
            "avg_logprob": None,          # Sarvam has no logprob — kept explicit, not 0.0
            "no_speech_prob": None,       # ditto; propagated so the gate sees the gap
            "confidence_source": "sarvam_none",
        })
    return segments


def transcribe_sarvam_batch(chunk_path: str) -> dict:
    """
    Transcribe ONE audio chunk via Sarvam's Speech-to-Text BATCH job API and return
    a Groq-CACHE-shaped dict so merge.py / chunker.py stay engine-agnostic
    (ADR-001 provider swap). The returned dict mirrors what transcribe.py caches for
    Groq — merge.py reads it with zero structural changes:

        {
          "language": <bcp47 str | None>,
          "language_probability": <float | None>,   # whole-file; merge ignores it
          "engine": "sarvam",                        # provenance for the gate/debug
          "segments": [ {start, end, text, avg_logprob, no_speech_prob,
                         confidence_source}, ... ]   # start/end are chunk-relative
        }

    Lifecycle verified against sarvamai 0.1.28 SDK source (speech_to_text_job):
        create_job(with_timestamps=True) -> upload_files -> start
        -> wait_until_complete -> download_outputs -> parse the JSON off disk.
    """
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY missing from the root .env file.")

    client = SarvamAI(api_subscription_key=SARVAM_API_KEY)

    job = client.speech_to_text_job.create_job(
        model=SARVAM_MODEL,
        mode=SARVAM_MODE,
        with_timestamps=True,   # REQUIRED — no timestamps => no segment boundaries
    )
    basename = os.path.basename(chunk_path)
    logger.info("Sarvam batch job %s created for %s", job.job_id, basename)

    job.upload_files([chunk_path])
    job.start()
    status = job.wait_until_complete(poll_interval=POLL_INTERVAL_S, timeout=JOB_TIMEOUT_S)
    if status.job_state.lower() != "completed":
        raise RuntimeError(
            f"Sarvam job {job.job_id} ended in state '{status.job_state}' for "
            f"{basename} (expected 'completed')."
        )

    # download_outputs writes one JSON per input file into a dir; grab it, then clean up.
    out_dir = tempfile.mkdtemp(prefix="sarvam_out_")
    try:
        job.download_outputs(out_dir)
        result_files = glob.glob(os.path.join(out_dir, "*.json"))
        if not result_files:
            raise RuntimeError(f"Sarvam job {job.job_id} produced no output JSON for {basename}.")
        with open(result_files[0], "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Diagnostic: if SARVAM_RAW_DUMP points at a dir, preserve the exact batch
        # output JSON there before we parse/discard it — lets us confirm the batch
        # envelope vs the assumed sync schema without re-spending quota.
        dump_dir = os.getenv("SARVAM_RAW_DUMP")
        if dump_dir:
            os.makedirs(dump_dir, exist_ok=True)
            dump_path = os.path.join(dump_dir, f"{basename}.raw_batch.json")
            with open(dump_path, "w", encoding="utf-8") as df:
                json.dump(raw, df, ensure_ascii=False, indent=2)
            logger.info("Raw Sarvam batch envelope dumped to %s", dump_path)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    # ASSUMPTION (unverified until a real job runs — see step-5 note): the downloaded
    # batch JSON matches the sync SpeechToTextResponse shape (transcript, timestamps{},
    # language_code, language_probability). Guarded so a shape mismatch fails loudly.
    timestamps = raw.get("timestamps") or {}
    if not timestamps.get("words"):
        raise RuntimeError(
            f"Sarvam job {job.job_id} returned no word timestamps for {basename} — "
            f"cannot build segments (with_timestamps flag or model-support issue, "
            f"or the batch output envelope differs from the sync schema)."
        )

    segments = _synthesize_segments(
        timestamps.get("words"),
        timestamps.get("start_time_seconds"),
        timestamps.get("end_time_seconds"),
    )
    logger.info("Sarvam job %s -> %d synthesized segments for %s",
                job.job_id, len(segments), basename)

    return {
        "language": raw.get("language_code"),
        "language_probability": raw.get("language_probability"),
        "engine": "sarvam",
        "segments": segments,
    }
