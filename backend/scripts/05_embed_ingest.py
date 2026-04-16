"""
05_embed_ingest.py — Embedding + ChromaDB 寫入腳本（支援增量更新）

功能：
1. 讀取 chunks_final.jsonl（若存在）或 chunks.jsonl
2. 載入 file_hashes.json，比對 SHA256 hash
3. 只重新 embed 有變動的文件（增量更新）
4. 批量呼叫 text-embedding-3-small
5. 寫入 ChromaDB persistent collection（construction_knowledge）
6. 更新 file_hashes.json

執行方式：
    cd backend
    uv run python scripts/05_embed_ingest.py [--full]

選項：
    --full   強制全量重新 embed（忽略 hash 比對）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
except ImportError:
    print("[ERROR] 請先安裝 chromadb", file=sys.stderr)
    sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("[ERROR] 請先安裝 openai", file=sys.stderr)
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
BACKEND_DIR = SCRIPT_DIR.parent
DATA_ROOT = BACKEND_DIR.parent
OUTPUT_DIR = SCRIPT_DIR / "output"
MD_DIR = DATA_ROOT / "data_markdown"

FINAL_CHUNKS_FILE = OUTPUT_DIR / "chunks_final.jsonl"
CHUNKS_FILE = OUTPUT_DIR / "chunks.jsonl"
HASHES_FILE = OUTPUT_DIR / "file_hashes.json"

CHROMA_PATH = str(BACKEND_DIR / "chroma_db")
COLLECTION_NAME = "construction_knowledge"

# ── Embedding 設定 ────────────────────────────────────────────
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')
EMBED_BATCH_SIZE = 50  # 每批送 OpenAI 的數量
EMBED_RETRY = 3        # 失敗重試次數


# ── Hash 工具 ─────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_hashes() -> dict[str, str]:
    if HASHES_FILE.exists():
        return json.loads(HASHES_FILE.read_text(encoding='utf-8'))
    return {}


def save_hashes(hashes: dict[str, str]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HASHES_FILE.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')


# ── Chunk 載入 ────────────────────────────────────────────────

def load_chunks() -> list[dict]:
    source_file = FINAL_CHUNKS_FILE if FINAL_CHUNKS_FILE.exists() else CHUNKS_FILE
    if not source_file.exists():
        print(f"[ERROR] 找不到 chunks 檔案（{FINAL_CHUNKS_FILE} 或 {CHUNKS_FILE}）", file=sys.stderr)
        print("請先執行 02_chunk.py", file=sys.stderr)
        sys.exit(1)

    chunks = []
    with source_file.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))

    print(f"載入 {len(chunks)} 個 chunks（來源：{source_file.name}）")
    return chunks


# ── 增量更新邏輯 ──────────────────────────────────────────────

def get_changed_files(all_chunks: list[dict], old_hashes: dict, force_full: bool) -> set[str]:
    """
    比對 data_markdown/ 中的 .md 文件 hash，
    回傳有變動（新增/修改）的 source_file 集合。
    """
    if force_full:
        return {c['source_file'] for c in all_chunks}

    changed = set()
    md_files = {f.stem: f for f in MD_DIR.glob('*.md')}

    for chunk in all_chunks:
        src = chunk['source_file']
        # 找對應的 MD 檔（stem 匹配）
        md_path = None
        for stem, path in md_files.items():
            if stem.startswith(src) or src in stem:
                md_path = path
                break

        if md_path is None:
            # 找不到原始 MD，視為需要重新處理
            changed.add(src)
            continue

        current_hash = sha256_file(md_path)
        if old_hashes.get(src) != current_hash:
            changed.add(src)

    return changed


# ── Embedding ─────────────────────────────────────────────────

def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """批量 embed，含重試邏輯"""
    for attempt in range(EMBED_RETRY):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            if attempt == EMBED_RETRY - 1:
                raise
            wait = 2 ** attempt
            print(f"  [WARN] Embed 失敗，{wait}s 後重試: {e}")
            time.sleep(wait)
    return []  # unreachable


# ── ChromaDB 操作 ─────────────────────────────────────────────

def get_collection(chroma_path: str):
    """取得或建立 ChromaDB collection"""
    client = chromadb.PersistentClient(
        path=chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def delete_source_chunks(collection, source_files: set[str]):
    """刪除指定 source_file 的所有舊 chunks"""
    for src in source_files:
        try:
            collection.delete(where={"source_file": src})
            print(f"  已刪除舊 chunks: {src}")
        except Exception as e:
            print(f"  [WARN] 刪除失敗 {src}: {e}")


def build_metadata(chunk: dict) -> dict:
    """
    ChromaDB metadata 僅支援 str/int/float/bool，
    list 需轉換為逗號分隔字串。
    """
    return {
        "chunk_id": chunk["chunk_id"],
        "source_file": chunk["source_file"],
        "section_code": chunk["section_code"],
        "chapter": chunk["chapter"],
        "phase": chunk["phase"],
        "document_type": chunk["document_type"],
        "file_type": chunk["file_type"],
        "tags": ",".join(chunk.get("tags", [])),
        "parent_h1": chunk.get("parent_h1", ""),
        "parent_h2": chunk.get("parent_h2", ""),
        "parent_h3": chunk.get("parent_h3", ""),
        "chunk_index": chunk["chunk_index"],
        "has_images": chunk.get("has_images", False),
        "image_paths": ",".join(chunk.get("image_paths", [])),
        "image_tags": ",".join(chunk.get("image_tags", [])),
        "token_count": chunk.get("token_count", 0),
    }


def ingest_chunks(
    client_openai: OpenAI,
    collection,
    chunks: list[dict],
    label: str = "",
):
    """批量 embed 並寫入 ChromaDB"""
    total = len(chunks)
    if total == 0:
        return

    print(f"  開始 embed {label}（{total} 個 chunks）...")

    for batch_start in range(0, total, EMBED_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + EMBED_BATCH_SIZE]
        texts = [c['text'] for c in batch]

        try:
            embeddings = embed_texts(client_openai, texts)
        except Exception as e:
            print(f"  [ERROR] Embed 批次失敗: {e}")
            continue

        ids = [c['chunk_id'] for c in batch]
        metadatas = [build_metadata(c) for c in batch]

        try:
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        except Exception as e:
            print(f"  [ERROR] ChromaDB 寫入失敗: {e}")
            continue

        progress = min(batch_start + EMBED_BATCH_SIZE, total)
        print(f"    {progress}/{total} 已完成", end='\r', flush=True)
        time.sleep(0.1)  # 避免 rate limit

    print(f"    {total}/{total} 已完成")


# ── 主流程 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Embed and ingest chunks into ChromaDB')
    parser.add_argument('--full', action='store_true', help='強制全量重新 embed')
    args = parser.parse_args()

    # 環境檢查
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        print("[ERROR] 未設定 OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client_openai = OpenAI(api_key=api_key)

    # 載入 chunks
    all_chunks = load_chunks()

    # 載入 hash 記錄
    old_hashes = load_hashes()
    new_hashes = dict(old_hashes)

    # 決定要更新的 source_file
    changed_files = get_changed_files(all_chunks, old_hashes, args.full)

    if not changed_files:
        print("所有文件均無變動，跳過 embed。")
        print(f"ChromaDB collection: {COLLECTION_NAME}")
        return

    print(f"\n有變動的文件：{len(changed_files)} 份")
    for f in sorted(changed_files):
        print(f"  - {f}")

    # 篩選需要重新 embed 的 chunks
    chunks_to_ingest = [c for c in all_chunks if c['source_file'] in changed_files]
    print(f"\n需要 embed 的 chunks：{len(chunks_to_ingest)} 個")

    # 取得 ChromaDB collection
    print(f"\n連接 ChromaDB: {CHROMA_PATH}")
    _, collection = get_collection(CHROMA_PATH)
    print(f"Collection '{COLLECTION_NAME}' 目前有 {collection.count()} 個 chunks")

    # 刪除舊 chunks（若非全新文件）
    if old_hashes:
        delete_source_chunks(collection, changed_files)

    # Embed 並寫入
    ingest_chunks(client_openai, collection, chunks_to_ingest, "changed files")

    # 更新 hash 記錄
    md_files = {f.stem: f for f in MD_DIR.glob('*.md')}
    for src in changed_files:
        for stem, path in md_files.items():
            if stem.startswith(src) or src in stem:
                new_hashes[src] = sha256_file(path)
                break

    save_hashes(new_hashes)

    # 最終統計
    final_count = collection.count()
    print(f"\n完成！")
    print(f"  ChromaDB collection '{COLLECTION_NAME}'：{final_count} 個 chunks")
    print(f"  Hash 記錄已更新：{HASHES_FILE}")
    print(f"\n下一步：執行 06_verify.py 驗證結果")


if __name__ == '__main__':
    main()
