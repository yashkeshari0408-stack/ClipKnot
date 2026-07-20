
# ClipKnot — Stage 2 Spec (v2)

> Supersedes stage2_spec.md v1. Reordered again — v1 was itself evidence-based but its premise (ASR noise caps relevance) was tested directly and falsified. This version reflects what was actually found, not what was assumed going in.

## What changed and why

v1 assumed: relevance ceiling (0.42–0.54) = garbled Hindi ASR → fix = route to Sarvam.

Tested directly (two controlled experiments, real production pipeline output):
- Clean Sarvam transcripts vs garbled Groq transcripts: **no meaningful retrieval difference** (~0.009 mean, noise-level at n=3).
- Tight windows (~4 sentences) vs wide windows (45s), same transcripts: **+0.017 mean lift, identical for both engines**.

**Conclusion: the ceiling is a windowing/semantic-dilution problem, not an ASR-engine problem.** Confirmed by two independent tests (an early sliding-window spike, and this controlled tight-vs-wide comparison) landing on the same explanation weeks apart.

## Priority order (v2, evidence-based)

### 1. Tighten chunker window size — NEW priority #1
Reduce `chunker.py`'s target window from ~30-45s toward the tight-window shape that scored best (~4 sentences / ~15-20s, small overlap). Engine-agnostic — helps whichever ASR is used. Cheap: parameter change + re-index, no new integration.
- Re-run the existing 3-query eval after tightening to confirm the lift holds at production scale.
- Watch for the tradeoff this reintroduces: tighter windows = more windows = more Qdrant points + slightly higher embedding cost. Acceptable given BGE-M3's measured local performance (ADR-012).

### 2. Confidence gate — still worth building, reframed
No longer "the fix for the noise ceiling" (there wasn't one on this video). Still legitimate as: (a) genuine defense against rare bad segments, (b) required infrastructure since Groq segments carry real avg_logprob/no_speech_prob and Sarvam segments don't (confidence_source: sarvam_none) — the gate must branch on this regardless of which engine's used.

### 3. Sarvam — RESCOPED from Stage 2 retrieval fix to Stage 4 editorial-input-quality decision
Not adopted for retrieval (no measured benefit). Kept for **transcript readability**: properly punctuated (317 sentences vs Groq's 2 unpunctuated blobs on the same 36-min video), correctly spelled Hindi. This matters for Stage 4's editorial agent (clip captions, draft articles — ADR-005), which needs clean sentence boundaries and readable text, not for search ranking.
- Revisit when Stage 4 is scoped. Router (`transcribe.py`), `transcribe_sarvam.py`, and the language-tag ingest flag are already built and validated — this is a real, working option to activate later, not a discarded experiment.
- `clipsutra_chunks` collection stays as-is; no re-index to Sarvam-sourced content on current evidence.

### 4. Async ingest (jobs table)
Unchanged from v1 — justified by real blocking pain (ADR-011), not a quality fix. Search stays synchronous (ADR-014).

### 5. Audio enhancement — still last, still likely unnecessary
Unchanged reasoning from v1: confidence-gate telemetry already showed clean audio (9/299 segments flagged). Now doubly de-prioritized — if ASR engine barely moves relevance, audio enhancement (a lever aimed at ASR input quality) is even less likely to be the answer. Build only if a future video's gate output specifically implicates noise.

### 6
"Free-tier budget is tight (~100 credits, ~70 consumed in this investigation) — factor into Stage 4 scoping, don't treat Sarvam as freely re-testable like Groq." That's the kind of constraint that should shape how Stage 4 gets planned, not get rediscovered the hard way mid-build.

## What this means for evidence discipline going in
n=1 video, n=3 queries. The windowing finding is corroborated twice (independently, weeks apart) so it's trustworthy directionally. Before fully committing engineering time past a parameter tune, a cheap sanity step: re-run the same tight-vs-wide comparison on one more video (ideally a second Hindi debate) to confirm the +0.017 lift generalizes before treating it as settled.

## Relevant ADRs
001 (ASR choice — Sarvam scope narrowed) · 002 (jobs table) · 003 (enhancement, deprioritized) · 004 (Redis) · 005 (editorial agent — Sarvam's new home) · 008 (diarization) · 009 (chunking) · 010 (trust ASR / gate — evidence update: ASR was NOT the primary cap) · 011 (sync→async) · 012 (BGE-M3) · 013 (ASR resilience) · 014 (frontend/backend separation)

## Done means
Chunker retuned + re-validated on the 3-query eval → gate built with engine-branching for missing Sarvam confidence → async ingest working → Sarvam formally parked as a Stage 4 input, with router/integration preserved and documented → enhancement stack untouched unless evidence demands it.