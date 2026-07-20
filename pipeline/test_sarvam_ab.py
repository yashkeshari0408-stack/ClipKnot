import os
import glob
import json
import logging
from dotenv import load_dotenv
from sarvamai import SarvamAI
from pydub import AudioSegment
import io

# Path alignments
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ClipKnot.SarvamAB")

load_dotenv()
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

if not SARVAM_API_KEY:
    raise ValueError("CRITICAL: SARVAM_API_KEY is missing from the root .env file.")

def run_ab_transcription():
    search_pattern = os.path.join(PROJECT_ROOT, "data", "chunks", "**", "*.flac")
    audio_files = sorted(glob.glob(search_pattern, recursive=True))
    
    # Exclude any previous output matrices if they were matched
    audio_files = [f for f in audio_files if not f.endswith("sarvam_ab_raw.json")]
    
    if not audio_files:
        logger.error("No valid .flac partitions could be located on the drive.")
        return

    logger.info(f"Target locked. Found {len(audio_files)} files to process via 30s slicing.")
    client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
    sarvam_results = []

    # 30 seconds = 30,000 milliseconds for pydub slicing
    SLICE_DURATION_MS = 30000 

    for index, file_path in enumerate(audio_files):
        filename = os.path.basename(file_path)
        logger.info(f"[{index + 1}/{len(audio_files)}] Slicing and transcribing: {filename}")
        
        try:
            # Load the full audio file natively
            audio = AudioSegment.from_file(file_path)
            duration_ms = len(audio)
            
            full_chunk_transcript = []
            
            # Slide a window across the audio file in 30-second steps
            for start_ms in range(0, duration_ms, SLICE_DURATION_MS):
                end_ms = min(start_ms + SLICE_DURATION_MS, duration_ms)
                audio_slice = audio[start_ms:end_ms]
                
                # Export the slice to an in-memory buffer to bypass disk writes
                slice_buffer = io.BytesIO()
                audio_slice.export(slice_buffer, format="flac")
                slice_buffer.seek(0)
                
                # Provide a name attribute so the SDK registers it as a valid file object
                slice_buffer.name = f"slice_{start_ms}.flac"
                
                logger.info(f"  -> Shipping slice {start_ms//1000}s to {end_ms//1000}s...")
                
                response = client.speech_to_text.transcribe(
                    file=slice_buffer,
                    model="saaras:v3",
                    mode="codemix"
                )
                
                if response.transcript:
                    full_chunk_transcript.append(response.transcript.strip())
            
            # Join all sub-transcripts with a space
            unified_text = " ".join(full_chunk_transcript)
            logger.info(f"✓ Success: Compiled unified transcript for {filename}")
            
            sarvam_results.append({
                "chunk_file": filename,
                "transcript": unified_text
            })
            
        except Exception as e:
            logger.error(f"❌ Failed processing sequence for {filename}: {str(e)}")

    output_path = os.path.join(PROJECT_ROOT, "data", "chunks", "sarvam_ab_raw.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"chunks": sarvam_results}, f, indent=2, ensure_ascii=False)
        
    logger.info(f"✨ A/B matrix transcription complete! File written to: {output_path}")

if __name__ == "__main__":
    run_ab_transcription()