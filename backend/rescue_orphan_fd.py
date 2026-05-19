"""Rescue data from the live backend process before it's restarted.

Why this exists:
  search.db / app.db on disk diverged from what the backend process
  actually has open (orphan-FD hypothesis). The orphan view is only
  reachable via HTTP — once we restart pm2, those bytes are gone.

Usage:
  $env:BEARER_TOKEN = "eyJ..."   # paste from frontend DevTools
  & backend/.venv/Scripts/python.exe backend/rescue_orphan_fd.py

Output:
  backend/rescue_<UTC-stamp>/*.json  — one file per endpoint / run.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
TOKEN = os.environ.get("BEARER_TOKEN", "").strip()
if not TOKEN:
    print("ERROR: set BEARER_TOKEN env var first", file=sys.stderr)
    sys.exit(2)

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
STAMP = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
OUT = Path(__file__).resolve().parent / f"rescue_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)
print(f"[rescue] dumping into {OUT}")


def _save(name: str, obj) -> None:
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str),
                 encoding="utf-8")
    print(f"  wrote {p.name}")


def _try_get(client: httpx.Client, path: str, *, label: str | None = None,
             quiet_404: bool = False) -> dict | list | None:
    label = label or path
    try:
        r = client.get(path, headers=HEADERS, timeout=20.0)
    except Exception as e:  # noqa: BLE001
        print(f"  [{label}] connection error: {e}", file=sys.stderr)
        return None
    if r.status_code == 200:
        return r.json()
    if r.status_code == 404 and quiet_404:
        return None
    print(f"  [{label}] HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
    return None


def main() -> None:
    with httpx.Client(base_url=BASE) as client:
        # ── sanity check ──────────────────────────────────────
        me = _try_get(client, "/api/auth/me", label="auth/me")
        if me is None:
            print("ERROR: token rejected. Get a fresh one from DevTools.",
                  file=sys.stderr)
            sys.exit(3)
        _save("00_me", me)

        # ── SEARCH-side: CSC + generation runs ────────────────
        for grp in ("monthly", "quarterly"):
            snap = _try_get(client, f"/api/search/csc/{grp}",
                            label=f"csc/{grp}")
            if snap is not None:
                _save(f"csc_{grp}", snap)

        # Sweep generation_runs IDs. Range is generous — the orphan FD
        # may have rows the disk doesn't.
        runs_dir = OUT / "generation_runs"
        runs_dir.mkdir(exist_ok=True)
        hits = misses = 0
        for rid in range(1, 80):
            run = _try_get(client, f"/api/search/generation/{rid}",
                           label=f"run/{rid}", quiet_404=True)
            if run is None:
                misses += 1
                continue
            (runs_dir / f"run_{rid:03d}.json").write_text(
                json.dumps(run, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            hits += 1
        print(f"  generation_runs: {hits} saved, {misses} not-found")

        # ── ADMIN-side: users, usage, conversations ───────────
        admin_ok = True
        usage = _try_get(client, "/api/admin/search-usage", label="usage")
        if usage is not None:
            _save("admin_search_usage", usage)
        else:
            admin_ok = False

        users_list = _try_get(client, "/api/admin/users?limit=200",
                              label="admin/users")
        if users_list is not None:
            _save("admin_users", users_list)
        else:
            admin_ok = False

        # If admin works, dump per-user conversations
        if admin_ok and isinstance(users_list, dict):
            users = users_list.get("users") or users_list.get("items") or []
            convs_dir = OUT / "conversations_per_user"
            convs_dir.mkdir(exist_ok=True)
            for u in users:
                uid = u.get("id")
                if not uid:
                    continue
                convs = _try_get(client,
                                 f"/api/admin/users/{uid}/conversations",
                                 label=f"convs/{uid[:8]}",
                                 quiet_404=True)
                if convs is None:
                    continue
                (convs_dir / f"user_{uid}.json").write_text(
                    json.dumps(convs, ensure_ascii=False, indent=2,
                               default=str),
                    encoding="utf-8",
                )
            print(f"  conversations dumped per user → {convs_dir}")

        stats = _try_get(client, "/api/admin/stats", label="stats",
                         quiet_404=True)
        if stats is not None:
            _save("admin_stats", stats)

    print(f"\n[rescue] done. inspect: {OUT}")


if __name__ == "__main__":
    main()
