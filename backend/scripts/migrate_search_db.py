"""One-shot migration from SEARCH/backend/data/app.db to data/backend/search.db.

# ONE-SHOT SCRIPT — DO NOT RUN AFTER PRODUCTION
#
# Run exactly once during the SEARCH→RAG integration cutover, then never
# again. After search.db is in place and prod is live, the RAG backend
# is the authoritative writer; running this script again would clobber
# any data added since.

What it does, in order:
    1. WAL-safe full copy of the source DB (sqlite3 .backup API
       auto-checkpoints, so the -wal file's uncommitted writes are
       preserved — a plain cp would lose them).
    2. PRAGMA foreign_keys=OFF (defensive — current SEARCH schema has no
       FKs, but DDL below renames tables and we don't want a future FK
       to silently break the run).
    3. DROP TABLE users — SEARCH's users are obsolete; RAG's users
       (in app.db) are authoritative. SEARCH refs users only by UUID
       string from this point on.
    4. Look up RAG UUIDs by email from RAG_DB. Translate the
       USERNAME_TO_EMAIL map below into USERNAME_TO_UUID at runtime so
       no UUID is ever hand-copied (format errors silently break the
       ownership check forever).
    5. Sanity-check every UUID matches 36-char hyphenated form. Abort
       if any are off — fail loud, not silently produce bad data.
    6. ALTER 3 tables (generation_runs, csc_price_state,
       csc_announcement_meta) so started_by / updated_by become
       NULLABLE. SQLite has no `ALTER COLUMN`; we recreate via
       rename + create + copy.
    7. UPDATE each table: replace known usernames with UUIDs, leave
       unmapped values as NULL (the row survives, the actor is "unknown
       legacy user").
    8. PRAGMA foreign_keys=ON.
    9. Print an audit summary.

Usage:
    uv run python scripts/migrate_search_db.py \
        --source "C:/Users/226376/Desktop/SEARCH/backend/data/app.db" \
        --rag-db ./app.db \
        --target ./search.db

    Add --force to overwrite an existing target.
    Add --dry-run to print the plan without writing.

BEFORE RUNNING:
    Edit USERNAME_TO_EMAIL below. Unmapped usernames become NULL in the
    new search.db (acceptable for synthetic users like 'seed_csc';
    review per-deployment for real ones).
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# EDIT BEFORE RUNNING — one row per SEARCH username that should be
# preserved as a real RAG user. Keys: SEARCH username (as it appears
# in users.username / generation_runs.started_by / csc_*.updated_by).
# Values: RAG users.email. UUID is resolved at runtime.
#
# Synthetic usernames (seeders, scripts) should NOT be listed here —
# they'll fall through to NULL, which is the right outcome.
# ──────────────────────────────────────────────────────────────────────
USERNAME_TO_EMAIL: dict[str, str] = {
    "admin": "pijh102511@gmail.com",
}

# ──────────────────────────────────────────────────────────────────────

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Tables touched by user-field rewriting. Each entry: (table_name,
# user_column, full ordered column list, full CREATE TABLE for the
# nullable-fied version). Columns and types must match SEARCH's existing
# schema exactly except for the nullability change on the user column.
TABLES_TO_NULLABILIZE: list[tuple[str, str, list[str], str]] = [
    (
        "generation_runs",
        "started_by",
        ["id", "meeting_date", "started_by", "started_at", "finished_at",
         "status", "output_path", "notes", "result_json"],
        """
        CREATE TABLE generation_runs_new (
            id INTEGER NOT NULL PRIMARY KEY,
            meeting_date DATE NOT NULL,
            started_by VARCHAR(64),
            started_at DATETIME NOT NULL,
            finished_at DATETIME,
            status VARCHAR(16) NOT NULL,
            output_path VARCHAR,
            notes VARCHAR NOT NULL,
            result_json TEXT NOT NULL DEFAULT ''
        )
        """,
    ),
    (
        "csc_price_state",
        "updated_by",
        ["id", "group", "slot_index", "prev_price", "change_amount",
         "updated_at", "updated_by"],
        """
        CREATE TABLE csc_price_state_new (
            id INTEGER NOT NULL PRIMARY KEY,
            "group" VARCHAR(16) NOT NULL,
            slot_index INTEGER NOT NULL,
            prev_price INTEGER NOT NULL,
            change_amount INTEGER NOT NULL,
            updated_at DATETIME NOT NULL,
            updated_by VARCHAR(64)
        )
        """,
    ),
    (
        "csc_announcement_meta",
        "updated_by",
        ["group", "period_label", "announce_date", "updated_at", "updated_by"],
        """
        CREATE TABLE csc_announcement_meta_new (
            "group" VARCHAR(16) NOT NULL PRIMARY KEY,
            period_label VARCHAR(64) NOT NULL,
            announce_date VARCHAR(16) NOT NULL,
            updated_at DATETIME NOT NULL,
            updated_by VARCHAR(64)
        )
        """,
    ),
]


def step(msg: str) -> None:
    print(f"\n>> {msg}")


def _wal_safe_copy(source: Path, target: Path) -> None:
    """sqlite3 .backup() pulls a consistent snapshot including pending WAL
    writes — equivalent to a checkpointed copy. Plain shutil.copy would
    miss anything in app.db-wal that hasn't been checkpointed yet."""
    step(f"WAL-safe copy: {source} -> {target}")
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    print(f"  OK ({target.stat().st_size:,} bytes)")


