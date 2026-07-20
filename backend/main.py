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
import uuid
import logging
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# Make shared/ importable regardless of launch dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import config  # noqa: E402
from shared.db import get_connection, init_db  # noqa: E402

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


class IngestRequest(BaseModel):
    video_url: str
    language: str = "en"   # ASR routing tag; mirrors ingest_and_convert's default


class IngestResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    status: str                     # pending | processing | completed | failed
    error: str | None = None        # populated only on failed
    video_id: str | None = None     # populated once ingest resolves the YouTube id


# --- Lifespan: load model + connect Qdrant ONCE ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    # Ensure the jobs table exists before we serve /ingest. Cheap + idempotent, and
    # it fails fast if DATABASE_URL is wrong rather than on the first enqueue.
    logger.info("Ensuring jobs table exists (init_db)...")
    init_db()
    logger.info(f"Loading embedding model '{config.MODEL_NAME}' (this takes ~100s on first cold load)...")
    app.state.model = SentenceTransformer(config.MODEL_NAME)
    logger.info("Model loaded. Connecting to Qdrant Cloud...")
    app.state.qdrant = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
    app.state.ready = True
    logger.info(f"Ready. Collection='{config.COLLECTION_NAME}', url='{config.QDRANT_URL}'")
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


# --- Async ingest (Stage 2) ------------------------------------------------
# /ingest enqueues; it does NOT run the pipeline inline (ADR-002/015). It inserts a
# pending row and returns the job id immediately; pipeline/worker.py claims and runs
# it out of band. Poll /jobs/{id} for progress. Note: unlike /search these don't need
# the embedding model, but they only become reachable after the ~100s startup load
# completes (single-process lifespan) — decoupling that is a later concern.
@app.post("/ingest", response_model=IngestResponse, status_code=202)
def ingest(req: IngestRequest):
    """Enqueue a video for async transcription+indexing. Returns the job id at once."""
    with closing(get_connection()) as conn:
        with conn:  # transaction: commit on success, rollback on error
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO jobs (video_url, language) VALUES (%s, %s) RETURNING id;",
                    (req.video_url, req.language),
                )
                job_id = cur.fetchone()[0]
    return IngestResponse(job_id=str(job_id))


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    """Report a job's current status/error/video_id. 404 if the id is unknown or malformed."""
    # Validate up front so a non-UUID path param is a clean 404, not a psycopg2
    # "invalid input syntax for type uuid" 500.
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="job not found")

    with closing(get_connection()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, error, video_id FROM jobs WHERE id = %s;",
                (job_id,),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="job not found")

    status, error, video_id = row
    return JobStatusResponse(status=status, error=error, video_id=video_id)