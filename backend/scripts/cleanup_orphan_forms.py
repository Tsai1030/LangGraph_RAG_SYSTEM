"""
cleanup_orphan_forms.py — 一次性掃描並刪除 orphan 殘留資料

orphan 定義：對應的 conversation_id 已不存在於 app.db.conversations，
但仍有以下殘留：
  - generated_forms/<conv_id>_*.{docx,xlsx,csv}
  - langgraph.db checkpoints / writes 表中以該 conv_id 為 thread_id 的列

執行方式（在 backend/ 目錄）：
  # 預設 dry-run，只列 orphan 不動資料
  python scripts/cleanup_orphan_forms.py

  # 確認無誤後加 --apply 真的刪除
  python scripts/cleanup_orphan_forms.py --apply

設計重點：
  - 預設 dry-run，避免誤刪
  - 兩種側邊資料分開計數，互不阻塞
  - 兩個 .db 用 sync sqlite3（一次性腳本，不需要 async overhead）
  - 路徑穿越防護：只刪 generated_forms 目錄內的檔案
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_DB = BACKEND_DIR / "app.db"
LANGGRAPH_DB = BACKEND_DIR / "langgraph.db"
GENERATED_DIR = BACKEND_DIR / "data" / "generated_forms"


def _conversation_ids(app_db: Path) -> set[str]:
    """讀取 app.db 內所有 conversation id。"""
    with sqlite3.connect(app_db) as conn:
        return {row[0] for row in conn.execute("SELECT id FROM conversations")}


def _orphan_thread_ids(langgraph_db: Path, valid_ids: set[str]) -> list[str]:
    """langgraph checkpoints 中不存在於 valid_ids 的 thread_id。"""
    with sqlite3.connect(langgraph_db) as conn:
        all_threads = {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
    return sorted(all_threads - valid_ids)


_GENERATED_EXTS = ("docx", "xlsx", "csv")


def _orphan_files(gen_dir: Path, valid_ids: set[str]) -> list[Path]:
    """generated_forms 中 prefix 不在 valid_ids 內的產出檔（docx / xlsx / csv）。"""
    if not gen_dir.exists():
        return []
    orphans: list[Path] = []
    for ext in _GENERATED_EXTS:
        for path in gen_dir.glob(f"*.{ext}"):
            conv_part = path.name.split("_", 1)[0]
            if conv_part not in valid_ids:
                orphans.append(path)
    return sorted(orphans)


def _delete_threads(langgraph_db: Path, thread_ids: Iterable[str]) -> int:
    """從 langgraph.db 刪除指定 thread_id 的 checkpoints 與 writes 兩張表。"""
    ids = list(thread_ids)
    if not ids:
        return 0
    with sqlite3.connect(langgraph_db) as conn:
        # 用 IN ? * N 較難移植；分別 DELETE 較直觀
        n = 0
        for tid in ids:
            cur = conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (tid,))
            n += cur.rowcount
            conn.execute("DELETE FROM writes WHERE thread_id = ?", (tid,))
        conn.commit()
        return n


def _delete_files(paths: Iterable[Path]) -> int:
    """刪除指定產出檔（docx / xlsx / csv）；二次驗證仍位於 GENERATED_DIR 之內。"""
    gen_resolved = GENERATED_DIR.resolve()
    n = 0
    for path in paths:
        try:
            resolved = path.resolve()
            if gen_resolved not in resolved.parents:
                print(f"  [skip] outside GENERATED_DIR: {resolved}", file=sys.stderr)
                continue
            path.unlink()
            n += 1
        except OSError as exc:
            print(f"  [warn] cannot delete {path.name}: {exc}", file=sys.stderr)
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="實際執行刪除；省略則只 dry-run（列 orphan 不刪資料）",
    )
    args = parser.parse_args()

    if not APP_DB.exists():
        print(f"app.db not found: {APP_DB}", file=sys.stderr)
        return 1

    valid_ids = _conversation_ids(APP_DB)
    print(f"app.db 現存 conversations: {len(valid_ids)}")

    orphan_threads: list[str] = []
    if LANGGRAPH_DB.exists():
        orphan_threads = _orphan_thread_ids(LANGGRAPH_DB, valid_ids)
    else:
        print(f"langgraph.db not found（跳過）: {LANGGRAPH_DB}")

    orphan_files = _orphan_files(GENERATED_DIR, valid_ids)

    print()
    print(f"orphan langgraph threads: {len(orphan_threads)}")
    if orphan_threads[:5]:
        for tid in orphan_threads[:5]:
            print(f"  - {tid}")
        if len(orphan_threads) > 5:
            print(f"  ...（另 {len(orphan_threads) - 5} 筆）")

    print(f"orphan generated files (docx/xlsx/csv): {len(orphan_files)}")
    for path in orphan_files[:10]:
        print(f"  - {path.name}")
    if len(orphan_files) > 10:
        print(f"  ...（另 {len(orphan_files) - 10} 個）")

    if not args.apply:
        print()
        print("(dry-run 模式：未執行刪除。確認列表無誤後加 --apply 真的清理)")
        return 0

    print()
    print("=== 執行清理 ===")
    n_threads = _delete_threads(LANGGRAPH_DB, orphan_threads) if LANGGRAPH_DB.exists() else 0
    n_files = _delete_files(orphan_files)
    print(f"deleted langgraph rows (checkpoints): {n_threads}")
    print(f"deleted generated files (docx/xlsx/csv): {n_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
