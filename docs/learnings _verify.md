# ClipSutra — Learnings Log

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

## First-run benchmarks are contaminated — always take the second number
**Date:** 2026-06-17 · **Stage:** 1 · **Status:** core habit

**Question:** Is BGE-M3 too heavy to run locally? First benchmark looked alarming: 302s load, 32s embed for 7 chunks (~4.5s/chunk), which extrapolated to ~4.5 min of embedding for a 30-min video and a thermal-throttling scare.

**Answer:** The first run was contaminated. The 302s "load time" secretly included the ~2-minute one-time download of the 2.27GB model file (the download progress bar was still running, interleaved with the benchmark output). The 32s embed was also inflated by cold caches and the download churning disk/CPU in parallel. Second run, with the model already on disk: **load 103s, embed 13.55s for the same 7 chunks (~1.9s/chunk)** — embedding was less than half the "measured" first-run cost. RAM held flat at 1.73GB delta both runs. The scary extrapolation evaporated: real 30-min embedding ≈ 1.5–2 min, not 4.5.

**Transferable lesson:** The first measurement of anything is suspect — it measures your *cache/cold-start state*, not your code. Downloads, cold disk caches, JIT warmup, and disk paging all hide inside a first run. Always take the second number as the truth, and measure load-time and inference-time *separately* (in production the model loads once and stays resident, so only inference latency recurs). Also: never trust a per-unit cost from a tiny sample to extrapolate a large one — embedding batches, so throughput per chunk usually *improves* at scale rather than scaling linearly.

**Links:** ADR-001, docs/benchmarks/embedding_benchmark.md

---

## Optimize search latency (user-felt), not ingestion latency (batch/background)
**Date:** 2026-06-17 · **Stage:** 1 · **Status:** guiding principle

**Question:** Should we offload steps to Colab now to shave minutes off processing, since "people won't use a system where a 30-min video takes 10 min"?

**Answer:** That instinct aims latency optimization at the wrong place. ClipSutra is a **batch newsroom pipeline**, not a live interactive tool. Ingestion (download → transcribe → embed → index) happens *once, in the background, before anyone searches*. The editor isn't watching a stopwatch during ingest; they search and pull clips *later*. So the latency that's actually user-felt — and the real NFR — is **search (<2s)**. Whether ingestion takes 3 or 7 minutes is nearly invisible to the user. "People don't prefer slow systems" is true for *interactive* latency, not for batch indexing.

Separately: you can't optimize a multi-stage total before building it, because you don't yet know which stage dominates. Most of the feared "heavy local compute" is already offloaded or fast — transcription is Groq (cloud), diarization is already lazy+Colab (ADR-008), enrichment is API calls. The likeliest real bottleneck at Stage 4 isn't laptop compute at all — it's **free-tier rate-limit waiting** (spacing API calls under RPM caps), which Colab does nothing to fix; batching LLM calls into one request would help far more.

**Transferable lesson:** Distinguish interactive latency (user is waiting → optimize hard) from batch latency (runs in background → "good enough" is genuinely good enough). Never optimize a multi-stage pipeline's total before it's built and instrumented — measure which single stage dominates, then optimize only that. Premature optimization across an unbuilt pipeline guarantees you optimize the wrong step. Moving a step to Colab later is a *swap* (same provider-swap pattern as splitter/ASR), not a rewrite — so building local-first costs nothing and locks in nothing.

**Links:** ADR-008, ADR-011

---

## ffmpeg `-c copy` on FLAC segments clones a stale duration header → Groq 500s
**Date:** 2026-06-23 · **Stage:** 1 · **Status:** fixed in split.py

**Question:** transcribe.py kept getting 500/502 from Groq on every chunk. Groq's request logs showed `input_audio_seconds = 2184` (the full 36-min master) for every request — but the chunks were real, separate ~600s files. How can a 600s chunk report 2184s?

