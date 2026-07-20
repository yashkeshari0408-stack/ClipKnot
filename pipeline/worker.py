"""
pipeline/worker.py — async ingest worker (Stage 2, ADR-002/015).

Polls the jobs table, atomically claims ONE pending job (FOR UPDATE SKIP LOCKED so
concurrent workers never grab the same row), runs the full Stage-1 pipeline for that
video by calling the now-importable per-video functions, then marks the job completed
(with its resolved video_id) or failed (with the error). Sleeps a few seconds between
polls when there's nothing to do.

Run:  python -m pipeline.worker        (from the project root)

Design notes:
- Short-lived DB connections. We claim with one connection and close it, run the
  (multi-minute) pipeline holding NO connection, then reopen briefly to record the
  outcome. Holding a Neon/PgBouncer connection idle across a long transcription would
  risk it being reaped mid-run.
- No requeue-on-crash yet: a job left in 'processing' because the worker died stays
  there. A reaper (reset stale 'processing' rows past a timeout) is a later addition.
- Search stays synchronous (ADR-011); only ingest is async. This process is separate
  from the FastAPI backend on purpose.
"""

import os
import sys
import time
import logging
from contextlib import closing

# Put the project root on sys.path so `shared` and `pipeline.*` import whether this is
# launched as `python -m pipeline.worker` or `python pipeline/worker.py`.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from shared.db import get_connection, init_db  # noqa: E402
from pipeline.ingest import ingest_and_convert  # noqa: E402
from pipeline.split import split_flac_naive  # noqa: E402
from pipeline.transcribe import transcribe_video  # noqa: E402
from pipeline.merge import merge_video_transcripts  # noqa: E402
from pipeline.chunker import build_semantic_windows  # noqa: E402
from pipeline.index import index_semantic_windows  # noqa: E402

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
POLL_INTERVAL_S = 5  # idle sleep between polls when no pending jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Worker")


# --- DB helpers ------------------------------------------------------------
def claim_next_job():
    """
    Atomically claim the oldest pending job: flip it to 'processing' and return
    (id, video_url, language). Returns None when the queue is empty.

    FOR UPDATE SKIP LOCKED means a second worker skips a row already being claimed
    instead of blocking on it — safe to run N workers.
    """
    with closing(get_connection()) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE jobs
                       SET status = 'processing', updated_at = now()
                     WHERE id = (
                           SELECT id FROM jobs
                            WHERE status = 'pending'
                            ORDER BY created_at
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                     )
                    RETURNING id, video_url, language;
                    """
                )
                return cur.fetchone()  # (id, video_url, language) or None


def _update(sql, params):
    """Run a single write in its own short-lived, committed connection."""
    with closing(get_connection()) as conn:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)


def set_video_id(job_id, video_id):
    """Record the resolved YouTube id mid-run so /jobs surfaces it during processing."""
    _update(
        "UPDATE jobs SET video_id = %s, updated_at = now() WHERE id = %s;",
        (video_id, job_id),
    )


def mark_completed(job_id, video_id):
    _update(
        "UPDATE jobs SET status = 'completed', video_id = %s, updated_at = now() WHERE id = %s;",
        (video_id, job_id),
    )


def mark_failed(job_id, error, video_id=None):
    _update(
        "UPDATE jobs SET status = 'failed', error = %s, video_id = %s, updated_at = now() WHERE id = %s;",
        (error, video_id, job_id),
    )


# --- Pipeline orchestration ------------------------------------------------
def _require_ok(result, stage):
    """Raise if a stage returned an error contract ({'status': 'error', ...})."""
    if isinstance(result, dict) and result.get("status") == "error":
        raise RuntimeError(f"{stage}: {result.get('message', 'unknown error')}")
    return result


def process_job(job_id, video_url, language):
    """
    Run ingest -> split -> transcribe -> merge -> chunk -> index for one video.
    Returns the resolved video_id on success; raises on any stage failure.
    """
    # 1. ingest + convert (resolves the YouTube id)
    ingest_res = _require_ok(ingest_and_convert(video_url, language=language), "ingest")
    video_id = ingest_res["video_id"]
    set_video_id(job_id, video_id)  # visible in /jobs while the rest runs
    logger.info("job %s resolved video_id=%s", job_id, video_id)

    # 2. transport split (25MB/10-min FLAC segments + manifest)
    flac_path = os.path.join(RAW_DIR, f"{video_id}.flac")
    _require_ok(split_flac_naive(video_id, flac_path), "split")

    # 3. transcribe every chunk (Groq/Sarvam routed by the ingest language tag)
    t_res = _require_ok(transcribe_video(video_id), "transcribe")
    # Guard against a silent empty result: if this run produced no transcripts and
    # none were already cached, downstream would index nothing — fail loudly instead.
    if t_res.get("transcribed", 0) == 0 and t_res.get("skipped", 0) == 0:
        raise RuntimeError(
            f"transcribe: no chunks transcribed ({t_res.get('failed', 0)} failed, "
            f"{t_res.get('missing', 0)} missing)"
        )

    # 4. merge chunk responses into one absolute-timeline transcript (+ confidence gate)
    _require_ok(merge_video_transcripts(video_id), "merge")

    # 5. semantic windowing (tight sliding windows for retrieval)
    _require_ok(build_semantic_windows(video_id), "chunk")

    # 6. embed + upsert this ONE video's windows into Qdrant (raises on hard error)
    index_semantic_windows(video_id)

    return video_id


# --- Main loop -------------------------------------------------------------
def main():
    init_db()  # idempotent; also fails fast if DATABASE_URL is wrong
    logger.info("Worker up. Polling for pending jobs every %ss...", POLL_INTERVAL_S)

    while True:
        try:
            job = claim_next_job()
        except Exception:
            logger.exception("Failed to poll/claim a job; backing off %ss.", POLL_INTERVAL_S)
            time.sleep(POLL_INTERVAL_S)
            continue

        if job is None:
            time.sleep(POLL_INTERVAL_S)
            continue

        job_id, video_url, language = job
        logger.info("Claimed job %s: url=%s lang=%s", job_id, video_url, language)

        try:
            video_id = process_job(job_id, video_url, language)
            mark_completed(job_id, video_id)
            logger.info("Job %s completed -> video_id=%s", job_id, video_id)
        except Exception as exc:
            # Never let one bad job kill the worker. Record the failure and move on.
            logger.exception("Job %s failed.", job_id)
            try:
                mark_failed(job_id, f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception("Could not even record failure for job %s.", job_id)


if __name__ == "__main__":
    main()
