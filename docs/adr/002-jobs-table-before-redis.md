# ADR-002: Postgres jobs table before a Redis queue

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Stage 1 is synchronous (the API call blocks until the video is processed). This is fine at ~10 videos but will not hold. Stage 2 needs async processing so the UI returns immediately. The simplest async mechanism vs. a "proper" queue is the question.

## Decision
Introduce async with a Postgres `jobs` table (status: pending → processing → completed/failed) polled by a background worker, BEFORE bringing in Redis. Redis arrives only at Stage 3 when reliability/retry/burst-absorption become real needs.

## Alternatives Considered
- **Jump straight to Redis/Celery** — rejected (for Stage 2): premature; adds infra before the problem that justifies it exists.
- **Stay synchronous** — rejected: blocks the user, won't scale past a handful of videos.

## Consequences
- Simplest thing that works; one new table, no new infrastructure.
- Polling is slightly wasteful but trivial at this scale.
- Creates a clean, documented upgrade path to Redis (ADR-004) — good interview narrative.

## Notes
This staged escalation (sync → jobs table → Redis → K8s) is the spine of the whole project; each step pulled in by a real problem, never pushed in speculatively.