**Answer:** split.py used `-c copy` (stream-copy) with ffmpeg's segment muxer. FLAC stores total length in its STREAMINFO header. Stream-copy clones the *master's* header byte-for-byte into every segment without recomputing `total_samples`, so each 600s chunk's header *claimed* 2184s while only ~600s of audio frames followed. Groq read the header (logged 2184s), then its decoder hit end-of-stream at 600s while the header promised more → it treated the file as truncated/corrupt → 500/502. The non-zero start PTS on later chunks (600.048, 1200.024) was the same disease: `-reset_timestamps` doesn't take effect under stream-copy. **Fix:** drop `-c copy`, re-encode segments with `-c:a flac` so ffmpeg writes a fresh correct header and true zero-based timestamps. Cost is sub-second per chunk at 16kHz mono; split runs once per video, not in any hot path. (Verify re-encoded chunks stay s16/16kHz/mono afterward.)

**Transferable lesson:** Stream-copy (`-c copy`) is fast because it moves bytes without decoding — but that means it does NOT recompute container metadata like duration/sample-count headers. When you *segment* with stream-copy, every piece can inherit the whole file's metadata and lie about itself. A server that trusts the header before reading the stream will see a header/stream mismatch and reject it as corrupt. The error surfaces far downstream (a remote API's 500) from the real cause (a local muxing flag), and the diagnostic that cracked it was a server-side log column (`input_audio_seconds`) revealing what the server *thought* it received vs. what was actually sent. Lesson: when a remote service rejects your file, check what *it* reports about the file, not just what you think you sent — and re-encode rather than stream-copy whenever segment metadata must be correct.

**Note for Phase B:** the VAD-aware splitter will also cut FLAC segments — it must re-encode too, or this exact bug returns.

**Links:** ADR-009, split.py

## Groq's FLAC decoder 500s on some audio content; same samples as WAV succeed
**Date:** 2026-06-23 · **Stage:** 1 · **Status:** fixed via FLAC→WAV fallback in transcribe.py

**Question:** After the header-mismatch fix, chunks 00/01/02 transcribed fine but chunk_03 reproducibly returned 500 on every clean call (5/5 attempts, no retry-storm, format-identical to its siblings: s16/16kHz/mono, decodes clean, under size cap). Not the header bug, not size, not format validity. What's left?

**Answer:** A controlled experiment isolated it: re-encoding chunk_03 to WAV (pcm_s16le, identical 16kHz mono samples, lossless) → 200 OK in 11s. Same audio samples, different container: FLAC reproducibly fails, WAV succeeds. So it's a **Groq server-side FLAC-decode edge case** triggered by this specific chunk's audio content — nothing wrong with the file or pipeline. (A Groq community forum thread independently reported content-specific 500s on the transcription endpoint.) Fix: FLAC→WAV fallback in transcribe.py — on a *persistent* 500 (only after the normal backoff retries are exhausted), re-encode the chunk to WAV and try once; cache the WAV result like any other. Keeps FLAC's size advantage (6.7 vs 11.7 MB) for the ~99% of chunks that work, pays the WAV cost only when needed.

**Two sub-lessons surfaced:**
- **Double-retry layering:** the custom backoff loop (5×) stacked with the Groq SDK's internal retries (default max_retries=2) → chunk_03 actually hit Groq ~15×, not 5. Fix: `Groq(max_retries=0)` so the application loop is the *single* retry authority. When you write your own retry logic, disable the library's, or they compound invisibly.
- **Whisper segmentation is non-deterministic:** the same audio returned 82 segments on one call and 66 on another. Text content is equivalent; only segment-boundary counts drift. Don't treat segment count as a stable fingerprint when comparing runs.

**Transferable lesson:** When a file is rejected but "looks valid," change ONE variable at a time to isolate the cause — re-encoding to a different container while holding the audio samples identical is a clean controlled experiment that separates "bad audio" from "bad container handling on the server." The fix belongs at the layer where the problem lives (a targeted fallback for the rare failing case), not as a blanket change that penalizes every request. And always make sure only one component owns retry behavior.

**Links:** ADR-009, ADR-010, transcribe.py

## Stage 1 search works end-to-end; relevance scores capped by Hindi ASR noise (not the vector layer)
**Date:** 2026-06-23 · **Stage:** 1 · **Status:** Stage 1 complete; quality ceiling identified, deferred to Stage 2/Phase B

