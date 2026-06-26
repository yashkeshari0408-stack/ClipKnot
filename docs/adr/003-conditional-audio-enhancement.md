# ADR-003: Conditional, A/B-tested audio enhancement (not always-on)

**Status:** Accepted (implemented in Stage 2)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Real audio (especially field reports) carries noise, hum, and background music. Naively denoising every file is tempting but wrong: modern ASR is trained on noisy audio, and aggressive enhancement can REDUCE accuracy and introduce artifacts. Heavy isolation models (DeepFilterNet, Demucs) also add serious latency if run on everything.

## Decision
Enhancement is conditional and verified, not blanket:
1. Cheap noise-floor check first (ffmpeg `volumedetect` / `silencedetect`) — clean audio skips enhancement entirely.
2. Only chunks above a noise threshold route to enhancement (afftdn/high-pass → DeepFilterNet → Demucs as escalating fallback for field reports).
3. A/B rule: transcribe both raw and enhanced for flagged chunks; keep whichever scores better on ASR confidence. Never assume cleaning helped.

## Alternatives Considered
- **Always-on denoising** — rejected: cripples latency and can hurt accuracy.
- **Never denoise** — rejected: extreme field audio (crowd chants, wind) genuinely needs it.

## Consequences
- Latency stays low on clean/normal audio; heavy work only where it's earned.
- Requires a confidence-scoring + comparison step (shared with ADR-010's gate).
- The raw-vs-enhanced-vs-clean accuracy comparison becomes a key project deliverable.

## Notes
Stage 1 uses only the cheap codec filter `highpass=f=80` (NOT lowpass=3000 — that clips speech consonants at 4–8kHz and hurts ASR). Whisper `prompt` is a soft bias, not reliable artifact control — VAD (ADR-010) is the real mechanism for suppressing non-speech.
