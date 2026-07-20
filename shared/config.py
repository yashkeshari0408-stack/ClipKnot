"""
Single source of truth for values that MUST match between indexing and search.

Both pipeline/index.py and backend/ import from here so they can never drift.
If index.py embeds with one model and the API queries with another, cosine
similarity is meaningless with no error raised — so these live in exactly one place.

Lives in shared/ (not backend/) so the dependency direction is sane:
pipeline depends on shared, backend depends on shared, neither depends on the other.
"""

import os

from dotenv import load_dotenv

# Load .env here so QDRANT_URL / QDRANT_API_KEY are available no matter which entry
# point imports config first (backend, index.py, or the worker).
load_dotenv()

# --- Embedding model -------------------------------------------------------
# MUST be byte-identical to what pipeline/index.py loads. Query and documents
# must be embedded by the same model or retrieval is garbage.
MODEL_NAME = "BAAI/bge-m3"

# --- Qdrant ----------------------------------------------------------------
# Stage 2 re-index: renamed clipsutra_chunks -> clipknot_chunks (ADR-012's deferred
# rename, free at re-index time). Points now come from Groq-sourced 149 tight windows.
# The old clipsutra_chunks collection is intentionally left intact for rollback/compare.
COLLECTION_NAME = "clipknot_chunks"
VECTOR_SIZE = 1024  # bge-m3 dimension

# Qdrant Cloud (server mode) is now the live store — index.py and the backend both
# connect via QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY). Server mode ends
# the embedded single-writer file lock, so the worker (indexing) and the backend
# (serving /search) can hold connections at the same time (ADR-015).
# Credentials come from .env, never hardcoded.
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Embedded on-disk store — RETAINED as a rollback/backup snapshot, no longer the live
# target. Do not delete data/qdrant_storage; it still holds the pre-cloud 149 points.
# shared/config.py -> project root is one level up from this file's dir.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)
QDRANT_PATH = os.path.join(PROJECT_ROOT, "data", "qdrant_storage")

# --- Search defaults -------------------------------------------------------
DEFAULT_TOP_K = 5