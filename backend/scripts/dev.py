"""Worktree dev launcher — runs uvicorn on port 8002.

Why this exists:
    Prod backend is on :8000 (managed by PM2 via ecosystem.config.js).
    Plain `uv run uvicorn app.main:app` defaults to :8000 and would
    collide with prod when worktree dev tries to start. This script
    enforces :8002 + 127.0.0.1 so dev never touches a port prod uses.

    app_dir is set explicitly so reload's child process can still import
    `app.main` (the spawned subprocess does not inherit cwd-based sys.path).

Use:
    uv run python scripts/dev.py
"""
from __future__ import annotations

from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8002,
        reload=True,
        reload_dirs=[str(BACKEND_DIR / "app")],
        app_dir=str(BACKEND_DIR),
        log_level="info",
    )
