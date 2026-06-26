# PHASE 1

ingest.py must handle both downloading the stream and converting it to a 16kHz mono FLAC right away so your data contract is immediately fulfilled.


When yt-dlp pulls down your audio streams, it saves them in formats like .m4a or .webm depending on what YouTube provides. Groq Whisper Cloud prefers FLAC or MP3, and downsampling them to 16kHz mono client-side drops the file size dramatically, which protects your 25MB upload limit later.

We need to build a synchronous, idempotent script called pipeline/convert.py.

The Rules for convert.py:
Source Tracking: It must scan data/raw/ for any raw audio files (.m4a, .webm, etc.) that have a corresponding metadata {video_id}.json file.

The Target Output: It should use native ffmpeg to transform that raw file into data/raw/{video_id}.flac.

Strict Constraints: It must apply the highpass=f=80 audio filter to cut low-end room rumble, downsample to 16000Hz, and mix down to a single channel (mono).

Idempotency Gate: If data/raw/{video_id}.flac already exists, it must log a skip message and avoid running a heavy ffmpeg processing loop again.



What should happen:
It reads your videos_urls.csv.

It fetches the stream, hands it off to ffmpeg to sample down to 16kHz mono FLAC with the highpass filter applied, and cleans up the raw scratch file.

You will see data/raw/{video_id}.flac and data/raw/{video_id}.json perfectly generated.
__________________________________________________________________________________________________

The Next Step: pipeline/split.py (The Naive Version)
Following the Construction Sequence (Build Order), we are writing the Dumb, Naive Splitter.

The Strategy
We will not use Silero VAD yet. Instead, we are writing a straightforward size/time chunker.

A standard 10-minute (600 seconds) segment of 16kHz mono FLAC takes up roughly 11.5 MB of space, which leaves a wide, safe margin below Groq's 25MB gateway ceiling.

Our primary engineering objective here is establishing the exact Data Contract Output Shape:

A subdirectory for the video: data/chunks/{video_id}/

The sequentially sliced audio chunk files: chunk_00.flac, chunk_01.flac, etc.

A tracking manifest.json recording the exact number of seconds offset from the video timeline for each file.

Once this contract shape is locked in, we can build the transcription and interval-merge modules. In Phase B, we can drop the VAD system directly into this file without rewriting any downstream modules.
______________

The Next Battle: pipeline/split.py (Transport Chunking)
Now we hit the real algorithmic constraint of the project: Groq’s strict 25MB file size limit for free tier requests.

A 45-minute master FLAC file will comfortably blow past 25MB, meaning your pipeline will instantly fail at the transcription layer if we don't chop it up here.

According to your locked spec, you need to break the master .flac into transport chunks under 25MB, and we want to prefer splitting at silence boundaries so we don't slice a word completely in half right at the split mark.

The Strategy for split.py:
Since we cut out the local machine-learning VAD layer to save your 8GB laptop's RAM, we will use native ffmpeg parameters to locate silence and split the files cleanly.

ffmpeg has a built-in module called segment that can split files based on duration while safely snap-aligning the cuts to the nearest silent frame.

Technical Target Blueprint:
Target Inputs: Scan data/raw/ for {video_id}.flac files.

Chunk Target Output: Save chunks into data/chunks/{video_id}/chunk_XX.flac.

The Manifest Contract: We must write a matching data/chunks/{video_id}/manifest.json file that logs the exact start offset in seconds for each chunk. If we don't track this offset, we will hit the Timestamp Offset Bug later, and your search results will jump to the wrong moments in the video.


____________________________________________________________________________________________________
🚀 Run the Naive Splitter

Step 5: Transcribe.
The Strategy
Your script needs to hit the live Groq Cloud API gateway. Because your project specification explicitly calls out "verbose output, per chunk" and "429 exponential backoff", you cannot just do a basic, blind API call. We have to design for real-world network edge cases:

Verbose Format: We must tell Groq to return verbose_json format. Standard JSON only yields the full block text. 
Verbose JSON exposes the structural segments, token confidence values, and individual words with their relative timestamps (avg_logprob, no_speech_prob, compression_ratio). This is the exact metadata your Step 6 Confidence Gate and Step 7 Merge Algorithm depend on.

429 Rate Limit Mitigation: If you push a 60-minute video through (which generates 6 consecutive chunk requests), or if you run multiple tests back-to-back, Groq will eventually fire back an HTTP 429 Too Many Requests status block. Your code must catch this natively and use an exponential backoff retry loop (e.g., waiting $2^n$ seconds before knocking on the door again).

