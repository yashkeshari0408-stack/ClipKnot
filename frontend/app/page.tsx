"use client";

import { useEffect, useState } from "react";

// ── Types: mirror the backend's SearchHit schema (backend/main.py). ──
// Keeping this in sync with the API is the cross-HTTP "single source of truth".
type SearchHit = {
  score: number;
  start_s: number;
  end_s: number;
  text: string;
  title: string | null;
  source_url: string | null;
};

type SearchResponse = {
  query: string;
  hits: SearchHit[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Format seconds → mm:ss (or h:mm:ss) for display.
function formatTime(s: number): string {
  const total = Math.floor(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

// Extract the YouTube video ID from a watch URL so we can build an embed URL.
function youtubeId(url: string | null): string | null {
  if (!url) return null;
  // handles ...watch?v=ID and youtu.be/ID
  const m = url.match(/(?:v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}

export default function Home() {
  const [apiReady, setApiReady] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [selected, setSelected] = useState<SearchHit | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Behavior 1: poll /health until the backend (and its ~100s model load) is ready. ──
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/health`);
        const data = await res.json();
        if (!cancelled && data.status === "ok") {
          setApiReady(true);
          return; // stop polling once ready
        }
      } catch {
        // backend not up yet — keep polling
      }
      if (!cancelled) setTimeout(poll, 3000);
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Behavior 2: search. ──
  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    setSelected(null);
    try {
      const res = await fetch(
        `${API_URL}/search?q=${encodeURIComponent(query)}&top_k=8`
      );
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data: SearchResponse = await res.json();
      setResults(data.hits);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search error");
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  // ── Behavior 3: clicking a hit selects it → video panel seeks to start_s. ──
  const vid = selected ? youtubeId(selected.source_url) : null;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">ClipKnot</h1>
      <p className="text-sm text-gray-500 mb-6">
        Search broadcast transcripts — Hindi, English, or Hinglish.
      </p>

      {/* Warming-up state while the backend loads */}
      {!apiReady && (
        <div className="mb-4 rounded bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
          Warming up the search engine… (the model takes a moment to load)
        </div>
      )}

      {/* Search box */}
      <div className="flex gap-2 mb-6">
        <input
          className="flex-1 rounded border border-gray-300 px-3 py-2 disabled:bg-gray-100"
          placeholder="e.g. बीजेपी पर प्रतिबंध  /  saffron terrorism"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
          disabled={!apiReady}
        />
        <button
          className="rounded bg-black px-4 py-2 text-white disabled:bg-gray-400"
          onClick={runSearch}
          disabled={!apiReady || searching}
        >
          {searching ? "…" : "Search"}
        </button>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {/* Video panel (appears when a hit is selected) */}
      {selected && vid && (
        <div className="mb-6">
          <iframe
            className="w-full aspect-video rounded"
            src={`https://www.youtube.com/embed/${vid}?start=${Math.floor(
              selected.start_s
            )}&autoplay=1`}
            allow="autoplay; encrypted-media"
            allowFullScreen
          />
          <p className="mt-1 text-xs text-gray-500">
            Jumped to {formatTime(selected.start_s)}
          </p>
        </div>
      )}

      {/* Results */}
      <div className="space-y-2">
        {results.map((hit, i) => (
          <button
            key={i}
            onClick={() => setSelected(hit)}
            className="block w-full rounded border border-gray-200 px-3 py-2 text-left hover:bg-gray-50"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-gray-500">
                {formatTime(hit.start_s)}
              </span>
              <span className="text-xs text-gray-400">
                score {hit.score.toFixed(3)}
              </span>
            </div>
            <p className="mt-1 text-sm">{hit.text}</p>
          </button>
        ))}
      </div>
    </main>
  );
}
