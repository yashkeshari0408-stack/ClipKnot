# ADR-012: BGE-M3 as the embedding model, run locally via sentence-transformers

**Status:** Accepted (Stage 1) — backed by measurement, not opinion
**Date:** 2026-06-17
**Deciders:** Yash

## Context
Content is Hindi, English, and Hinglish (code-mixed at the sentence level). The embedding model must handle all three in a shared vector space, and must run on an 8GB Windows laptop. Two candidates: **BAAI/bge-m3** (2.2GB) and **intfloat/multilingual-e5-large** (~1GB, 560M params). Both output 1024 dims.

An additional constraint surfaced during implementation: **FastEmbed 0.8.0 does not package bge-m3** (verified from package contents — only `bge-*-en`/`-zh` variants ship). So the Qdrant `models.Document` auto-embed path cannot run m3 at all.

## Decision
Use **BGE-M3**, loaded via **sentence-transformers**, encoding to raw 1024-dim float lists that are passed directly to Qdrant (NOT via `models.Document`/FastEmbed).

**Also rejected: content-specific model routing** (e.g. Hindi→one model, English→another). Different embedding models produce *incompatible vector spaces* — mixing them in one collection breaks similarity entirely. And Hinglish is code-mixed *within a sentence*, so there is no clean language to route on. One multilingual model is the architecturally correct answer, not a compromise.

## Alternatives Considered
- **multilingual-e5-large** — viable fallback: half the size, FastEmbed-native (clean `models.Document` path), still multilingual. Rejected as primary because a 2026 benchmark across 12 Indian languages showed **BGE-M3 at ~32% Recall@1 vs E5's ~27%** — a real edge on exactly our target languages. Hindi retrieval quality *is* the project's differentiator; trading it away for 1GB was the wrong trade if the hardware could take it. (Also note: e5 requires `query:`/`passage:` prefixes; m3 does not.)
- **Per-content routing** — rejected (see above): incompatible vector spaces, breaks cross-lingual search, and impossible for code-mixed Hinglish.
- **FastEmbed `models.Document` auto-embed** — not available for m3; forced the sentence-transformers path.

## Consequences — measured on target hardware
| | Result |
|---|---|
| Peak process RAM | **1.73–1.76 GB net** (comfortable on 8GB) |
| Model load (warm cache) | ~13–24s; **~103s cold** (one-time; model stays resident) |
| Embed throughput | **~1.3–1.9s per semantic window** (73 windows ≈ 95–120s) |
| Verdict | Runs locally without thrashing. The size difference that's irrelevant on a GPU *is* the cost on CPU — but it's affordable. |

- **Load once, embed many** is mandatory: the model loads at process start (FastAPI lifespan), never per-request.
- **Query and documents MUST be encoded identically** — same model, same kwargs. Enforced structurally via `shared/config.py` (ADR-014).
- Loading via sentence-transformers hits huggingface.co to validate the cache (~12s even when warm). Set `HF_HUB_OFFLINE=1` if hermetic/offline runs are ever needed.
- **Fallback plan if hardware ever can't take it:** either e5-large locally, or keep m3 but move embedding to Colab as a batch step. Neither is needed today.
- Cross-lingual retrieval **validated in production**: an English query ("saffron terrorism") with zero shared characters retrieved the Hindi window containing "भगवा आतंकवाद". This is the capability that justified m3.

## Notes
Collection is `clipsutra_chunks` (1024-dim, cosine) — deliberately kept under the old project name until the Stage 2 re-index, when the rename is free. Encoding is unnormalized (`model.encode(texts)`, no `normalize_embeddings`); Qdrant's COSINE distance normalizes at compare time. If the pipeline ever switches to normalized embeddings, the query path must mirror it.
