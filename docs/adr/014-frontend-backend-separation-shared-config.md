# ADR-014: Frontend/backend separation over HTTP, with shared config as single source of truth

**Status:** Accepted (Stage 1)
**Date:** 2026-06-29
**Deciders:** Yash (with Claude input)

## Context
Stage 1's UI needs a search interface. Two structural questions: how do frontend and backend relate inside the monorepo, and how do we stop the API and the indexing pipeline from silently disagreeing about the embedding model?

The drift risk is real and silent: if `index.py` embeds with one model and the search API queries with another, cosine similarity is meaningless — **no error is raised**, results are just quietly wrong.

## Decision
1. **Monorepo, but cleanly separated deployables.** `backend/` (FastAPI) and `frontend/` (Next.js) live in one git repo but communicate **only over HTTP**. The frontend never imports backend code. This keeps them independently deployable (planned: Fly.io backend, separate frontend host).
2. **Configurable API URL** — the frontend reads `NEXT_PUBLIC_API_URL` from env, never a hardcoded `localhost:8000`. Local dev points at localhost; production points at the deployed URL. (Deployment becomes an env change, not a code hunt.)
3. **`shared/config.py` as single source of truth** for values that MUST match across the HTTP boundary: `MODEL_NAME`, `COLLECTION_NAME`, `VECTOR_SIZE`, `QDRANT_PATH`. Both `pipeline/` and `backend/` import from it. It lives in `shared/` — **not** inside `backend/` — so the dependency direction is sane: pipeline→shared, backend→shared, neither depends on the other.
4. **Search is synchronous.** The only slow thing in the search path is the one-time ~100s model load at *startup*, not per-query. Search itself is ~1s. A `/health` endpoint reports `loading` until the model is resident, so the UI shows a "warming up" state instead of failing searches. **No background jobs for search** — that machinery belongs to `/ingest` in Stage 2 (ADR-002).

## Alternatives Considered
- **Serve the frontend from FastAPI** — rejected: couples deploy lifecycles; kills independent scaling/hosting.
- **Hardcoded API URL** — rejected: the exact bug seen in a prior project (hardcoded `localhost` in `.env.production`), discovered only at deploy time.
- **Duplicate the model/collection constants in both places** — rejected: guarantees eventual silent drift.
- **Async/job-queue for search** — rejected: solves a problem search doesn't have; imports Stage 2 scope into Stage 1.

## Consequences
- CORS must allow the frontend origin (currently `http://localhost:3000`; tighten to the real origin before deploy).
- The frontend's TypeScript `SearchHit` type mirrors the backend's pydantic schema — a second (compile-time) guard against contract drift.
- Model loads once in FastAPI's `lifespan`, stashed on `app.state`; handlers read it from there. Loading per-request would make every search take ~100s.
- Qdrant local-mode (`QdrantClient(path=...)`) takes an **exclusive lock** — the API and `index.py` cannot hold the store simultaneously. Fine for now; a Stage 2 reason to move to Qdrant server mode.

## Notes
`qdrant-client` **removed** `client.search()` in v1.18.0 — the current API is `client.query_points(query=..., ...)` with results under `.points`. Library APIs change between versions; verify against the installed version rather than assuming.
