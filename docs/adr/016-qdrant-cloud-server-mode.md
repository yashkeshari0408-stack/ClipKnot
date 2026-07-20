# ADR-016: Qdrant Cloud (server mode) over embedded/local-file mode

**Status:** Accepted (Stage 2)
**Date:** 2026-07
**Deciders:** Yash (with Claude input)

## Context
Async ingest (ADR-002) requires the worker (writing to Qdrant during indexing) and the backend (reading from Qdrant during search) to run as separate, concurrent processes. Embedded Qdrant (`QdrantClient(path=...)`) takes an exclusive file lock — only one process can hold `data/qdrant_storage` at a time. This is fine for Stage 1 (one process at a time) but breaks the moment worker and backend run simultaneously, which is the normal operating state once async ingest ships.

Docker-based Qdrant server mode was considered but conflicts with a hard constraint in CLAUDE.md: Windows-native dev, Docker/WSL2 reserved for the Kubernetes stage. Qdrant has no native-Windows server binary, so server mode realistically means Docker or Qdrant Cloud — nothing in between.

## Decision
Switch to **Qdrant Cloud (free tier)** — a managed, hosted Qdrant instance reached via `QdrantClient(url=..., api_key=...)` instead of a local file path. This resolves the lock conflict without touching the Windows-native/no-Docker constraint (it's an API connection, not local infrastructure) and is closer to the actual deployment target (Fly.io + Neon — managed cloud services generally, not local containers).

The existing embedded store (`data/qdrant_storage`, 149 points) is kept as an untouched local backup — not deleted.

## Alternatives Considered
- **Docker container** — rejected: would pull Docker into the workflow before the Kubernetes stage, contradicting a deliberate constraint. Solves the lock problem but at the cost of scope creep the constraint exists to prevent.
- **Stay embedded, add lock-and-retry handling** — rejected: doesn't solve the actual need (worker and backend running concurrently is the normal operating mode now, not an edge case); would mean tolerating stalls/retries on every job rather than removing the conflict entirely.

## Consequences
- Confirmed via direct test: simultaneous reader (backend search) + writer (indexer) with zero lock errors — impossible in embedded mode.
- `shared/config.py` now holds `QDRANT_URL`/`QDRANT_API_KEY` (from `.env`) alongside the retained `QDRANT_PATH` (pointing at the embedded backup, unused in normal operation).
- Observed: transient "Batch upload failed, retrying" on cloud upserts (likely cold-connection hiccup to the free-tier cluster) — client's built-in retry absorbs it, final counts always correct. Watch if this recurs at higher volume.
- Free-tier capacity limits apply going forward — not yet a concern at 149 points, worth checking before large-scale re-indexing.

## Notes
This is a genuine, felt-need-driven infrastructure change (concurrent processes exist today), distinct from ADR-015's deferred multi-worker question (which has no current need). Don't conflate the two: this ADR is about one worker + one backend needing to coexist; ADR-015 is about multiple workers, which is still deferred.
