# ADR-009: Transport chunking is separate from semantic chunking

**Status:** Accepted (Stage 1)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
"Chunking" was being used for two different things, which caused confusion. Groq's free tier accepts ~25MB per request, so long audio MUST be split to upload. Separately, embeddings need text windows. Conflating them breaks either uploads (oversize) or timestamps.

## Decision
Two distinct, clearly-named layers:
1. **Transport chunking (audio):** split long audio into <25MB segments at silence boundaries to fit Groq's limit. Record each chunk's time offset.
2. **Semantic chunking (text):** build overlapping ~30–60s windows from Groq's returned text segments for embedding, preserving absolute start/end timestamps.

## Alternatives Considered
- **Single audio-chunk = embedding-chunk** — rejected: couples API limits to retrieval granularity; wrong on both axes.

## Consequences
- Requires an offset-merge step: chunk-relative timestamps → video-absolute, plus overlap dedupe (interval merge). This is the key Stage 1 algorithm.
- FLAC compression maximizes audio per chunk under the 25MB cap.

## Notes
Without offset correction, every search result after the first audio chunk jumps to the wrong place in the video. Dry-run the merge on paper with 3 fake chunks before coding.
