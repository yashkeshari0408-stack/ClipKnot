# ADR-007: Lazy video fetch for clip cutting

**Status:** Accepted (applies in Stage 4)
**Date:** 2026-06-11
**Deciders:** Yash (with Claude, ChatGPT, Gemini input)

## Context
Stage 4 cuts approved clips, which needs video. Re-downloading full videos to cut a 40s clip is wasteful. Stream-copy cuts also snap to keyframes, missing exact timestamps.

## Decision
Download only the clip's time range on approval: `yt-dlp --download-sections "*start-end"`, padded ±2s, with frame-accurate cutting (`--force-keyframes-at-cuts` / re-encode rather than `-c copy`). Retry ×2; fallback = full download for that single job.

## Alternatives Considered
- **Full re-download per clip** — rejected: ~98% wasted bandwidth.
- **Stream-copy without re-encode** — rejected: cuts snap to nearest keyframe, off by seconds.
- **Keep video from ingest** — rejected: contradicts ADR-006; most videos never get clipped.

## Consequences
- Huge bandwidth saving; video fetched only for content that's actually published.
- Section downloads can be slow/flaky (YouTube throttling) → retry + full-download fallback.
- ±2s padding also absorbs ASR timestamp drift (speech timestamps aren't frame-perfect).

## Notes
For the internal/company version, this whole mechanism swaps for reading byte-ranges from their storage — pipeline interface unchanged (provider-swap pattern).