def _resolve_username_map(rag_db: Path) -> dict[str, str]:
    """Translate USERNAME_TO_EMAIL → USERNAME_TO_UUID by looking up emails
    in the RAG DB. UUIDs come straight from SELECT — never hand-copied."""
    step(f"Resolving username -> UUID from RAG DB: {rag_db}")
    conn = sqlite3.connect(str(rag_db))
    try:
        email_to_uuid = {
            row[1]: row[0]
            for row in conn.execute("SELECT id, email FROM users")
        }
    finally:
        conn.close()

    out: dict[str, str] = {}
    missing: list[tuple[str, str]] = []
    for username, email in USERNAME_TO_EMAIL.items():
        uuid_str = email_to_uuid.get(email)
        if uuid_str is None:
            missing.append((username, email))
            continue
        if not UUID_RE.match(uuid_str):
            print(f"  FATAL: UUID for {email} is not 36-char hyphenated: {uuid_str!r}")
            sys.exit(2)
        out[username] = uuid_str
        print(f"  {username:<20} -> {email:<40} -> {uuid_str}")

    if missing:
        print("\n  WARNING: the following USERNAME_TO_EMAIL entries do NOT match any RAG user:")
        for u, e in missing:
            print(f"    {u} → {e}  (no such email in RAG users)")
        print("  These mappings will be skipped — the corresponding rows become NULL.")
    if not out:
        print("  (no mappings resolved — every started_by/updated_by will become NULL)")
    return out


def _nullabilize_table(
    conn: sqlite3.Connection, table: str, _user_col: str,
    cols: list[str], create_new_sql: str,
) -> None:
    cur = conn.cursor()
    # Quote each column for INSERT/SELECT (handles reserved words like
    # 'group') — sqlite accepts double-quoted identifiers.
    quoted_cols = ", ".join(f'"{c}"' for c in cols)
    cur.executescript(f"""
        {create_new_sql.strip()};
        INSERT INTO {table}_new ({quoted_cols}) SELECT {quoted_cols} FROM {table};
        DROP TABLE {table};
        ALTER TABLE {table}_new RENAME TO {table};
    """)
    cur.close()


