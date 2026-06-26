
# ClipKnot — Stage 1 Implementation Spec (consolidated)
### Supersedes the Stage 1 section of Roadmap v2. All decisions from design discussions baked in.

> **Scope:** YouTube URL → searchable transcript with timestamp jump. Synchronous, single-process, deliberately simple. No diarization, no enrichment, no queue — those have their stages.

---

## Runtime pipeline (DATAFLOW order — how data flows when the system runs)

> ⚠️ This is the **runtime architecture**, NOT the build order. Do not build top-to-bottom. VAD sits early in the dataflow but is built LAST (see Build Order below). The order data flows ≠ the order you write code.

```
URL
 → [1] ingest: audio-only download (yt-dlp) + metadata
 → [2] convert: 16kHz mono FLAC (ffmpeg)        [combined with ingest in code]
 → [3] vad: speech-region detection (Silero VAD, ONNX) — skip music/silence
 → [4] split: speech regions → chunks < 24MB (size-checked, not time-assumed)
 → [5] transcribe: Groq Whisper Large v3, verbose output, per chunk
 → [6] gate: confidence check per segment (avg_logprob, no_speech_prob,
            compression_ratio); flagged chunks → afftdn enhance → retry once
            → keep better-scoring result
 → [7] merge: offset-correct chunk timestamps to video time; dedupe
            overlap regions (interval merge)
 → [8] chunk_text: semantic windows (~30–60s, overlapping) from merged
            segments; preserve start_s + end_s of window
 → [9] embed: BGE-M3 → Qdrant upsert
 → [10] serve: FastAPI /ingest, /search → Next.js page, YouTube embed
            seeks to start_s of clicked result
```

## Decisions locked (each is an ADR)

| # | Decision | Rationale |
|---|---|---|
| ADR-006 | **Audio-only ingest.** Video never downloaded at ingest. | Bandwidth/disk; Groq needs audio only. |
| ADR-007 | **Lazy video fetch** (Stage 4): on clip approval, download only the clip's time range via `yt-dlp --download-sections`, padded ±2s, frame-accurate re-encode (`--force-keyframes-at-cuts`). Retry ×2, fallback = full download for that job. | ~98% bandwidth saving per clip; stream-copy cuts snap to keyframes, hence re-encode. |
| ADR-008 | **Lazy diarization.** Not run at ingest; only when Stage 4 enrichment is requested. | Search doesn't need speakers; diarization on CPU is the single biggest latency risk (can approach real-time). Candidate faster alternative under evaluation (article pending review). |
| ADR-009 | **Transport chunking ≠ semantic chunking.** Audio is split for Groq's 25MB free-tier per-request limit; embedding chunks are built from returned *text* segments. | Conflating these breaks either the API calls (oversize) or the timestamps. |
| ADR-010 | **Trust ASR on mild noise; gate the output instead of pre-cleaning input.** VAD removes non-speech (kills Whisper hallucination on music stings); per-segment confidence scores flag locally bad audio; only flagged chunks get enhancement + one retry. | Whisper is trained on noisy audio; global pre-cleaning can hurt accuracy. Full noise machinery (DeepFilterNet/Demucs for field reports) remains Stage 2. |
| ADR-011 | **Deliberately synchronous.** /ingest blocks until done. | The pain justifies Stage 2's jobs table honestly. |

## Data contracts

**Ingest artifacts** (`data/raw/`):
- `{video_id}.flac` — 16kHz mono
- `{video_id}.json` — `{video_id, source_url, title, channel, duration_s, upload_date}`
- Idempotent: artifacts exist → skip (re-runnable by a future crashed worker).

**Merged transcript** (`data/transcripts/{video_id}.json`):
```json
{
  "video_id": "...",
  "language": "en",
  "segments": [
    {"start_s": 12.4, "end_s": 18.9, "text": "...",
     "avg_logprob": -0.21, "flagged": false, "retried": false}
  ],
  "timings": {"download_s": 0, "vad_s": 0, "transcribe_s": 0, "...": 0}
}
```
`start_s`/`end_s` are **video-absolute** (chunk offset already applied).

