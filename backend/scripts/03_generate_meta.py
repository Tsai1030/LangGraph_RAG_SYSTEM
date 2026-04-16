"""
03_generate_meta.py — GPT 批量 Metadata 生成腳本

功能：
1. 讀取 scripts/output/chunks.jsonl
2. 找出缺少 tags（空 list）的 chunks
3. 批量呼叫 GPT（每批 10 個 chunk）生成語意標籤
4. 輸出 scripts/output/metadata_review.csv 供人工審查

執行方式：
    cd backend
    uv run python scripts/03_generate_meta.py

注意：
- 需要 OPENAI_API_KEY 環境變數（從 .env 讀取）
- 輸出的 CSV 請人工審查後再執行 04_review_meta.py
- 若某批次失敗，腳本會標記 error 並繼續，不中斷
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("[ERROR] 請先安裝 openai: uv add openai", file=sys.stderr)
    sys.exit(1)

# 載入 .env
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── 路徑設定 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"
CHUNKS_FILE = OUTPUT_DIR / "chunks.jsonl"
REVIEW_CSV = OUTPUT_DIR / "metadata_review.csv"

# ── GPT 設定 ──────────────────────────────────────────────────
BATCH_SIZE = 10
MODEL = "gpt-4o-mini"  # 用便宜的 mini 版本生成標籤

SYSTEM_PROMPT = """你是一位專業的台灣營造業知識管理顧問。
你的任務是為以下建築工程管理文件的片段（chunk）生成精確的語意標籤（tags）。

標籤規則：
1. 生成 5–8 個關鍵詞標籤
2. 標籤以繁體中文為主
3. 涵蓋：作業類型、適用對象、管理層面、文件動作
4. 不使用過於泛化的詞（如「工程」、「管理」、「作業」）
5. 以 JSON array 格式回覆，例如：["動員開工", "工令", "業主提報", "專案負責人"]"""

USER_PROMPT_TEMPLATE = """請為以下營造業文件片段生成標籤：

文件節次：{section_code}
階段：{phase}
文件類型：{document_type}
上層標題：{parent_h2} / {parent_h3}

---
{text}
---

請以 JSON array 格式回覆標籤（5–8 個），不需要其他說明文字。"""


def load_chunks() -> list[dict]:
    if not CHUNKS_FILE.exists():
        print(f"[ERROR] 找不到 {CHUNKS_FILE}", file=sys.stderr)
        print("請先執行 02_chunk.py", file=sys.stderr)
        sys.exit(1)

    chunks = []
    with CHUNKS_FILE.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def needs_tags(chunk: dict) -> bool:
    """判斷此 chunk 是否需要 GPT 生成標籤"""
    return not chunk.get('tags')


def generate_tags_batch(client: OpenAI, batch: list[dict]) -> list[list[str]]:
    """
    批量生成標籤，回傳與 batch 等長的 tags list。
    若單一 chunk 失敗，標記為空 list。
    """
    results = []
    for chunk in batch:
        text_preview = chunk['text'][:800]  # 只送前 800 字

        prompt = USER_PROMPT_TEMPLATE.format(
            section_code=chunk.get('section_code', ''),
            phase=chunk.get('phase', ''),
            document_type=chunk.get('document_type', ''),
            parent_h2=chunk.get('parent_h2', ''),
            parent_h3=chunk.get('parent_h3', ''),
            text=text_preview,
        )

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=200,
            )
            raw = response.choices[0].message.content.strip()
            # 解析 JSON array
            tags = json.loads(raw)
            if not isinstance(tags, list):
                tags = []
            results.append([str(t) for t in tags])
        except Exception as e:
            print(f"  [WARN] 生成失敗 chunk_id={chunk['chunk_id'][:8]}: {e}")
            results.append([])  # 失敗標記為空

        # Rate limit 保護
        time.sleep(0.3)

    return results


def main():
    chunks = load_chunks()
    print(f"載入 {len(chunks)} 個 chunks")

    # 篩選需要生成 tags 的 chunks
    need_tags_chunks = [(i, c) for i, c in enumerate(chunks) if needs_tags(c)]
    print(f"需要生成 tags：{len(need_tags_chunks)} 個 chunks")

    if not need_tags_chunks:
        print("所有 chunks 已有 tags，跳過生成。")
        # 仍輸出 CSV 以供審查
    else:
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            print("[ERROR] 未設定 OPENAI_API_KEY", file=sys.stderr)
            sys.exit(1)

        client = OpenAI(api_key=api_key)

        print(f"\n開始批量生成（每批 {BATCH_SIZE} 個，共 {len(need_tags_chunks)} 個）...")

        # 分批處理
        for batch_start in range(0, len(need_tags_chunks), BATCH_SIZE):
            batch_items = need_tags_chunks[batch_start:batch_start + BATCH_SIZE]
            batch_chunks = [c for _, c in batch_items]

            print(f"  批次 {batch_start // BATCH_SIZE + 1}"
                  f"/{(len(need_tags_chunks) + BATCH_SIZE - 1) // BATCH_SIZE}"
                  f" ({len(batch_chunks)} 個)...", end=' ', flush=True)

            tags_list = generate_tags_batch(client, batch_chunks)

            # 更新 chunks（in-place）
            for (orig_idx, chunk), tags in zip(batch_items, tags_list):
                chunks[orig_idx]['tags'] = tags

            print(f"完成")

    # 輸出 CSV
    with REVIEW_CSV.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'chunk_id', 'source_file', 'section_code', 'phase',
            'document_type', 'file_type', 'parent_h2', 'parent_h3',
            'generated_tags', 'approved',  # approved 欄位供人工確認後填寫
            'text_preview',
        ])
        writer.writeheader()

        for chunk in chunks:
            writer.writerow({
                'chunk_id': chunk['chunk_id'],
                'source_file': chunk['source_file'],
                'section_code': chunk['section_code'],
                'phase': chunk['phase'],
                'document_type': chunk['document_type'],
                'file_type': chunk['file_type'],
                'parent_h2': chunk.get('parent_h2', ''),
                'parent_h3': chunk.get('parent_h3', ''),
                'generated_tags': ','.join(chunk.get('tags', [])),
                'approved': '',  # 人工審查後填 'y' 或修改 tags
                'text_preview': chunk['text'][:150].replace('\n', ' '),
            })

    # 同時更新 chunks.jsonl（寫入已生成的 tags）
    with CHUNKS_FILE.open('w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    print(f"\n完成！")
    print(f"  審查 CSV 輸出至：{REVIEW_CSV}")
    print(f"  chunks.jsonl 已更新（含生成的 tags）")
    print(f"\n下一步：")
    print(f"  1. 開啟 {REVIEW_CSV} 審查 tags 品質")
    print(f"  2. 確認無誤後執行 04_review_meta.py 合併結果")


if __name__ == '__main__':
    main()
