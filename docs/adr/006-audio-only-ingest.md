# ADR-006: Audio-only ingest (no video download at ingest time)

**Status:** Accepted (Stage 1)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
The pipeline ingests YouTube videos but Stage 1 only transcribes and indexes text. Downloading full video at ingest wastes bandwidth and disk; Groq's ASR needs audio only.

## Decision
At ingest, download only the audio stream (yt-dlp audio format selector) and extract 16kHz mono FLAC. Video is never fetched at ingest. Output: `{video_id}.flac` + `{video_id}.json` metadata. Idempotent — existing artifacts cause a skip.

## Alternatives Considered
- **Download full video at ingest** — rejected: ~10x bandwidth/disk for frames never used in Stage 1.

## Consequences
- Fast, lean ingest on an 8GB machine.
- Stage 4 clip-cutting needs video → handled by lazy fetch (ADR-007), not by changing this.
- Idempotency makes this safe for future crashed-and-retried workers (Stage 3).

## Notes
16kHz mono is the ASR-expected format. FLAC = lossless, smaller uploads to fit Groq's 25MB limit (ADR-009).