def _rewrite_user_column(
    conn: sqlite3.Connection, table: str, user_col: str,
    username_to_uuid: dict[str, str],
) -> tuple[int, int, set[str]]:
    """Returns (rewritten_count, nulled_count, unmapped_usernames_seen)."""
    cur = conn.cursor()
    rewritten = 0
    for username, uuid_str in username_to_uuid.items():
        cur.execute(
            f'UPDATE {table} SET "{user_col}" = ? WHERE "{user_col}" = ?',
            (uuid_str, username),
        )
        rewritten += cur.rowcount

    # Any value NOT in our UUID list AND NOT NULL is either a legacy
    # username we couldn't map or a synthetic actor like 'seed_csc'.
    # Set to NULL so the column is uniformly "real UUID or null".
    if username_to_uuid:
        placeholders = ",".join("?" * len(username_to_uuid))
        unmapped_rows = cur.execute(
            f'SELECT DISTINCT "{user_col}" FROM {table} '
            f'WHERE "{user_col}" IS NOT NULL AND "{user_col}" NOT IN ({placeholders})',
            tuple(username_to_uuid.values()),
        ).fetchall()
    else:
        unmapped_rows = cur.execute(
            f'SELECT DISTINCT "{user_col}" FROM {table} WHERE "{user_col}" IS NOT NULL'
        ).fetchall()

    unmapped_usernames = {r[0] for r in unmapped_rows}

    if username_to_uuid:
        cur.execute(
            f'UPDATE {table} SET "{user_col}" = NULL '
            f'WHERE "{user_col}" IS NOT NULL AND "{user_col}" NOT IN ({placeholders})',
            tuple(username_to_uuid.values()),
        )
    else:
        cur.execute(
            f'UPDATE {table} SET "{user_col}" = NULL WHERE "{user_col}" IS NOT NULL'
        )
    nulled = cur.rowcount
    cur.close()
    return rewritten, nulled, unmapped_usernames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", required=True,
                        help="Path to SEARCH/backend/data/app.db (source)")
    parser.add_argument("--rag-db", default="./app.db",
                        help="Path to RAG app.db (for username→UUID lookup)")
    parser.add_argument("--target", default="./search.db",
                        help="Path to write the new search.db")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite target if it exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan; do not write anything")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    rag_db = Path(args.rag_db).resolve()
    target = Path(args.target).resolve()

    if not source.exists():
        sys.exit(f"ERROR: --source does not exist: {source}")
    if not rag_db.exists():
        sys.exit(f"ERROR: --rag-db does not exist: {rag_db}")
    if target.exists() and not args.force:
        sys.exit(f"ERROR: --target exists ({target}); rerun with --force to overwrite")

    if args.dry_run:
        print("DRY RUN — no files will be modified")
        print(f"  source: {source}")
        print(f"  rag-db: {rag_db}")
        print(f"  target: {target}")
        print(f"  mapping: {USERNAME_TO_EMAIL or '(empty — every actor will become NULL)'}")
        return

    if target.exists():
        target.unlink()

    _wal_safe_copy(source, target)
    username_to_uuid = _resolve_username_map(rag_db)

    step("Opening target for DDL/UPDATE")
    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA foreign_keys=OFF")

        step("Dropping users table (RAG is the authority now)")
        conn.execute("DROP TABLE IF EXISTS users")

        step("ALTER 3 tables -- started_by / updated_by -> NULLABLE")
        for table, user_col, cols, create_sql in TABLES_TO_NULLABILIZE:
            print(f"  - {table} ({user_col})")
            _nullabilize_table(conn, table, user_col, cols, create_sql)

        step("Rewriting user columns (mapped -> UUID, unmapped -> NULL)")
        report: list[tuple[str, int, int, set[str]]] = []
        for table, user_col, _, _ in TABLES_TO_NULLABILIZE:
            rewritten, nulled, unmapped = _rewrite_user_column(
                conn, table, user_col, username_to_uuid,
            )
            report.append((f"{table}.{user_col}", rewritten, nulled, unmapped))
            print(f"  {table}.{user_col}: rewrote {rewritten}, nulled {nulled}")
            if unmapped:
                print(f"    (unmapped values seen: {sorted(unmapped)})")

        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
    finally:
        conn.close()

    step("Audit summary")
    print(f"  target: {target}")
    print(f"  size:   {target.stat().st_size:,} bytes")
    for label, rewritten, nulled, unmapped in report:
        print(f"  {label:<35} rewrote={rewritten:<4} nulled={nulled:<4} "
              f"unmapped={sorted(unmapped) if unmapped else '(none)'}")

    # Final schema verification — make sure users is gone and the three
    # user columns are nullable. Fail loud if not.
    conn = sqlite3.connect(str(target))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "users" in tables:
            sys.exit("FATAL: users table still present after migration")
        for table, user_col, _, _ in TABLES_TO_NULLABILIZE:
            info = conn.execute(f"PRAGMA table_info({table})").fetchall()
            row = next((r for r in info if r[1] == user_col), None)
            if row is None:
                sys.exit(f"FATAL: {table}.{user_col} not found")
            if row[3] != 0:   # PRAGMA table_info col 3 == notnull flag
                sys.exit(f"FATAL: {table}.{user_col} is still NOT NULL")
    finally:
        conn.close()
    print("\n[OK] Migration complete. search.db ready for use.")


if __name__ == "__main__":
    main()
