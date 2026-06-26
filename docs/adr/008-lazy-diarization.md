# ADR-008: Lazy diarization (not at ingest)

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Diarization (who-spoke-when) is needed only for Stage 4 speaker-attributed articles, not for Stage 1 search. pyannote on an 8GB CPU is the single biggest latency risk — it can approach real-time (a 30-min video taking ~30 min just for this step).

## Decision
Do not run diarization at ingest. Run it lazily, only when Stage 4 enrichment is requested for a given video. Prefer Colab GPU or a lighter method for the heavy run.

## Alternatives Considered
- **Diarize every video at ingest** — rejected: massive latency cost for data most searches never use.
- **pyannote on local CPU as default** — rejected: too slow on this hardware.

## Consequences
- Stage 1 stays fast; diarization cost paid only when speaker labels are actually needed.
- "I made diarization lazy and cut processing time ~60%" is a strong portfolio line.

## Notes
A faster diarization method (claim: 90-min audio in <2 min) is under evaluation from a Medium article — likely GPU-based or accuracy-traded; verify what it actually measures before adopting. This ADR will be updated if we swap the method.