**Qdrant payload per point:** `{video_id, start_s, end_s, text, source_url, title}`. Collection: `clipsutra_chunks`, cosine distance, BGE-M3 dims.

## The two algorithms worth doing carefully

1. **Offset-merge (step 7).** Groq returns timestamps relative to each audio chunk. For chunk *i* starting at offset *Oᵢ*: every segment's time += *Oᵢ*. Where chunk *i* and *i+1* overlap, segments in the overlap window appear twice — keep one (prefer the higher-confidence copy). This is interval merging; dry-run it on paper with 3 fake chunks before coding.
2. **Semantic windowing (step 8).** Slide over merged segments grouping into ~30–60s windows with ~1 segment (or ~50 token) overlap between consecutive windows. Window start_s = first segment's start_s; end_s = last segment's end_s.

## Confidence gate thresholds (step 6)

Starting values — **tune empirically on your 15–20 test videos and record the tuning table in docs:**
- `no_speech_prob > 0.6` → likely non-speech, drop or flag
- `avg_logprob < -1.0` → low confidence, flag for retry
- `compression_ratio > 2.4` → likely repetitive hallucination, flag

Flagged chunk → `ffmpeg afftdn` (+ high-pass 80–100Hz) → re-transcribe → keep the version with better aggregate scores. One retry max in Stage 1.

## Build order (CONSTRUCTION sequence — different from dataflow order above)

> Principle: build the thinnest end-to-end path first with a *naive* splitter, prove URL→search works, THEN add the smart (VAD) splitter and the confidence gate. Each addition then has a known-good baseline to debug against. Naive and VAD splitters share the same output contract (chunk files + `manifest.json` of offsets), so they're swappable — that's why VAD can come last without rework.

**Phase A — thin path (get one clickable result):**
1. `ingest.py` — URL → 16kHz mono FLAC + metadata json, idempotent, polite failures *(current milestone)*
2. `split.py` (NAIVE) — split FLAC into <24MB chunks by size/time; write `manifest.json` with each chunk's `start_offset_sec`. **No VAD yet.**
3. `transcribe.py` — Groq client, verbose response, 429 exponential backoff
4. `merge.py` — offset correction + overlap dedupe *(the interesting algorithm)*
5. `chunker.py` — semantic windows from merged segments
6. `index.py` — BGE-M3 + Qdrant upsert (Qdrant: native Windows binary or Docker Desktop container)
7. `api/` — FastAPI `/ingest` (blocking), `/search?q=` (embed query → top-k → payloads)
8. `frontend/` — single Next.js page: search box → result cards → YouTube iframe `?start={start_s}`

**→ Milestone: end-to-end search works. This is the real Stage 1 demo.**

**Phase B — quality layer (added last, each with the thin path as baseline):**
9. `split.py` (VAD UPGRADE) — drop in Silero VAD (ONNX, CPU) to shave silence/music and chunk on speech boundaries; **same manifest contract**, so nothing downstream changes. Size-check each chunk (`os.path.getsize`), don't assume minutes→MB.
10. `gate.py` — confidence checks (avg_logprob, no_speech_prob, compression_ratio) + selective afftdn retry
11. Timing instrumentation throughout: every step logs `step_name duration_s` (future Grafana metrics, today's log lines)

## Non-functional targets (Stage 1, without diarization)

| Metric | Target |
|---|---|
| 30-min video, end-to-end | < 6 min (benchmark and record actuals per step) |
| 45-min video | < 10 min |
| Search latency | < 2s |
| Bad URL / private video | Clear error message, no traceback |
| Re-run same URL | Skips cleanly (idempotent) |

## Done means

One command ingests a URL; the Next.js page finds a phrase spoken at minute 23 of a 45-min video and one click puts the embedded player there; the timings log shows where every second went; ADRs 006–011 are in `docs/adr/`; works on a 5-min and a 45-min video, English first (Hindi routes in at Stage 2).