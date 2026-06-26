# ADR-004: Redis queue before Kubernetes-native Jobs

**Status:** Accepted (Stage 3)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
By Stage 3 the jobs table (ADR-002) is real but polling-based and fragile under bursts and worker crashes. We need retries, burst absorption, and decoupling of API from workers. Kubernetes isn't present yet (arrives Stage 6), so K8s-native Jobs aren't an option at this point.

## Decision
Introduce a Redis-backed queue between the API and workers in Stage 3. API enqueues; workers consume; failed jobs retry with backoff up to N, then park as failed-with-reason.

## Alternatives Considered
- **Kubernetes Jobs/CronJobs** — rejected at this stage: no cluster yet; would force K8s prematurely.
- **Keep polling the jobs table** — rejected: no clean retry/burst handling; wasteful.

## Consequences
- Real reliability: crash-resilient, burst-tolerant.
- One more service to run (Redis) — acceptable, justified by need.
- When K8s arrives (Stage 6), Redis stays as the queue; we do NOT migrate to K8s Jobs — the queue pattern is sound and portable.

## Notes
Failure matrix (quota exceeded, Qdrant down, worker crash, Redis down) is documented in the roadmap's Stage 3 section.
