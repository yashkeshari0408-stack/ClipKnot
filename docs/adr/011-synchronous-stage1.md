# ADR-011: Stage 1 is deliberately synchronous

**Status:** Accepted (Stage 1)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
There's a temptation to build async processing from the start. But Stage 1's goal is a thin, working vertical slice to validate that transcript search is useful — not to build infrastructure.

## Decision
Stage 1's `/ingest` endpoint blocks until processing completes. No queue, no jobs table, no workers. Single process, single language (English), no diarization, no enrichment.

## Alternatives Considered
- **Async from day one** — rejected: premature infrastructure before the validating problem (slow blocking calls at scale) is even felt.

## Consequences
- Fastest path to a demoable, user-testable slice.
- The blocking pain is intentional — it's the honest justification for ADR-002 (jobs table) in Stage 2.
- Not production-shaped, and that's fine for Stage 1.

## Notes
Roadmap is frozen for Stage 1 scope. Resist mid-stage redesign urges; new ideas become ADRs for later stages, not Stage 1 rework.