**Question:** Full pipeline proven end-to-end (URL→FLAC→split→Groq→merge→embed→Qdrant→search), and cross-lingual retrieval works — an English query ("saffron terrorism") with zero shared characters surfaced the Hindi window for "भगवा आतंकवाद". So why are the similarity scores only modest (0.47–0.54) when strong bge-m3 cosine matches usually sit ~0.6–0.7+?

**Answer:** The bottleneck is upstream of the embedding, not in it. The indexed Hindi transcript text is degraded by ASR errors — Whisper garbled consonants on this audio ("आतंवाद" missing क, words run together like "जहरीजाहोगया"). The embeddings faithfully represent broken text, so similarity compresses. This is garbage-in propagating through a correct vector layer, not a bug in index.py or a model failure. The fix lives exactly where the architecture already put it: Phase B's confidence gate (gate.py) flags low-quality segments, and Stage 2's Sarvam routing handles Hindi/Hinglish ASR better than generic Whisper. The decision records called this shot turns earlier — noisy Hindi was predicted to be the hard part and deferred to a stage built for it; real data confirmed the ceiling sits precisely there.

**Transferable lesson:** When a retrieval/search system returns *directionally correct but weak* results, check the quality of the indexed text BEFORE blaming the embedding model or the vector DB. Retrieval quality is bounded by document quality — a perfect embedder on garbled input still yields compressed scores. Diagnose top-to-bottom: are the documents themselves clean? Cross-lingual retrieval working at all (English query → correct foreign-language hit) proves the vector layer is sound, which isolates the problem upstream to ingestion/ASR. Also: modest absolute scores don't mean broken — the *ranking* was right (on-topic hits surfaced), which is what actually matters for search.

**Links:** ADR-010 (trust-ASR/gate-output), gate.py (Phase B), Stage 2 Sarvam routing



## Sarvam A/B test was confounded — different chunking per arm invalidated the result
Date: 2026-07 · Stage: 2 · Status: corrected, gate reopened

Q: Sarvam A/B (item #1) showed scores 0.37–0.46 vs Groq's 0.42–0.54 → initially
read as "Sarvam is worse, close the gate." Was that valid?

A: No. The Groq baseline came from properly chunker.py-windowed text; the Sarvam
transcripts were embedded as raw 10-min bulk blocks (9,000+ chars), evaluated in
an isolated script that never ran through the chunker layer. Two variables changed
at once (ASR engine AND chunk granularity), and a same-day sliding-window test
showed chunk size ALONE swings scores by roughly the full gap being attributed to
Sarvam. The comparison measured chunking, not ASR quality.

Transferable lesson: change one variable at a time. Before trusting an A/B result,
verify both arms went through identical downstream processing. An isolated
"quick eval" script is the classic way to silently reintroduce a confound that
the main pipeline had already solved — this is the same class of mistake as
skipping a proven step to save time.

Links: ADR-012, stage2_spec.md priority #1 (reopened)



## Correction: the 0.42–0.54 score ceiling is NOT primarily ASR noise
Date: 2026-07 · Stage: 2 · Status: supersedes learnings entry #10's diagnosis

Q: Entry #10 attributed low search scores to garbled Hindi ASR from background
noise. Confidence-gate telemetry (avg_logprob, no_speech_prob, compression_ratio)
on all 299 cached segments — did that hold up?

A: No. Only 9/299 segments (<3%) crossed noise thresholds; no_speech_prob was
flat 0.0 across nearly the whole file. The audio is clean studio debate audio,
transcription quality is high. The real dominant factor is semantic dilution —
embedding whole 10-min blocks instead of tight windows — confirmed by a sliding-
window test spiking the top Hindi query score to 0.5550 immediately.

Transferable lesson: a plausible-sounding diagnosis (noisy audio) can be wrong
even when the fix it points to sounds reasonable. Read the actual telemetry
before committing engineering effort to a hypothesis — the gate you build to
"prove" a theory is also the gate that can disprove it, and that's a good
outcome, not a wasted one.

Links: learnings entry #10 (corrected), ADR-010