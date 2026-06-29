"""
ClipKnot — Search API (Stage 1)

Synchronous search endpoint. The ONLY slow thing here is the one-time model
load at startup (~100s for bge-m3); that happens before any request is served,
so per-query latency is just embed + Qdrant lookup (~1s). No async/job-queue
needed for search — that's a Stage 2 concern for /ingest, not /search.

Run:  uvicorn backend.main:app --reload --port 8000
Note: startup takes ~100s while the model loads. Hit GET /health to know when
      it's ready (returns {"status": "loading"} until the model is in memory).
"""

import sys
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# Make shared/ importable regardless of launch dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.API")


# --- Response schema -------------------------------------------------------
class SearchHit(BaseModel):
    score: float            # cosine similarity — kept for debugging; frontend may hide it
    start_s: float          # drives the video seek — keep float precision, do NOT round/int
    end_s: float
    text: str               # preview snippet
    title: str | None = None
    source_url: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


# --- Lifespan: load model + connect Qdrant ONCE ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    logger.info(f"Loading embedding model '{config.MODEL_NAME}' (this takes ~100s on first cold load)...")
    app.state.model = SentenceTransformer(config.MODEL_NAME)
    logger.info("Model loaded. Connecting to Qdrant local store...")
    app.state.qdrant = QdrantClient(path=config.QDRANT_PATH)
    app.state.ready = True
    logger.info(f"Ready. Collection='{config.COLLECTION_NAME}', path='{config.QDRANT_PATH}'")
    yield
    # shutdown
    logger.info("Shutting down — closing Qdrant client.")
    app.state.qdrant.close()


app = FastAPI(title="ClipKnot Search API", lifespan=lifespan)

# CORS: allow the frontend origin to call this API from the browser.
# Tighten allow_origins to your real frontend URL before deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev default; add prod URL later
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Readiness probe. Startup takes ~100s; poll this until status == 'ok'."""
    ready = getattr(app.state, "ready", False)
    return {"status": "ok" if ready else "loading"}


@app.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="search query (Hindi/English/Hinglish)"),
    top_k: int = Query(config.DEFAULT_TOP_K, ge=1, le=50),
):
    if not getattr(app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Model still loading, try again shortly.")

    model = app.state.model
    client = app.state.qdrant

    # ── CRITICAL: encode the query EXACTLY as index.py encoded the documents. ──
    # VERIFY against your index.py encode line. If index.py passed
    # normalize_embeddings=True, add it here too. Any mismatch silently
    # corrupts cosine scores. Mirror it precisely.
    # VERIFIED against pipeline/index.py:88 — documents were encoded with
    # `model.encode(window_texts, show_progress_bar=False)` (no normalize_embeddings).
    # show_progress_bar doesn't affect the vector, so a bare encode is identical here.
    query_vector = model.encode(q).tolist()   # matches index.py encode exactly

    # qdrant-client 1.18 removed .search(); use query_points (query= not query_vector=).
    response = client.query_points(
        collection_name=config.COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )

    hits = []
    for r in response.points:
        p = r.payload or {}
        hits.append(SearchHit(
            score=r.score,
            start_s=p.get("start_s"),
            end_s=p.get("end_s"),
            text=p.get("text", ""),
            title=p.get("title"),
            source_url=p.get("source_url"),
        ))

    return SearchResponse(query=q, hits=hits)