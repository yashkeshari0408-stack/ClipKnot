# ADR-015: Multi-worker concurrency deferred; single worker for now

**Status:** Accepted (Stage 2) — revisit at a later stage, not now
**Date:** 2026-07
**Deciders:** Yash (with Claude input)

## Context
Async ingest (ADR-002/ADR-011) needs a worker to process jobs off the queue. A single polling worker processes videos strictly sequentially — video 2 doesn't start until video 1 fully completes (ingest→split→transcribe→merge→chunker→index, several minutes). True concurrency requires multiple worker processes claiming jobs atomically from the same table, which raises real questions: how many workers is safe given shared Groq/Sarvam free-tier limits (2,000 req/day, 7,200 audio-sec/hour) and local RAM (~1.7GB per BGE-M3 embedding pass); where workers run (local machine can't usefully run many in parallel — 8GB RAM, one embedding pass alone is a real chunk of it); and whether a free-tier cloud VM (Oracle Cloud's free tier, or similar) could host additional worker processes without cost.

## Decision
**Defer.** Ship with exactly ONE worker process for now. It fully satisfies the actual pain ADR-011 identified (blocking `/ingest` calls) — the user gets a job ID instantly regardless of queue depth. Sequential processing is an accepted limitation until real volume makes it a felt bottleneck, not a hypothetical one.

**Revisit at:** the point where sequential processing is measurably too slow for real usage (e.g., a genuine backlog of unprocessed videos), OR at final-stage productionizing when deployment topology is being decided anyway. At that point, evaluate:
- Multiple workers polling one table, using an atomic claim (`UPDATE ... WHERE status='pending' ... RETURNING`) to avoid double-processing.
- Whether a free-tier cloud VM (Oracle Cloud Free Tier's Always Free compute shapes, or similar) can host 1-2 additional workers without cost — offloading concurrent processing from the local 8GB laptop.
- Whether Redis (ADR-004) becomes worth adopting at that point for proper queue coordination vs. naive DB polling with multiple claimants.

## Alternatives Considered
- **Build multi-worker now** — rejected: no felt need yet (matches every other "defer until evidence demands it" decision in this project — Redis, K8s, enhancement stack). Adds coordination complexity (atomic claims, race conditions) for a problem that doesn't exist at current volume.
- **Multi-threaded single process instead of multi-process workers** — not evaluated in depth; multi-process is simpler to reason about and matches the project's existing pattern (backend/frontend/pipeline already run as separate processes).

## Consequences
- Ingestion throughput is bounded by one worker's sequential pace until this is revisited.
- No coordination/race-condition code needed now — genuinely simpler.
- When revisited, the free-tier-cloud-VM question is a real, cheap option worth checking before assuming paid infrastructure is needed.

## Notes
This is a "check later" ADR, not a "build later" spec — no committed design yet, just the question flagged so it isn't forgotten or rediscovered from scratch at the production-deployment stage.
