"""
07_clean_chunks.py — 清理 chunks_final.jsonl 中的雜訊 chunk

刪除規則：
- 整行 JSON 中含有 "rag"（不分大小寫）的 chunk 一律移除
  （涵蓋：RAG 使用建議、RAG 友善 Markdown、內容摘要等說明性區塊）

執行方式：
    cd backend
    uv run python scripts/07_clean_chunks.py
"""

from __future__ import annotations

import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
INPUT_FILE  = SCRIPT_DIR / "output" / "chunks_final.jsonl"
OUTPUT_FILE = SCRIPT_DIR / "output" / "chunks_final_preview.jsonl"   # 原地覆蓋


def main() -> None:
    if not INPUT_FILE.exists():
        print(f"[ERROR] 找不到 {INPUT_FILE}")
        return

    lines = INPUT_FILE.read_text(encoding="utf-8").splitlines()
    total = len(lines)

    kept:    list[str] = []
    removed: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "rag" in line.lower():
            removed.append(line)
        else:
            kept.append(line)

    # 寫回（原地覆蓋）
    OUTPUT_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")

    print(f"原始 chunks：{total}")
    print(f"刪除 chunks：{len(removed)}")
    print(f"保留 chunks：{len(kept)}")

    if removed:
        print("\n--- 被刪除的 chunk 來源（前 20 筆）---")
        for line in removed[:20]:
            try:
                obj = json.loads(line)
                print(f"  [{obj.get('source_file','')}] "
                      f"h2={obj.get('parent_h2','')} "
                      f"h3={obj.get('parent_h3','')} "
                      f"tokens={obj.get('token_count','')}")
            except Exception:
                print(f"  (parse error) {line[:80]}")


if __name__ == "__main__":
    main()
