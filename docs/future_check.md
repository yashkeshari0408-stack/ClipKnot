
# ClipKnot — Future Check

Unresolved assumptions / deferred questions. Not blocking current work. Review
periodically; move to RESOLVED when closed (keep a one-line record, don't
just delete — it's useful history).

## Open

### videos_urls.csv is single-language per batch run
`--language` applies to the whole ingest run, not per-row. A mixed-language
batch needs a CSV language column added later. Not blocking — current test
set is run in single-language batches anyway.

### Sarvam needs duration/sentence-based windowing, not segment-count
Segment-count windowing (WINDOW_SIZE=4) works for Groq's fine-grained segments
but produces wide (~66s) windows on Sarvam's paragraph-level output — 4
paragraphs ≈ 4x wider than intended. When Sarvam is activated for Stage 4,
chunker needs an engine-aware windowing strategy (duration cap or sentence-
split for Sarvam, segment-count for Groq).

### Whisper special tokens and Urdu-script segments leak into transcript
Seen in production search results — raw Whisper tokens (e.g. `<|af|>`) and
Nastaliq/Urdu-script segments (not filtered/normalized) surface in the text
field on Hindustani-inflected speech. Cosmetic for search (doesn't break
retrieval) but would look unpolished in any user-facing display or Stage 4
editorial output. Fix: strip special tokens, consider script normalization
pass. Low priority — revisit if it recurs at volume or before Stage 4 UI
polish.

---

## Resolved

### Sarvam batch output envelope shape ✅
Assumed: batch JSON == sync SpeechToTextResponse shape. Confirmed correct on
first real batch job (transcript/timestamps/language_code all present as
predicted; parser's fail-loud guards never tripped).

### Sarvam batch API FLAC acceptance ✅
Assumed: FLAC accepted despite sync endpoint hardcoding `audio/wav` Content-
Type. Confirmed: batch API accepted FLAC directly (201 on Azure blob PUT for
every chunk) — Groq-style WAV fallback was never needed.

### Qdrant Cloud vs the Windows-native constraint ✅
Resolved by ADR-016: cloud Qdrant is a managed API connection, not local
infrastructure — doesn't conflict with CLAUDE.md's "Docker/WSL2 reserved for
the Kubernetes stage" constraint, which was written with local dev tooling in
mind. See ADR-016 for the full reasoning.