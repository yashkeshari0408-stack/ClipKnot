# ADR-017: Async ingest via Postgres (Neon) jobs table + single polling worker

**Status:** Accepted (Stage 2) — implements ADR-002's plan
**Date:** 2026-07
**Deciders:** Yash (with Claude input)

## Context
Stage 1's `/ingest` was deliberately synchronous (ADR-011), blocking until the full pipeline completed. ADR-002 named the fix (jobs table before Redis) as Stage 2 work. This ADR records the actual implementation.

## Decision
- **Neon (managed Postgres)** hosts a `jobs` table (`pending → processing → completed/failed`), chosen directly over local Postgres since Neon is the already-planned production database (ADR for Fly.io+Neon deployment) — no local-then-migrate step needed.
- `POST /ingest` inserts a row, returns `{job_id}` immediately (202) — no blocking.
- `GET /jobs/{job_id}` reports status/error/video_id for polling.
- **`pipeline/worker.py`**: a single standalone polling process claims one pending job atomically (`UPDATE ... WHERE status='pending' ... FOR UPDATE SKIP LOCKED ... RETURNING`), runs the six pipeline stages via now-importable functions (`ingest_and_convert`, `split_flac_naive`, `transcribe_video`, `merge_video_transcripts`, `build_semantic_windows`, `index_semantic_windows`), marks `completed`/`failed`.
- **Minimal refactors, zero behavior change to batch paths:** `transcribe.py` gained `transcribe_video(video_id)` (extracted from the batch loop); `index.py` gained an optional `video_id` filter (`None` = existing batch behavior).
- **Single worker only** — see ADR-015; multi-worker concurrency is explicitly deferred, not needed at current volume.

## Alternatives Considered
- **Local Postgres** — rejected: no benefit over Neon given Neon is the confirmed production target; would mean a migration step later for zero gain now.
- **Redis/Celery immediately** — rejected per ADR-002/004: premature before the simpler jobs-table approach is even exercised.

## Consequences
- Verified end-to-end: real worker run through `/ingest` → atomic claim → all six stages (idempotency gates correctly skipped already-cached ingest/split/transcribe steps, no wasted Groq spend) → `completed` status observable via `/jobs` → Qdrant count held at 149 (idempotent re-index, no duplication).
- `channel_binding=require` in the Neon connection string caused no issues with `psycopg2` in a normal Python process (a prior concern from an unrelated Cloudflare Workers project, where a lightweight edge driver lacked SCRAM channel-binding support — not a general Postgres/psycopg2 limitation).
- Search (`/search`) remains fully synchronous (ADR-014) — only `/ingest` is async. This ADR does not change search latency or architecture.

## Notes
**Known follow-up, not yet solved:** the backend's model load (~100s, at FastAPI startup) currently means `/ingest` can't be called usefully until the backend has finished loading — worth a clean readiness check or documentation note so this isn't confusing later. Not a bug, just an ordering dependency to be explicit about.
