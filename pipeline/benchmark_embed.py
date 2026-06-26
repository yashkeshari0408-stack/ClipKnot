import os
import json
import time
import logging
import gc
import psutil

# Strict monorepo path anchoring
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CHUNKS_DIR = os.path.join(PROJECT_ROOT, "data", "chunks")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Benchmark")

def get_current_ram_gb() -> float:
    """Reads current process Resident Set Size (RSS) memory allocation in GB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 ** 3)

def run_embedding_benchmark(video_id: str):
    semantic_path = os.path.join(CHUNKS_DIR, f"{video_id}_semantic.json")
    
    if not os.path.exists(semantic_path):
        logger.error(f"Missing semantic windows for {video_id}. Run chunker.py first.")
        return

    with open(semantic_path, 'r', encoding='utf-8') as f:
        semantic_data = json.load(f)
    
    text_batch = [win["text"] for win in semantic_data["windows"]]
    total_chunks = len(text_batch)
    
    logger.info(f"--- STARTING BENCHMARK FOR {video_id} ({total_chunks} Chunks) ---")
    
    # Baseline Memory Check
    ram_baseline = get_current_ram_gb()
    
    # -------------------------------------------------------------
    # TIMING BOTTLENECK 1: Model Loading (Cold Boot)
    # -------------------------------------------------------------
    logger.info("Bottleneck 1: Loading BGE-M3 model into memory...")
    start_load = time.time()
    
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3", trust_remote_code=True, device="cpu")
    
    end_load = time.time()
    load_duration = end_load - start_load
    ram_after_load = get_current_ram_gb()
    
    logger.info(f"Model Load Complete. Latency: {load_duration:.2f}s")
    
    # -------------------------------------------------------------
    # TIMING BOTTLENECK 2: Model Inference (Active Workload)
    # -------------------------------------------------------------
    logger.info("Bottleneck 2: Simulating active inference encoding loop...")
    start_embed = time.time()
    
    # Normalize to ensure Cosine metric calculations line up perfectly
    embeddings = model.encode(text_batch, normalize_embeddings=True, show_progress_bar=False)
    
    end_embed = time.time()
    embed_duration = end_embed - start_embed
    ram_peak = get_current_ram_gb()
    
    logger.info(f"Inference Complete. Latency: {embed_duration:.2f}s")
    
    # Calculate Deltas
    net_ram_used_gb = ram_peak - ram_baseline
    
    print("\n" + "="*50)
    print("📋 BENCHMARK MARKDOWN ROW CONSTRUCTOR")
    print("="*50)
    print("| Video ID | Chunks | Model Load Time | Embed Time | Peak Process RAM | Net RAM Delta |")
    print("|---|---|---|---|---|---|")
    print(f"| {video_id} | {total_chunks} | {load_duration:.2f}s | {embed_duration:.2f}s | {ram_peak:.2f} GB | {net_ram_used_gb:.2f} GB |")
    print("="*50 + "\n")
    
    # Aggressive memory cleanup evaluation pass
    del model, embeddings
    gc.collect()
    ram_after_cleanup = get_current_ram_gb()
    logger.info(f"Memory cleared. RAM dropped back to: {ram_after_cleanup:.2f} GB")

if __name__ == "__main__":
    # Target your existing baseline smoke test clip first
    run_embedding_benchmark("dQw4w9WgXcQ")