import os
import json
import logging
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import torch
from sentence_transformers import SentenceTransformer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.WindowEval")

BENCHMARK_QUERIES = [
    "भारतीय अर्थव्यवस्था की स्थिति", 
    "Prime Minister speech on infrastructure",
    "चुनाव प्रचार रणनीति और गठबंधन"
]

def build_sliding_windows(segments, window_size=4, step=2):
    windows = []
    total = len(segments)
    for i in range(0, total, step):
        end_idx = min(i + window_size, total)
        window_segs = segments[i:end_idx]
        
        if not window_segs:
            break
            
        # Combine the text and keep track of timestamps
        combined_text = " ".join([s.get("text", "").strip() for s in window_segs])
        start_time = window_segs[0].get("start", 0.0)
        end_time = window_segs[-1].get("end", 0.0)
        
        windows.append({
            "text": combined_text,
            "start": start_time,
            "end": end_time
        })
        
        if end_idx == total:
            break
    return windows

def run_window_evaluation():
    base_json = os.path.join(PROJECT_ROOT, "data", "transcripts", "HK0ZkdwrNUM.json")
    
    with open(base_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    segments = data.get("segments", [])
    
    # 1. Chunk the massive transcript into small, highly contextual sliding windows
    windows = build_sliding_windows(segments, window_size=4, step=2)
    logger.info(f"Generated {len(windows)} granular semantic windows from raw timeline.")
    
    # 2. Initialize the BGE-M3 model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    
    query_embeddings = model.encode(BENCHMARK_QUERIES, convert_to_tensor=True)
    doc_texts = [w["text"] for w in windows]
    
    logger.info("Encoding all semantic windows...")
    doc_embeddings = model.encode(doc_texts, convert_to_tensor=True)
    
    print("\n" + "="*60)
    print("🎯 GRANULAR WINDOW SIMILARITY TOP MATCHES")
    print("="*60)
    
    for q_idx, query in enumerate(BENCHMARK_QUERIES):
        # Compute similarities for this specific query across all windows
        similarities = torch.nn.functional.cosine_similarity(query_embeddings[q_idx].unsqueeze(0), doc_embeddings)
        
        # Extract the highest scoring match
        best_idx = torch.argmax(similarities).item()
        best_score = similarities[best_idx].item()
        best_window = windows[best_idx]
        
        print(f"🔍 Query: '{query}'")
        print(f"   📈 Top Score: {best_score:.4f}")
        print(f"   ⏱️ Timeline: {best_window['start']}s - {best_window['end']}s")
        print(f"   📝 Text: \"{best_window['text']}\"\n")
        print("-" * 50)

if __name__ == "__main__":
    run_window_evaluation()