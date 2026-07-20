import os
import json
import logging
from dotenv import load_dotenv
# Suppress heavy model initialization prints
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import torch
from sentence_transformers import SentenceTransformer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.Evaluate")

load_dotenv()

# Define the exact benchmark search queries you used in Stage 1 testing
BENCHMARK_QUERIES = [
    "भारतीय अर्थव्यवस्था की स्थिति", 
    "Prime Minister speech on infrastructure",
    "चुनाव प्रचार रणनीति और गठबंधन"
]

def run_evaluation():
    sarvam_path = os.path.join(PROJECT_ROOT, "data", "chunks", "sarvam_ab_raw.json")
    if not os.path.exists(sarvam_path):
        logger.error(f"Could not locate Sarvam transcripts at: {sarvam_path}")
        return

    with open(sarvam_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    logger.info("Loading BAAI/bge-m3 tensor weights into memory...")
    # Will use local cache natively if already downloaded in Stage 1
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    
    logger.info("Computing embeddings for target benchmark queries...")
    query_embeddings = model.encode(BENCHMARK_QUERIES, convert_to_tensor=True)
    
    print("\n" + "="*60)
    print("📋 SARVAM AI BGE-M3 SIMILARITY SCORE MATRIX")
    print("="*60)
    
    for chunk in data.get("chunks", []):
        filename = chunk["chunk_file"]
        text = chunk["transcript"]
        
        if not text.strip():
            print(f"\n📂 File: {filename} -> Empty text block captured.")
            continue
            
        # Encode the unified transcript text segment
        doc_embedding = model.encode(text, convert_to_tensor=True)
        
        # Calculate cosine similarities against the queries
        similarities = torch.nn.functional.cosine_similarity(query_embeddings, doc_embedding.unsqueeze(0))
        
        print(f"\n📂 File: {filename}")
        print(f"📝 Length: {len(text)} characters")
        print("-" * 40)
        for q_idx, query in enumerate(BENCHMARK_QUERIES):
            score = similarities[q_idx].item()
            print(f"🔍 Query: '{query}'")
            print(f"   📈 Similarity Score: {score:.4f}")
            
    print("="*60 + "\n")

if __name__ == "__main__":
    run_evaluation()