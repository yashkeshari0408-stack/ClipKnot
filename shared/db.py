"""
Postgres (Neon) access for the async ingest pipeline.

Lives in shared/ for the same reason as config.py: both the backend (which enqueues
jobs and reads their status) and pipeline/worker.py (which claims and runs them) need
one connection helper, and neither should depend on the other.

Sync psycopg2 on purpose — the worker is a plain polling loop and the backend's job
inserts/reads are single fast round-trips, so an async driver buys nothing here.
The connection string (incl. Neon's sslmode/channel_binding params) comes from
DATABASE_URL in .env — never hardcoded. channel_binding=require works as-is with
psycopg2-binary's bundled libpq; do not strip it.
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# CREATE TABLE IF NOT EXISTS so init_db() is idempotent (safe to call on every boot).
# gen_random_uuid() is built into Postgres 13+ (no pgcrypto extension needed on Neon 18).
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_url TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    video_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def get_connection():
    """Open a new psycopg2 connection from DATABASE_URL. Caller owns closing it."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in the environment (.env).")
    return psycopg2.connect(url)


def init_db():
    """Create the jobs table if it doesn't exist. Idempotent."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()


if __name__ == "__main__":
    init_db()
    print("jobs table ready.")
