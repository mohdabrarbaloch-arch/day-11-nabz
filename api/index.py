"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level ASGI callable named ``app``.
This file exists only to expose the FastAPI application from ``app.main`` at
the path Vercel expects.

IMPORTANT — SQLite does not work here. Vercel's filesystem is read-only apart
from ``/tmp``, so the default ``sqlite:///./nabz.db`` will fail at startup with
"unable to open database file". Set ``DATABASE_URL`` to a PostgreSQL instance
(Neon, Supabase, RDS) in the project's environment variables before deploying.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The repository root must be importable so `app.main` resolves inside the
# serverless bundle, where the working directory is not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
