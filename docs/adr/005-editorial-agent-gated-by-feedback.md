# ADR-005: Editorial agent gated by Stage 1 user feedback

**Status:** Accepted (Stage 4)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
The editorial layer (clip suggestions, draft articles, headlines) is what turns a "transcript search tool" into a "broadcast-to-digital pipeline" — the part the newsroom actually cares about. But building it before knowing which outputs editors value risks wasting effort on the wrong features.

## Decision
Build the editorial agent in Stage 4, AFTER Stage 1 search is in front of 3–5 real colleagues. Their feedback (what they search for, which outputs they'd want) shapes which enrichment ships first. Every output lands in a human review queue — nothing auto-publishes, ever.

## Alternatives Considered
- **Build the full agent up front** — rejected: high effort on unvalidated assumptions.
- **Never build it (search only)** — rejected: solves the archive problem but not the broadcast-to-digital problem, which is the actual pitch.

## Consequences
- Editorial features are demand-driven, citing real user feedback in ADR-005's eventual update.
- Human-in-the-loop is a hard design constraint, not a feature — critical for newsroom trust.
- Uses Gemini free tier with strict-JSON output (pydantic-validated) + a cheap Groq/Llama newsworthiness pre-filter to conserve quota.

## Notes
Diarization (needed here for speaker attribution) is lazy — run only when enrichment is requested, not at ingest (see ADR-008).
