# ClipKnot

An AI pipeline that turns broadcast/YouTube video into a **searchable transcript** — type a phrase in Hindi, English, or Hinglish and jump to the exact moment it was spoken. Built for Indian newsrooms, where hours of TV footage are effectively unsearchable.

Stage 1 is complete and validated end-to-end on a real 36-minute Hindi debate: an English query (e.g. *"saffron terrorism"*) retrieves the matching Hindi segment and seeks the video to that timestamp.

---

## Architecture (Stage 1)

```
YouTube URL
  → ingest      audio-only download → 16kHz mono FLAC
  → split       transport chunks < 25MB (re-encoded, correct headers)
  → transcribe  Groq Whisper Large v3 (per chunk, FLAC→WAV fallback)
  → merge       offset-correct chunk timestamps → absolute timeline
  → chunker     semantic windows (~30–60s, overlapping)
  → index       BGE-M3 embeddings → Qdrant (local)
  → search      FastAPI /search → Next.js UI → video seek
```

Frontend and backend are separated and communicate only over HTTP, so they can be deployed independently later.

---

## Tech stack

- **Pipeline:** Python, yt-dlp, ffmpeg, Groq Whisper API
- **Embeddings:** BGE-M3 (multilingual, via sentence-transformers), 1024-dim
- **Vector store:** Qdrant (local on-disk)
- **Backend:** FastAPI
- **Frontend:** Next.js (TypeScript, Tailwind, App Router)

---

## Running Stage 1 locally

### Prerequisites
- Python 3.13 + the project virtualenv (`.venv`)
- Node.js (for the frontend)
- ffmpeg on PATH
- A Groq API key in `.env` at the project root: `GROQ_API_KEY=...`

### 1. Backend (search API)

From the project root, in its own terminal:

```bash
# install backend deps (first time only)
.venv/Scripts/pip.exe install -r backend/requirements.txt

# start the API — NOTE: first startup takes ~100s while the BGE-M3 model loads
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
```

Wait for the `Ready.` log line. Do **not** use `--reload` (it re-loads the ~100s model on every change). Check readiness:

```bash
curl http://localhost:8000/health        # {"status":"ok"} when loaded
```

Interactive API docs are at `http://localhost:8000/docs`.

### 2. Frontend (search UI)

In a separate terminal:

```bash
cd frontend
# create .env.local once, pointing at the backend:
#   NEXT_PUBLIC_API_URL=http://localhost:8000
npm install        # first time only
npm run dev
```

Open `http://localhost:3000`. The UI shows a "warming up" state until the backend's `/health` returns ok, then you can search.

### Running the pipeline on a new video

(Indexing a video into the search store — runs the pipeline scripts in order. See `docs/` for the full Stage 1 spec.)

```bash
.venv/Scripts/python.exe pipeline/ingest.py <youtube_url>
.venv/Scripts/python.exe pipeline/split.py
.venv/Scripts/python.exe pipeline/transcribe.py
.venv/Scripts/python.exe pipeline/merge.py
.venv/Scripts/python.exe pipeline/chunker.py
.venv/Scripts/python.exe pipeline/index.py
```

> Note: Groq free tier has a ~7,200 audio-seconds/hour cap — don't batch many long videos back-to-back.

---

## Stage 2 — what's next

Stage 1 proved the pipeline works, and surfaced its real ceiling: **Hindi ASR quality**. Generic Whisper garbles Hindi consonants on noisy debate audio, which caps search relevance. Stage 2 targets exactly that, plus production-readiness:

- **Better Hindi/Hinglish ASR** — route Indian-language content through Sarvam AI (built for 22 Indic languages + code-mixing) instead of generic Whisper.
- **Audio quality handling** — VAD to strip music/silence, and a confidence gate that flags low-quality segments and selectively re-processes them.
- **Async ingestion** — move from the current synchronous pipeline to a background job model (jobs table → Redis queue), so ingesting a video doesn't block.
- **Re-index** under a cleaner collection name with the improved transcripts.
- **Deployment** — separate frontend/backend deploy (Fly.io backend, managed Postgres for the jobs table).

Architecture and design decisions are recorded as ADRs in `docs/adr/`, with the reasoning and debugging lessons in `docs/learnings.md`.

---

## Project structure

```
ClipKnot/
├── pipeline/     Stage 1 scripts (ingest → index)
├── backend/      FastAPI search API
├── frontend/     Next.js search UI
├── shared/       config shared by pipeline + backend (model, collection names)
├── docs/         spec, roadmap, ADRs, learnings
└── data/         (gitignored) audio, transcripts, vector store
```