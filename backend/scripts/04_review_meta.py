"""
04_review_meta.py — 人工審查後合併 Metadata 腳本

功能：
1. 讀取人工審查後的 scripts/output/metadata_review.csv
2. 將審查後的 tags 合併回 chunks.jsonl
3. 輸出 scripts/output/chunks_final.jsonl（供 05_embed_ingest.py 使用）

工作流程：
    03_generate_meta.py 執行後，開啟 metadata_review.csv：
    - 檢查每個 chunk 的 generated_tags 是否正確
    - 若需修改，直接在 CSV 的 generated_tags 欄位編輯
    - 確認無誤的 chunk，在 approved 欄位填入 'y'（或留空代表接受）
    - 若完全不需修改，可以跳過此腳本直接執行 05_embed_ingest.py

執行方式：
    cd backend
    uv run python scripts/04_review_meta.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# ── 路徑設定 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"
CHUNKS_FILE = OUTPUT_DIR / "chunks.jsonl"
REVIEW_CSV = OUTPUT_DIR / "metadata_review.csv"
FINAL_CHUNKS_FILE = OUTPUT_DIR / "chunks_final.jsonl"


def main():
    # 載入現有 chunks
    if not CHUNKS_FILE.exists():
        print(f"[ERROR] 找不到 {CHUNKS_FILE}", file=sys.stderr)
        print("請先執行 02_chunk.py 和 03_generate_meta.py", file=sys.stderr)
        sys.exit(1)

    chunks_by_id: dict[str, dict] = {}
    with CHUNKS_FILE.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                chunks_by_id[c['chunk_id']] = c

    print(f"載入 {len(chunks_by_id)} 個 chunks")

    # 載入審查後的 CSV
    if not REVIEW_CSV.exists():
        print(f"[WARN] 找不到 {REVIEW_CSV}")
        print("直接複製 chunks.jsonl → chunks_final.jsonl")
        import shutil
        shutil.copy(CHUNKS_FILE, FINAL_CHUNKS_FILE)
        print(f"輸出至：{FINAL_CHUNKS_FILE}")
        return

    updated = 0
    errors = 0

    with REVIEW_CSV.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            chunk_id = row.get('chunk_id', '').strip()
            if not chunk_id or chunk_id not in chunks_by_id:
                errors += 1
                continue

            # 讀取審查後的 tags
            raw_tags = row.get('generated_tags', '').strip()
            if raw_tags:
                tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
                chunks_by_id[chunk_id]['tags'] = tags
                updated += 1

    print(f"已更新 {updated} 個 chunk 的 tags（{errors} 個 ID 找不到）")

    # 驗證：找出仍無 tags 的 chunks
    no_tags = [c for c in chunks_by_id.values() if not c.get('tags')]
    if no_tags:
        print(f"\n[WARN] 仍有 {len(no_tags)} 個 chunks 沒有 tags：")
        for c in no_tags[:10]:
            print(f"  - {c['source_file']} / {c['parent_h2']} / {c['parent_h3']}")
        if len(no_tags) > 10:
            print(f"  ... 共 {len(no_tags)} 個")

    # 輸出 chunks_final.jsonl
    chunks_ordered = sorted(
        chunks_by_id.values(),
        key=lambda c: (c['source_file'], c['chunk_index'])
    )

    with FINAL_CHUNKS_FILE.open('w', encoding='utf-8') as f:
        for chunk in chunks_ordered:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    print(f"\n完成！共 {len(chunks_ordered)} 個 chunks")
    print(f"輸出至：{FINAL_CHUNKS_FILE}")
    print(f"\n下一步：執行 05_embed_ingest.py 寫入 ChromaDB")


if __name__ == '__main__':
    main()
