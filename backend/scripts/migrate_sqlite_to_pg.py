"""One-shot SQLite → PostgreSQL data migration.

Run AFTER:
  1. PG kb_app schema is up-to-date (alembic upgrade head against PG)
  2. PG kb_search schema is up-to-date (SearchBase.metadata.create_all)
  3. PM2 stopped (frontend + backend) so SQLite isn't being written to
     mid-migration. Easiest: use enter-maintenance.bat first.

What it does:
  - app.db (SQLite) → kb_app (PG)  — skipping alembic_version
    (already populated by alembic upgrade)
  - search.db (SQLite) → kb_search (PG)
  - Resets PG sequences so next auto-generated id doesn't collide with
    the imported rows.
  - Does NOT touch langgraph.db (fresh start on PG).

Verification: prints per-table row counts. Compare to your SQLite
counts before continuing to Phase 4.

Run:
    cd backend
    .venv/Scripts/python.exe scripts/migrate_sqlite_to_pg.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, text

# ── config ────────────────────────────────────────────────────────────
# Paths are absolute so the script works regardless of cwd.
BACKEND = Path(__file__).resolve().parent.parent
APP_SQLITE   = f"sqlite:///{BACKEND / 'app.db'}"
SEARCH_SQLITE = f"sqlite:///{BACKEND / 'search.db'}"

# PG password is the same one we used in db.md Phase 1 Step 1.3.
# Hardcoded here (not from env) so the script is self-contained for a
# one-shot migration. Don't ship this to public repos.
PG_USER = "kb_user"
PG_PASSWORD = "cade6622"
PG_HOST = "127.0.0.1"
PG_PORT = 5432
APP_PG = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/kb_app"
SEARCH_PG = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/kb_search"

# (sqlite_url, pg_url, tables_to_skip_during_copy)
PAIRS = [
    (APP_SQLITE,    APP_PG,    {"alembic_version"}),
    (SEARCH_SQLITE, SEARCH_PG, set()),
]


# ── helpers ───────────────────────────────────────────────────────────

def copy_tables(src_url: str, dst_url: str, skip: set[str]) -> None:
    src = create_engine(src_url)
    dst = create_engine(dst_url)

    md = MetaData()
    md.reflect(bind=src)
    if not md.tables:
        print(f"  (no tables in source — nothing to copy)")
        return

    with src.connect() as s, dst.begin() as d:
        for tbl in md.sorted_tables:
            if tbl.name in skip:
                print(f"  {tbl.name}: SKIP (already populated by migration)")
                continue
            rows = list(s.execute(tbl.select()).mappings())
            if not rows:
                print(f"  {tbl.name}: 0 rows (empty source)")
                continue
            d.execute(tbl.insert(), [dict(r) for r in rows])
            print(f"  {tbl.name}: copied {len(rows)} rows")


def reset_sequences(pg_url: str) -> None:
    """After bulk insert, set every SERIAL/IDENTITY sequence to MAX(id)+1
    so the next auto-generated id doesn't collide.
    """
    eng = create_engine(pg_url)
    with eng.connect() as conn:
        # Find every column that has a serial sequence in public schema
        rows = conn.execute(text("""
            SELECT
                n.nspname AS schema,
                c.relname AS table,
                a.attname AS column,
                pg_get_serial_sequence(
                    quote_ident(n.nspname) || '.' || quote_ident(c.relname),
                    a.attname
                ) AS seq
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE c.relkind = 'r'
              AND n.nspname = 'public'
              AND a.attnum > 0
              AND pg_get_serial_sequence(
                    quote_ident(n.nspname) || '.' || quote_ident(c.relname),
                    a.attname
                  ) IS NOT NULL
        """)).fetchall()
        for r in rows:
            seq = r.seq
            tbl_fq = f"{r.schema}.{r.table}"
            col = r.column
            # setval third arg "is_called" = true means next nextval() returns
            # current_value+1. COALESCE handles empty tables.
            conn.execute(text(
                f"SELECT setval(:seq, COALESCE((SELECT MAX({col}) FROM {tbl_fq}), 0) + 1, false)"
            ), {"seq": seq})
            print(f"  reset {seq} → MAX({tbl_fq}.{col}) + 1")
        conn.commit()


# ── main ──────────────────────────────────────────────────────────────

def main() -> int:
    for src_url, dst_url, skip in PAIRS:
        print(f"\n=== {src_url}")
        print(f" → {dst_url}")
        try:
            copy_tables(src_url, dst_url, skip)
        except Exception as e:  # noqa: BLE001
            print(f"\n[FATAL] copy failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        print(f"--- sequences ({dst_url.split('/')[-1]}) ---")
        try:
            reset_sequences(dst_url)
        except Exception as e:  # noqa: BLE001
            print(f"\n[FATAL] sequence reset failed: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1

    print("\nDone. Verify row counts against your SQLite source before Phase 4.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
