# Broadcast-to-Digital AI Pipeline — Roadmap v2 (Merged)
### Staged MVP evolution × full editorial pipeline

> **Supersedes:** roadmap v1 (full pipeline, phase-based) and the ChatGPT system-design doc (MVP staging). This merges them: ChatGPT's staging discipline as the spine, v1's differentiators (noisy audio, Hindi/Hinglish, editorial agent, human-in-the-loop) as committed stages rather than afterthoughts.
>
> **Environment strategy unchanged:** Windows-native dev, Colab for heavy ML, WSL2/Minikube only at the Kubernetes stage. GitHub monorepo from day one.

---

## Vision

Validate that transcript search is genuinely useful, then progressively add the editorial layer and production-grade architecture — each addition justified by real need, documented in an ADR.

## Requirements

**Functional (MVP):** ingest YouTube videos → searchable transcripts → click result, video jumps to timestamp.

**Functional (full product):** + noisy field-audio handling, Hindi/Hinglish transcription, speaker attribution, suggested clips, draft articles, headlines — all landing in a human review queue, never auto-published.

**Non-functional targets:**

| Metric | Target |
|---|---|
| Initial scale | ~10 users, ~100 videos |
| Search latency | < 2s |
| 45-min video processing | < 10 min end-to-end |
| Publish action by AI | Never — human approval always |

---

## Stage 1 — MVP: Transcript Search (the thin slice)

**Build:** yt-dlp/ffmpeg ingest → Groq Whisper Large v3 → chunk (~30–60s windows, overlap) → BGE-M3 embeddings (local/Colab) → Qdrant → FastAPI `/ingest` + `/search` → minimal Next.js page with YouTube embed seeking to matched timestamp.

**Deliberately synchronous** — the API call processes the video inline. Ugly, blocks, fine at 10 videos. The pain this creates is what justifies Stage 2 (that's the point).

**Goal:** put it in front of 3–5 colleagues. Do they actually use search? What do they search for? This feedback gates Stage 4's scope.

**ADR-001:** managed ASR APIs over local models (8GB laptop, free tiers, quality).

## Stage 2 — Async Jobs + Real-World Audio


> ⚠️ SUPERSEDED BY docs/stage2_spec.md — Stage 1 evidence reordered these
> priorities (Sarvam first, enhancement last, not as originally sequenced
> below). This section is kept for historical context only.

[...existing content stays as-is...]

**Async:** `jobs` table in Postgres (pending → processing → completed/failed), background worker process polls it. API returns a job ID immediately; UI shows status.

**Audio reality (reinstated from v1 — core differentiator):**
- Audio QC step: estimate noise level per input; clean audio skips enhancement.
- Noisy field reports: ffmpeg high-pass + `afftdn` first pass → RNNoise/DeepFilterNet for hard cases → Demucs voice isolation as heavy fallback (Colab).
- **A/B rule:** transcribe raw AND enhanced on samples; keep whichever scores better — denoising can *hurt* modern ASR, so measure, don't assume.

**Multilingual (reinstated):** route Hindi/Hinglish content to Sarvam AI STT. BGE-M3's shared vector space means English queries already retrieve Hindi moments — demo this; it's the wow moment for an Indian newsroom.

**ADR-002:** jobs table before Redis (simplest async that works). **ADR-003:** enhancement is conditional + A/B tested, not always-on.

## Stage 3 — Reliability

Redis queue between API and workers (replaces polling). Worker crash → job retried (max N, then failed-with-reason). Burst of uploads → queue absorbs it instead of overload.

**Failure scenarios handled explicitly:**

| Failure | Behavior |
|---|---|
| Groq quota exceeded | Exponential backoff → fallback provider (Sarvam/local faster-whisper) → else park job as `quota_blocked` |
| Qdrant down | Search returns graceful error; ingestion jobs wait, don't fail |
| Worker crash mid-job | Job re-queued; idempotent steps (safe to re-run) |
| Redis down | API rejects new ingests with clear message; search still works |

**ADR-004:** Redis chosen over K8s-native Jobs at this stage (orchestrator not yet present).

## Stage 4 — Editorial Agent (gated on Stage 1 feedback)

The layer that turns "search tool" into "broadcast-to-digital pipeline" — built **only after** colleague feedback confirms which outputs matter, and shaped by it:

- Diarization (pyannote on Colab / Sarvam built-in) → speaker-attributed transcripts
- Topic segmentation (Gemini Flash, strict-JSON output, pydantic-validated)
- Cheap newsworthiness filter on Groq/Llama → spend Gemini quota only on segments that pass
- Per segment: 2–3 clip suggestions (ffmpeg actually cuts the files) + 300–400 word draft article + 3 headline variants
- Everything lands in a **review queue** UI: approve/reject. Nothing publishes itself.

**ADR-005:** which enrichment outputs shipped first, and why (cite the actual user feedback).

## Stage 5 — Observability

Prometheus metrics from API + workers: `videos_processed_total`, `queue_depth`, `processing_duration_seconds`, `search_latency_seconds`, `api_errors_total`, `provider_quota_remaining`. Grafana dashboard. Alert rule on queue_depth growth (processing falling behind ingestion).

## Stage 6 — Kubernetes + GitOps

Now genuinely justified: API, worker, Redis, Postgres, Qdrant, frontend = six services. Dockerize → Helm chart (`deploy.yaml` convention, CPU requests on all containers so HPA works) → ArgoCD → `yash-dev`/`yash-prod` on Minikube (raise `.wslconfig` to ~5GB for deploy/demo sessions). Stretch: mirror to GCP (GKE Autopilot / small VM) to connect with company stack.

**Interview narrative (keep ChatGPT's framing — it's strong):** "I didn't start with Kubernetes. I started with a synchronous monolith, and every architectural addition — async jobs, the queue, the orchestrator — was a response to a real problem I hit and documented in an ADR. By the time K8s arrived, I had six services that needed it."

## Architecture Decision Records

Every major choice gets `docs/adr/NNN-title.md`: Context · Decision · Alternatives considered · Consequences · Date. ADRs 001–005 seeded above; add as you go. This replaces the earlier `decisions.md` idea — same purpose, industry-standard format.

## Trade-offs (named, not hidden)

- Fast delivery vs completeness → thin slice first, committed stages after
- Managed APIs vs local models → APIs win on this hardware; provider-swap interface (`transcribe(audio) -> segments`) prevents lock-in
- Operational simplicity vs scalability → each complexity step is pulled in by a real problem, never pushed in speculatively
- Generic demo vs differentiated demo → noisy field audio + Hinglish are harder and worth it; they're what make this an *Indian media* project

## Scale assumptions

Now: 10 users, 100 videos, single worker. Future shape if validated: 1,000+ users, millions of transcript chunks, horizontal workers behind the queue — architecture already points that way without building it prematurely.

## What stays out until validated

Saved searches, notifications, regional languages beyond Hindi, live/real-time processing, any internal footage (permissions + free-tier data-training risk — public YouTube only).