The Data Contract Output Shape: The script must look at data/chunks/{video_id}/manifest.json, send every listed .flac chunk to Groq, and save the raw API outputs directly into a folder structure: data/transcripts/{video_id}/chunk_XX_response.json.

Look inside your project's workspace structure under data/transcripts/dQw4w9WgXcQ/. You will find chunk_00_response.json sitting there safely.

____________________________________________________________________________________________________________

🛠️ The Next Battle: pipeline/merge.py


Following the Phase A construction sequence, we now implement 
Step 7: Merge.

The Strategy: Your specification flags this as "the interesting algorithm.

"Groq returns timestamps (start and end) relative to each individual audio chunk file.

 For example, if chunk_01.flac captures speech starting 10 seconds into that file, its raw payload says start: 10.0. But on the true video timeline, if chunk_01.flac started at an offset of 600 seconds, that speech actually happened at 610.0 seconds.If you do not shift these segment arrays mathematically, your search results will point to the completely wrong location in the video.

 The Core Rules for merge.py:
 Load Artifacts: Read the master chunk mapping from data/chunks/{video_id}/manifest.json to get the true timeline start offsets (start_offset_sec).
 
 Apply 
 Math Offset: Loop through every segment inside data/transcripts/{video_id}/chunk_XX_response.json and adjust the times:

 start\_s = raw\_start + start\_offset\_sec
 end\_s = raw\_end + start\_offset\_sec
 
 Deduplicate Overlaps: Since your naive splitter doesn't create overlapping chunks right now (each splits exactly at 600s intervals), segments will line up continuously end-to-end.
  We will write a clean interval-merge function that appends them sequentially, keeping the code scalable for when you drop the VAD system in later.
  Fulfill Data Contract: Save the unified output straight to data/transcripts/{video_id}.json following your locked schema contract layout.

___________________________________________________________________________________________________

🛠️ The Next Battle:
 pipeline/chunker.py (Semantic Windowing)
 
 Following Phase A of your construction sequence, we now move to Step 8: Semantic Windowing.
 
 The Technical Objective :Your specification draws a sharp line here:
  Transport chunking != semantic chunking.
  Audio splitting (Step 4) handles the API file-size constraints.

  Semantic windowing (Step 8) creates dense text blocks designed for vector search.
  
  If you pass a tiny 2-second individual Whisper segment to an embedding model, the vector won't have enough textual context to match nuanced user queries.

   Conversely, if you embed a full 10-minute block, the specific timestamps get blurred out, and your search results will jump to the wrong moment in the video.
   
   The Algorithm Rules for chunker.py:

  1. Slide over the Merged Segments:
    Read data/transcripts/{video_id}.json.
  2.  Build Windows (~30–60s):
    Accumulate consecutive text lines into single logical windows until the total block duration spans between 30 and 60 seconds.
   3. Inject Overlaps: To ensure phrases don't get awkwardly severed right at a window border, consecutive windows must overlap by 1 full segment.
   4. Preserve Absolute Timeline Bounds: The final window's tracking payload must capture:

    start_s: The timestamp of the first segment in the group.
    end_s: The timestamp of the last segment in the group.
    text: The clean, combined paragraph string.
    
  5.  Output Contract: Save the resulting array directly to a fresh directory folder path: data/chunks/{video_id}_semantic.json.


  The mathematical sliding chunker executed with absolute precision.

Look at your data payload output—this is a textbook implementation of semantic slicing. Notice how Window 0 ends with "Gotta make you understand", and Window 1 immediately bootstraps its context using that exact overlapping phrase. This completely eliminates the risk of an edge query failing because a sentence was sliced blindly down the middle.

You have 7 highly dense, clean vector-optimized text blocks mapping from 0.0 to 187.2 seconds.

______________________________________________________________________________________________________

🛠️ The Next Battle: pipeline/index.py (Vector Embedding & Storage)

Step 9: Embed & Index.

The Strategy
Your specification locks down two very clear, explicit choices for the vector tier:

The Vector Model: BGE-M3. This model outputs exactly 1024 dimensions and relies on Cosine distance for indexing math.

The Vector Database: Qdrant.

To keep this light and rapid, we will use the official FastEmbed engine created by Qdrant. It runs quantized BGE-M3 inside a highly optimized CPU ONNX container. It takes up less than 150MB of memory and executes vector generations almost instantaneously.

Qdrant allows you to initialize an In-Memory / Local Disk Client directly through your Python script. It saves a simple, lightweight binary storage block inside your workspace (data/qdrant_storage), keeping things entirely self-contained

