# ADR-001: Managed ASR APIs over local Whisper models

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Transcription is the pipeline's core. Options range from fully local (faster-whisper) to managed APIs (Groq, Sarvam). Dev hardware is an 8GB Windows laptop; large local Whisper models won't fit comfortably, and the project runs on free tiers with no budget.

## Decision
Use managed ASR APIs as primary: Groq Whisper Large v3 for English, Sarvam AI for Hindi/Hinglish (added in Stage 2). Keep a local faster-whisper-small only as an offline fallback.

## Alternatives Considered
- **Local faster-whisper (large) as primary** — rejected: won't run well on 8GB; slow on CPU.
- **OpenAI Whisper API** — rejected: Groq is far cheaper/faster on free tier (~228x real-time) for the same model.

## Consequences
- Fast transcription (~228x real-time), near-zero local compute for this step.
- Introduces external dependency + rate limits → must handle 429s and the 25MB free-tier upload limit (see ADR-009).
- Must not send internal/company footage to free tiers (data-training risk) — public YouTube only for prototype.
- Provider-swap interface (`transcribe(audio) -> segments`) keeps us from lock-in.

## Notes
Groq free tier ~2,000 audio requests/day (verify in console). Pre-converting to 16kHz mono before upload reportedly improves accuracy ~15%.
