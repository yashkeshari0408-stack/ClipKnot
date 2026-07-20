# ADR-013: ASR resilience — FLAC→WAV fallback and single retry authority

**Status:** Accepted (Stage 1) — built in response to real production failures
**Date:** 2026-06-23
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Stage 1 hit three stacked, mutually-masking failures when calling Groq Whisper, all discovered on a real 36-minute Hindi video:

1. **Client timeouts (499s).** The Groq SDK's default 60s request timeout was too short to upload a ~10MB chunk and wait for transcription. The client hung up mid-request; Groq logged HTTP 499 ("client closed request") — a *self-inflicted* error, not a Groq failure.
2. **Double-retry storm.** A custom backoff loop (5×) stacked with the SDK's *internal* retries (`max_retries=2` by default), so one failing chunk actually hit Groq ~15 times, not 5. Two retry authorities, each unaware of the other.
3. **Reproducible 500s on one chunk.** One chunk 500'd on 5/5 clean attempts while its format-identical siblings succeeded. A controlled experiment (re-encode the *same audio samples* to WAV, change nothing else) returned 200 OK in 11s → **a Groq-side FLAC-decode edge case triggered by that chunk's audio content**, not a bad file.

## Decision
1. **Explicit generous client timeout** — `Groq(timeout=300.0)`. Covers upload + round-trip for large audio chunks.
2. **Single retry authority** — `Groq(max_retries=0)` so the application's backoff loop is the *only* thing retrying. Never let the library and the app both retry.
3. **Retry classified by transient-vs-permanent:**
   - timeouts / connection errors / 5xx / 429 → **transient** → exponential backoff + retry
   - 4xx → **permanent** → abort immediately (a malformed request fails identically every retry)
   - Back off *between* attempts, never after the final one (avoids a pointless trailing sleep before reporting failure).
4. **FLAC→WAV fallback** — only *after* the backoff loop exhausts on a **persistent 5xx**: re-encode the chunk to WAV (identical samples), try once, cache the result like any other. If WAV also fails, give up and report. Temp WAV deleted in `finally`.

## Alternatives Considered
- **Switch all output to WAV** — rejected: a 10-min chunk is ~19MB WAV vs ~10MB FLAC, tightening the margin under Groq's 25MB cap for every request, to fix a rare edge case.
- **Switch to MP3** — rejected: lossy; mild quality risk on already-noisy Hindi audio, against ADR-010's "trust the audio" spirit.
- **Fallback on the first 500** — rejected: most 500s are transient and clear on retry; converting immediately wastes work.

## Consequences
- FLAC's size advantage is kept for the ~99% of chunks that work; the WAV cost is paid only where earned.
- Per-chunk response caching (`_response.json`) means re-runs never re-bill Groq audio-seconds — critical while debugging (free tier: 25MB/request, 2,000 req/day, **7,200 audio-seconds/hour**).
- The fallback is not yet exercised end-to-end in a fresh run (the triggering chunk is cached); it will prove itself on the next video that hits a bad FLAC chunk.

## Notes
**Whisper segmentation is non-deterministic** — the same audio returned 82 segments on one call and 66 on another. Text content is equivalent; only segment-boundary counts drift. Don't treat segment count as a stable fingerprint when comparing runs.

**Transferable:** when a remote service rejects a file that "looks valid," change ONE variable at a time (re-encode container, hold audio samples identical) to isolate server-side handling from bad data. And read what the *server* reports about your request (Groq's `input_audio_seconds` log column) rather than trusting what you think you sent.
