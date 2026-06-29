"""
Single source of truth for values that MUST match between indexing and search.

Both pipeline/index.py and backend/ import from here so they can never drift.
If index.py embeds with one model and the API queries with another, cosine
similarity is meaningless with no error raised — so these live in exactly one place.

Lives in shared/ (not backend/) so the dependency direction is sane:
pipeline depends on shared, backend depends on shared, neither depends on the other.
"""

import os

# --- Embedding model -------------------------------------------------------
# MUST be byte-identical to what pipeline/index.py loads. Query and documents
# must be embedded by the same model or retrieval is garbage.
MODEL_NAME = "BAAI/bge-m3"

# --- Qdrant ----------------------------------------------------------------
# Collection deliberately kept as clipsutra_chunks until the Stage 2 re-index
# (see learnings.md). Renaming now would orphan the existing 73 vectors.
COLLECTION_NAME = "clipsutra_chunks"
VECTOR_SIZE = 1024  # bge-m3 dimension

# Local on-disk Qdrant path. Resolve relative to project root so it works
# regardless of where the process is launched from.
# shared/config.py -> project root is one level up from this file's dir.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)
QDRANT_PATH = os.path.join(PROJECT_ROOT, "data", "qdrant_storage")

# --- Search defaults -------------------------------------------------------
DEFAULT_TOP_K = 5