# ADR-010: Trust ASR on mild noise; gate the output, don't pre-clean the input

**Status:** Accepted (Stage 1)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Even "clean" baseline audio has some hiss, hum, or low background music. Two real failure modes: (1) Whisper hallucinates text over non-speech (music stings → "[music]" or invented phrases), and (2) locally noisy segments degrade transcription and timestamp precision. Heavy denoising on everything is wrong (ADR-003), and over-trusting a Whisper prompt to suppress artifacts is unreliable.

## Decision
In Stage 1, handle mild noise with light, cheap measures plus output-side checking:
1. **VAD (Silero) before transcription** — strip music/silence regions so Groq only sees speech. This is the real mechanism for killing non-speech hallucination.
2. **Light codec filter:** `ffmpeg -af "highpass=f=80"` to cut low-end rumble. Do NOT apply lowpass=3000 (clips speech consonants at 4–8kHz, hurts accuracy).
3. **Confidence gate on output:** check per-segment `avg_logprob`, `no_speech_prob`, `compression_ratio`; flag bad segments.
4. **Selective retry:** only flagged chunks get afftdn enhancement + one re-transcribe; keep the better-scoring result.

## Alternatives Considered
- **Global pre-cleaning of all audio** — rejected: Whisper is trained on noisy audio; blanket cleaning can hurt accuracy and adds latency.
- **Whisper `prompt` as primary artifact control** — rejected: soft bias only, not reliable. Kept as a cheap bonus.

## Consequences
- Cheap on clean audio; cost concentrated only where audio actually hurt the transcript.
- Threshold values are not universal — tune empirically on the 15–20 test videos and record the tuning table in docs.
- Shares its confidence-scoring machinery with ADR-003's Stage 2 A/B rule.

## Notes
Suggested starting thresholds: no_speech_prob > 0.6 (drop/flag), avg_logprob < -1.0 (flag), compression_ratio > 2.4 (likely repetition/hallucination, flag).
