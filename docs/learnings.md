# ClipKnot — Learnings Log

The **why** behind decisions, plus concepts worth keeping. Distinct from:
- `progress.md` = what's done / what's next (status)
- `docs/adr/` = decisions that constrain future code (formal guardrails)

This file = the reasoning and the transferable lessons. Skim the bold headers; Ctrl-F to search.

---

## Embedding model: m3 vs e5 vs content-specific routing
**Date:** 2026-06-15 · **Stage:** 1 · **Status:** decided → try m3 first, fallback e5

**Question:** Which embedding model for Hindi/English/Hinglish content, balancing retrieval quality against an 8GB laptop? And could we route per-content to different models?

**Answer:** Use ONE multilingual model, not per-content routing.
- **Routing is a trap here:** (a) different embedding models produce *incompatible vector spaces* — an m3 vector and an e5 vector aren't comparable even at the same 1024 dims, so mixing them in one collection breaks search; (b) it forces query-side routing + multiple collections + loss of cross-lingual search; (c) Hinglish is code-mixed at the *sentence* level, so there's no clean language to route to. Multilingual single-model handles mixed sentences natively.
- **m3 vs e5:** bge-m3 = 2.2GB, best Indian-language retrieval (~32% Recall@1 vs e5's ~27% in a 2026 12-Indian-language benchmark). multilingual-e5-large = ~1GB (560M params), lighter, slightly weaker on Hindi, needs `query:`/`passage:` prefixes. Both output 1024 dims (Qdrant schema identical).
- **Decision:** try m3 locally on the small Stage 1 test set; watch RAM + time. If it runs, keep it (Hindi is our differentiator). If the laptop chokes → either e5-large locally, or keep m3 but move embedding to Colab as a batch step (per CLAUDE.md's heavy-ML-on-Colab rule).

**Transferable lesson:** Embedding models live in their own vector spaces — query and documents MUST be embedded with the *same* model or similarity is meaningless. For code-mixed/bilingual content, a single multilingual model beats routing on both correctness and simplicity. On a GPU, model size barely affects latency; on a CPU laptop, size *is* the latency/RAM cost — the same decision flips depending on hardware.

**Links:** ADR-001, ADR-009

---

## VAD belongs early in dataflow but LAST in build order
**Date:** 2026-06-15 · **Stage:** 1 · **Status:** resolved

**Question:** The Stage 1 spec lists VAD at pipeline position 3 — does that mean build it third? (Two AI tools kept pulling toward building VAD early.)

**Answer:** No. Two different orderings were being conflated:
- **Runtime/dataflow order** — how data flows when the system runs. VAD correctly sits at position 3 (you want to strip silence/music *before* transport-splitting).
- **Build/construction order** — the sequence you write code in. VAD comes LAST.
Build the thin path first with a *naive* size-based splitter (ingest → split → transcribe → merge → chunk → embed → search), get one clickable end-to-end result, THEN swap the naive splitter for the VAD-aware one. The naive and VAD splitters share the same output contract (chunk files + `manifest.json` of offsets), so the swap is zero-rework.

**Transferable lesson:** The order data flows at runtime is almost never the order you should build in. Build the thinnest end-to-end path first so every later addition has a known-good baseline to debug against — if you build the clever part at the same time as the core, you can't tell which one broke. Numbered dataflow diagrams *look* like to-do lists; they aren't.

**Links:** ADR-010, ADR-011, Stage 1 spec (Build Order, Phase A/B)

---

## Transport chunking ≠ semantic chunking
**Date:** 2026-06-14 · **Stage:** 1 · **Status:** locked

**Question:** "Chunking" was being used for two different things and one AI said "don't chunk the audio" as an absolute — what's correct?

**Answer:** They're two separate layers that must not be conflated:
- **Transport chunking (audio):** split long audio into <24MB segments so each fits Groq's 25MB per-request upload limit. Split at silence boundaries; size-check each chunk (FLAC size depends on content, not duration — don't assume minutes→MB). Record each chunk's time offset.
- **Semantic chunking (text):** build overlapping ~30–60s windows from Groq's *returned text segments* for embedding, preserving absolute timestamps.
Doing only one breaks the pipeline: skip transport chunking and long videos silently fail the upload; skip semantic chunking and embeddings are either too sparse (2s fragments) or too blurry (10-min blocks) for good search.

**Transferable lesson:** The same word ("chunk") can name two unrelated operations in one pipeline. Name them distinctly. A constraint imposed by an external API (25MB) and a constraint imposed by retrieval quality (window size) are different axes and should be solved by different code.

**Links:** ADR-009

---

## The timestamp-offset bug (chunk-relative vs video-absolute)
**Date:** 2026-06-14 · **Stage:** 1 · **Status:** core algorithm in merge.py

**Question:** Why can't we just concatenate Groq's responses from each audio chunk?

**Answer:** Groq returns timestamps *relative to each audio chunk* — starting from 0. So a quote 12s into chunk 2 (which begins 600s into the video) comes back as `start: 12`, not `612`. Concatenate naively and every search result after the first chunk jumps to the wrong place in the video. Fix: for each chunk with offset Oᵢ, add Oᵢ to every segment's start/end during merge. Where adjacent chunks overlap, the overlap region's segments appear twice — dedupe (keep the higher-confidence copy). This is interval merging.

**Transferable lesson:** When you split work into independent units and recombine, check whether each unit's output is in *local* coordinates that need translating back to *global* coordinates. This class of bug is silent — nothing errors, the data is just subtly wrong — which makes it the dangerous kind. Dry-run recombination logic on paper with fake data before coding.

**Links:** ADR-009, Stage 1 spec (merge.py)

---

## Why FastEmbed rejected bge-m3 (and how the real fix was found)
**Date:** 2026-06-15 · **Stage:** 1 · **Status:** informs model decision above

**Question:** `index.py` crashed: "BAAI/bge-m3 is not found among supported models." Was it a missing dependency or a typo?

**Answer:** Neither. FastEmbed only runs models it has pre-packaged ONNX weights for, and bge-m3 isn't in its bundled list (verified directly from the 0.8.0 package: only `bge-*-en`/`-zh` variants ship). The error's "is fastembed installed?" hint was a red herring — it *was* installed. Checking what FastEmbed *does* package surfaced `intfloat/multilingual-e5-large` (native, 1024-dim, multilingual) as a drop-in that preserves the multilingual requirement — which is what made the e5 fallback viable without losing Hindi support entirely.

**Transferable lesson:** "Model X exists on HuggingFace" ≠ "tool Y can run model X locally." Local inference runtimes (FastEmbed, ONNX) only support models someone packaged weights for. When a model string is rejected, list what the tool *actually* supports rather than guessing at the name. Verify package contents directly instead of trusting the error message's suggested cause.

**Links:** ADR-001

---

## Project renamed ClipSutra → ClipKnot; Qdrant collection deliberately NOT renamed
**Date:** 2026-06-24 · **Stage:** 1 · **Status:** decided

Renamed the project to ClipKnot cosmetically (docs, README, logger names) but **kept the Qdrant collection name as `clipsutra_chunks`** — the current 73 vectors are from noisy Hindi ASR and will be rebuilt with Sarvam at Stage 2, so the collection re-indexes anyway then. Renaming the collection now would mean re-indexing twice; the rename is free at the Stage 2 re-index. `COLLECTION_NAME` in `index.py` and the spec's collection line are intentionally left as `clipsutra_chunks` until then.

---