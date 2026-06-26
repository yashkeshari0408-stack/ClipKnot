import os
import json
import time
import uuid
import logging
import glob
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

# Strict monorepo path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
QDRANT_PATH = os.path.join(PROJECT_ROOT, "data", "qdrant_storage")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Index")

COLLECTION_NAME = "clipsutra_chunks"
# BGE-M3 via sentence-transformers, NOT FastEmbed's models.Document auto-embed path:
# FastEmbed 0.8.0 doesn't package bge-m3 ("not found among supported models"). We
# benchmarked m3 through sentence-transformers and proved it loads (~103s) and encodes
# (~2s/chunk) locally, so we embed here and hand Qdrant raw 1024-dim float vectors.
MODEL_NAME = "BAAI/bge-m3"


def index_semantic_windows():
    """
    [Phase A - Step 9 Embed and Index]
    Embeds semantic windows with BGE-M3 (sentence-transformers) and upserts them
    into local Qdrant. Idempotent: deterministic UUID5 point IDs mean re-running the
    same window overwrites its point instead of creating a duplicate.
    """
    logger.info(f"Connecting to Qdrant Local Storage at: {QDRANT_PATH}")
    client = QdrantClient(path=QDRANT_PATH)

    # 1. Enforce explicit collection schema definition.
    # BGE-M3 emits exactly 1024 dimensions; rank with Cosine similarity.
    if not client.collection_exists(COLLECTION_NAME):
        logger.info(f"Creating new collection context: {COLLECTION_NAME}")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE
            ),
        )

    # 2. Scan for generated semantic window JSON structures.
    # Check BEFORE loading the model — the load is ~103s; don't pay it to find nothing.
    semantic_files = glob.glob(os.path.join(CHUNKS_DIR, "*_semantic.json"))
    if not semantic_files:
        logger.warning("No semantic window files discovered inside data/chunks. Run chunker.py first.")
        return

    # Load the embedding model ONCE, outside the per-video loop (~103s; never repeat per video).
    load_start = time.time()
    logger.info(f"Loading embedding model {MODEL_NAME} (one-time, ~100s)...")
    model = SentenceTransformer(MODEL_NAME)
    logger.info(f"Model loaded in {round(time.time() - load_start, 2)}s.")

    for semantic_path in semantic_files:
        video_id = os.path.basename(semantic_path).replace("_semantic.json", "")
        metadata_path = os.path.join(RAW_DIR, f"{video_id}.json")

        if not os.path.exists(metadata_path):
            logger.warning(f"Core tracking metadata absent for video ID: {video_id}. Skipping.")
            continue

        with open(metadata_path, 'r', encoding='utf-8') as meta_f:
            global_meta = json.load(meta_f)

        with open(semantic_path, 'r', encoding='utf-8') as sem_f:
            semantic_data = json.load(sem_f)

        windows = semantic_data["windows"]
        if not windows:
            logger.warning(f"No windows in {video_id}_semantic.json. Skipping.")
            continue

        logger.info(f"Encoding and upserting {len(windows)} windows for video: {video_id}")

        # Batch-encode ALL window texts in a single call (much faster per chunk than
        # one-at-a-time). .tolist() hands Qdrant raw 1024-dim float vectors.
        window_texts = [win["text"] for win in windows]
        embed_start = time.time()
        embeddings = model.encode(window_texts, show_progress_bar=False)
        logger.info(
            f"Embedded {len(window_texts)} windows in {round(time.time() - embed_start, 2)}s "
            f"({round((time.time() - embed_start) / len(window_texts), 3)}s/window)."
        )

        vectors = []
        payloads = []
        ids = []

        for win, embedding in zip(windows, embeddings):
            # Deterministic UUID5: same (video_id, window_index) -> same ID across runs,
            # so a re-run upserts (overwrites) rather than duplicating points.
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{video_id}_{win['window_index']}"))

            payload_contract = {
                "video_id": video_id,
                "start_s": win["start_s"],
                "end_s": win["end_s"],
                "text": win["text"],
                "source_url": global_meta.get("source_url"),
                "title": global_meta.get("title")
            }

            vectors.append(embedding.tolist())
            payloads.append(payload_contract)
            ids.append(point_id)

        # 3. Stream data points up to the local storage engine.
        client.upload_collection(
            collection_name=COLLECTION_NAME,
            vectors=vectors,
            payload=payloads,
            ids=ids
        )

        logger.info(f"Database sync finalized for video session: {video_id}")

    total = client.count(collection_name=COLLECTION_NAME).count
    logger.info(f"Collection '{COLLECTION_NAME}' now holds {total} points.")


if __name__ == "__main__":
    index_semantic_windows()
