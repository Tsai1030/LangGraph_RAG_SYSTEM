"""
05_embed_ingest.py — Embedding + ChromaDB 寫入腳本（支援版本管理）

═══ 版本管理模式 ════════════════════════════════════════════════════════════
  --list                    列出所有版本與狀態
  --new                     建立新版本（自動命名 v1、v2…），預設全量 embed
  --new --base v1           以 v1 的 hash 為基礎，只 embed 有變動的文件
  --new --full              明確全量建立新版本
  --version v1              對現有 v1 做增量更新
  --version v1 --full       對 v1 做全量重建
  --activate v1             將 v1 設為 app 使用的 active 版本（更新 .env）

═══ 傳統模式（行為與舊版完全相同）══════════════════════════════════════════
  [無版本參數]              增量更新 chroma_db/ 預設 collection
  --full                    全量重建 chroma_db/ 預設 collection

執行：  cd backend && uv run python scripts/05_embed_ingest.py [選項]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
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

# ── 載入 .env ─────────────────────────────────────────────────────────────────
_ROOT_DIR = Path(__file__).parent.parent.parent
_ENV_FILE = _ROOT_DIR / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── 路徑常數 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
OUTPUT_DIR  = SCRIPT_DIR / "output"
MD_DIR      = _ROOT_DIR / "data_markdown"

# 傳統路徑（不帶版本參數時使用，不改動現有行為）
LEGACY_FINAL_CHUNKS = OUTPUT_DIR / "chunks_final.jsonl"
LEGACY_CHUNKS       = OUTPUT_DIR / "chunks.jsonl"
LEGACY_HASHES_FILE  = OUTPUT_DIR / "file_hashes.json"
LEGACY_CHROMA_PATH  = str(BACKEND_DIR / "chroma_db")
LEGACY_COLLECTION   = "construction_knowledge"

# 版本化路徑
VERSIONS_DIR        = OUTPUT_DIR / "versions"
REGISTRY_FILE       = VERSIONS_DIR / "registry.json"
CHROMA_VERSIONS_DIR = BACKEND_DIR / "chroma_versions"

# ── Embedding 設定 ────────────────────────────────────────────────────────────
EMBEDDING_MODEL  = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')
EMBED_BATCH_SIZE = 50
EMBED_RETRY      = 3
COLLECTION_NAME  = "construction_knowledge"


# ══════════════════════════════════════════════════════════════════════════════
# 版本 Registry
# ══════════════════════════════════════════════════════════════════════════════

def load_registry() -> dict:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))
    return {"versions": {}, "active": None}


def save_registry(reg: dict) -> None:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def next_version_name(reg: dict) -> str:
    """自動產生下一個不衝突的版本號：v1, v2, v3…"""
    n = 1
    while f"v{n}" in reg["versions"]:
        n += 1
    return f"v{n}"


def version_out_dir(version: str) -> Path:
    return VERSIONS_DIR / version


def version_chroma_dir(version: str) -> Path:
    return CHROMA_VERSIONS_DIR / version


# ══════════════════════════════════════════════════════════════════════════════
# Hash 工具
# ══════════════════════════════════════════════════════════════════════════════

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_hashes(hashes_file: Path) -> dict[str, str]:
    if hashes_file.exists():
        return json.loads(hashes_file.read_text(encoding='utf-8'))
    return {}


def save_hashes(hashes: dict[str, str], hashes_file: Path) -> None:
    hashes_file.parent.mkdir(parents=True, exist_ok=True)
    hashes_file.write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8'
    )


# ══════════════════════════════════════════════════════════════════════════════
# Chunk 載入
# ══════════════════════════════════════════════════════════════════════════════

def load_chunks(source_file: Path | None = None) -> list[dict]:
    if source_file is None:
        source_file = LEGACY_FINAL_CHUNKS if LEGACY_FINAL_CHUNKS.exists() else LEGACY_CHUNKS
    if not source_file.exists():
        print(f"[ERROR] 找不到 chunks 檔案: {source_file}", file=sys.stderr)
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


# ══════════════════════════════════════════════════════════════════════════════
# 增量邏輯
# ══════════════════════════════════════════════════════════════════════════════

def get_changed_files(
    all_chunks: list[dict],
    old_hashes: dict,
    force_full: bool,
) -> set[str]:
    if force_full:
        return {c['source_file'] for c in all_chunks}

    changed: set[str] = set()
    md_files = {f.stem: f for f in MD_DIR.glob('*.md')}

    for chunk in all_chunks:
        src = chunk['source_file']
        md_path = None
        for stem, path in md_files.items():
            if stem.startswith(src) or src in stem:
                md_path = path
                break
        if md_path is None:
            changed.add(src)
            continue
        if old_hashes.get(src) != sha256_file(md_path):
            changed.add(src)

    return changed


# ══════════════════════════════════════════════════════════════════════════════
# Embedding
# ══════════════════════════════════════════════════════════════════════════════

def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    for attempt in range(EMBED_RETRY):
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [item.embedding for item in response.data]
        except Exception as e:
            if attempt == EMBED_RETRY - 1:
                raise
            wait = 2 ** attempt
            print(f"  [WARN] Embed 失敗，{wait}s 後重試: {e}")
            time.sleep(wait)
    return []


# ══════════════════════════════════════════════════════════════════════════════
# ChromaDB 操作
# ══════════════════════════════════════════════════════════════════════════════

def open_collection(chroma_path: str, collection_name: str = COLLECTION_NAME):
    client = chromadb.PersistentClient(
        path=chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def delete_source_chunks(collection, source_files: set[str]) -> None:
    for src in source_files:
        try:
            collection.delete(where={"source_file": src})
            print(f"  已刪除舊 chunks: {src}")
        except Exception as e:
            print(f"  [WARN] 刪除失敗 {src}: {e}")


def build_metadata(chunk: dict) -> dict:
    return {
        "chunk_id":      chunk["chunk_id"],
        "source_file":   chunk["source_file"],
        "section_code":  chunk["section_code"],
        "chapter":       chunk["chapter"],
        "phase":         chunk["phase"],
        "document_type": chunk["document_type"],
        "file_type":     chunk["file_type"],
        "tags":          ",".join(chunk.get("tags", [])),
        "parent_h1":     chunk.get("parent_h1", ""),
        "parent_h2":     chunk.get("parent_h2", ""),
        "parent_h3":     chunk.get("parent_h3", ""),
        "chunk_index":   chunk["chunk_index"],
        "has_images":    chunk.get("has_images", False),
        "image_paths":   ",".join(chunk.get("image_paths", [])),
        "image_tags":    ",".join(chunk.get("image_tags", [])),
        "token_count":   chunk.get("token_count", 0),
    }


def ingest_chunks(
    client_openai: OpenAI,
    collection,
    chunks: list[dict],
    label: str = "",
) -> None:
    total = len(chunks)
    if total == 0:
        return
    print(f"  開始 embed {label}（{total} 個 chunks）...")
    for batch_start in range(0, total, EMBED_BATCH_SIZE):
        batch = chunks[batch_start: batch_start + EMBED_BATCH_SIZE]
        texts = [c['text'] for c in batch]
        try:
            embeddings = embed_texts(client_openai, texts)
        except Exception as e:
            print(f"  [ERROR] Embed 批次失敗: {e}")
            continue
        try:
            collection.add(
                ids=[c['chunk_id'] for c in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[build_metadata(c) for c in batch],
            )
        except Exception as e:
            print(f"  [ERROR] ChromaDB 寫入失敗: {e}")
            continue
        progress = min(batch_start + EMBED_BATCH_SIZE, total)
        print(f"    {progress}/{total} 已完成", end='\r', flush=True)
        time.sleep(0.1)
    print(f"    {total}/{total} 已完成")


# ══════════════════════════════════════════════════════════════════════════════
# .env 更新
# ══════════════════════════════════════════════════════════════════════════════

def update_env_version(version: str) -> None:
    if not _ENV_FILE.exists():
        print(f"  [WARN] 找不到 .env，請手動加入：CHROMA_ACTIVE_VERSION={version}")
        return
    content = _ENV_FILE.read_text(encoding='utf-8')
    lines = content.splitlines(keepends=True)
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith('CHROMA_ACTIVE_VERSION'):
            new_lines.append(f"CHROMA_ACTIVE_VERSION={version}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        # 加在 ChromaDB 區塊附近或檔案末尾
        new_lines.append(f"CHROMA_ACTIVE_VERSION={version}\n")
    _ENV_FILE.write_text(''.join(new_lines), encoding='utf-8')
    print(f"  .env 已更新：CHROMA_ACTIVE_VERSION={version}")


# ══════════════════════════════════════════════════════════════════════════════
# 命令：--list
# ══════════════════════════════════════════════════════════════════════════════

def cmd_list() -> None:
    reg = load_registry()
    if not reg["versions"]:
        print("尚無任何版本。使用 --new 建立第一個版本。")
        return
    active = reg.get("active")
    print(f"\n  {'版本':<8} {'建立時間':<22} {'Chunks':<8} {'基礎版本':<10} 狀態")
    print("  " + "─" * 58)
    for vname, info in sorted(reg["versions"].items()):
        marker   = " <-- active" if vname == active else ""
        base     = info.get("base") or "—"
        created  = info.get("created_at", "")[:19].replace("T", " ")
        count    = info.get("chunk_count", "?")
        print(f"  {vname:<8} {created:<22} {str(count):<8} {base:<10}{marker}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# 命令：--activate
# ══════════════════════════════════════════════════════════════════════════════

def cmd_activate(version: str) -> None:
    reg = load_registry()
    if version not in reg["versions"]:
        print(f"[ERROR] 版本 '{version}' 不存在。使用 --list 查看可用版本。", file=sys.stderr)
        sys.exit(1)
    reg["active"] = version
    save_registry(reg)
    update_env_version(version)
    print(f"\n[OK] Active 版本已切換至 {version}（重啟 FastAPI server 後生效）")


# ══════════════════════════════════════════════════════════════════════════════
# 命令：--new / --version（核心 embed 流程）
# ══════════════════════════════════════════════════════════════════════════════

def cmd_embed(
    *,
    version: str | None,   # None = --new（自動命名）
    base: str | None,
    force_full: bool,
    client_openai: OpenAI,
) -> None:
    reg = load_registry()

    # ── 決定版本名稱 ───────────────────────────────────────────────────────────
    if version is None:
        version = next_version_name(reg)
        is_new = True
        print(f"\n建立新版本：{version}")
    else:
        if version not in reg["versions"]:
            print(f"[ERROR] 版本 '{version}' 不存在。使用 --new 建立新版本。", file=sys.stderr)
            sys.exit(1)
        is_new = False
        print(f"\n更新版本：{version}")

    out_dir    = version_out_dir(version)
    chroma_dir = version_chroma_dir(version)
    out_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    # ── 決定增量 hash 基礎 ────────────────────────────────────────────────────
    hashes_file = out_dir / "file_hashes.json"
    if is_new and base:
        base_hashes = version_out_dir(base) / "file_hashes.json"
        if not base_hashes.exists():
            print(f"[ERROR] base 版本 '{base}' 的 file_hashes.json 不存在", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(base_hashes, hashes_file)
        print(f"  使用 {base} 的 hash 作為增量基礎")
    elif is_new and not base:
        # 新版本無 base → 全量（除非使用者已手動放了 hashes）
        if not force_full and not hashes_file.exists():
            print("  新版本無指定 --base，預設全量 embed")
            force_full = True

    old_hashes = load_hashes(hashes_file)

    # ── 載入 chunks ────────────────────────────────────────────────────────────
    all_chunks = load_chunks()

    # ── 決定要重新 embed 的文件 ────────────────────────────────────────────────
    changed_files = get_changed_files(all_chunks, old_hashes, force_full)
    if not changed_files:
        print(f"\n所有文件均無變動，版本 {version} 無需更新。")
        return

    print(f"\n有變動的文件：{len(changed_files)} 份")
    for f in sorted(changed_files):
        print(f"  - {f}")

    chunks_to_ingest = [c for c in all_chunks if c['source_file'] in changed_files]
    print(f"需要 embed 的 chunks：{len(chunks_to_ingest)} 個")

    # ── ChromaDB ───────────────────────────────────────────────────────────────
    print(f"\n連接 ChromaDB: {chroma_dir}")
    _, collection = open_collection(str(chroma_dir))
    print(f"Collection '{COLLECTION_NAME}' 目前有 {collection.count()} 個 chunks")

    # 增量更新：先刪除有變動文件的舊 chunks
    if old_hashes and not (is_new and not base):
        delete_source_chunks(collection, changed_files)

    # Embed 並寫入
    ingest_chunks(client_openai, collection, chunks_to_ingest, version)

    # ── 更新 hash 記錄 ────────────────────────────────────────────────────────
    md_files = {f.stem: f for f in MD_DIR.glob('*.md')}
    new_hashes = dict(old_hashes)
    for src in changed_files:
        for stem, path in md_files.items():
            if stem.startswith(src) or src in stem:
                new_hashes[src] = sha256_file(path)
                break
    save_hashes(new_hashes, hashes_file)

    # ── 複製 chunks 到版本資料夾 ──────────────────────────────────────────────
    src_chunks = LEGACY_FINAL_CHUNKS if LEGACY_FINAL_CHUNKS.exists() else LEGACY_CHUNKS
    shutil.copy2(src_chunks, out_dir / "chunks_final.jsonl")

    # ── 最終統計 ──────────────────────────────────────────────────────────────
    final_count = collection.count()
    now_iso     = datetime.now(timezone.utc).isoformat()

    print(f"\n完成！")
    print(f"  版本：     {version}")
    print(f"  ChromaDB： {chroma_dir}")
    print(f"  Chunks：   {final_count}")
    print(f"  資料夾：   {out_dir}")

    # ── 更新 registry ─────────────────────────────────────────────────────────
    existing = reg["versions"].get(version, {})
    reg["versions"][version] = {
        "created_at":  existing.get("created_at") or now_iso,
        "updated_at":  now_iso,
        "base":        base,
        "chunk_count": final_count,
        "collection":  COLLECTION_NAME,
        "chroma_path": str(version_chroma_dir(version).relative_to(BACKEND_DIR)),
    }
    # 若尚無 active，自動設定
    if reg.get("active") is None:
        reg["active"] = version
        print(f"  自動設為 active 版本")
    save_registry(reg)

    print(f"\n提示：執行 --activate {version} 可將此版本設為 app 使用的 active 版本")


# ══════════════════════════════════════════════════════════════════════════════
# 傳統模式（不帶任何版本參數，行為與舊版完全相同）
# ══════════════════════════════════════════════════════════════════════════════

def cmd_legacy(force_full: bool, client_openai: OpenAI) -> None:
    all_chunks = load_chunks()
    old_hashes = load_hashes(LEGACY_HASHES_FILE)
    new_hashes = dict(old_hashes)

    changed_files = get_changed_files(all_chunks, old_hashes, force_full)
    if not changed_files:
        print("所有文件均無變動，跳過 embed。")
        print(f"ChromaDB collection: {LEGACY_COLLECTION}")
        return

    print(f"\n有變動的文件：{len(changed_files)} 份")
    for f in sorted(changed_files):
        print(f"  - {f}")

    chunks_to_ingest = [c for c in all_chunks if c['source_file'] in changed_files]
    print(f"\n需要 embed 的 chunks：{len(chunks_to_ingest)} 個")

    print(f"\n連接 ChromaDB: {LEGACY_CHROMA_PATH}")
    _, collection = open_collection(LEGACY_CHROMA_PATH, LEGACY_COLLECTION)
    print(f"Collection '{LEGACY_COLLECTION}' 目前有 {collection.count()} 個 chunks")

    if old_hashes:
        delete_source_chunks(collection, changed_files)

    ingest_chunks(client_openai, collection, chunks_to_ingest, "legacy")

    md_files = {f.stem: f for f in MD_DIR.glob('*.md')}
    for src in changed_files:
        for stem, path in md_files.items():
            if stem.startswith(src) or src in stem:
                new_hashes[src] = sha256_file(path)
                break

    save_hashes(new_hashes, LEGACY_HASHES_FILE)

    final_count = collection.count()
    print(f"\n完成！")
    print(f"  ChromaDB collection '{LEGACY_COLLECTION}'：{final_count} 個 chunks")
    print(f"  Hash 記錄已更新：{LEGACY_HASHES_FILE}")
    print(f"\n下一步：執行 06_verify.py 驗證結果")


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed and ingest chunks into ChromaDB（支援版本管理）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--list',     action='store_true',  help='列出所有版本')
    mode.add_argument('--new',      action='store_true',  help='建立新版本（自動命名）')
    mode.add_argument('--version',  metavar='VERSION',    help='更新現有版本，如 --version v1')
    mode.add_argument('--activate', metavar='VERSION',    help='設定 active 版本並更新 .env')

    parser.add_argument('--base', metavar='VERSION',
                        help='（搭配 --new）以此版本的 hash 為增量基礎')
    parser.add_argument('--full', action='store_true',
                        help='強制全量重新 embed')

    args = parser.parse_args()

    # --list / --activate 不需要 OpenAI
    if args.list:
        cmd_list()
        return

    if args.activate:
        cmd_activate(args.activate)
        return

    # 其他模式需要 API Key
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        print("[ERROR] 未設定 OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)
    client_openai = OpenAI(api_key=api_key)

    if args.new:
        cmd_embed(
            version=None,
            base=args.base,
            force_full=args.full,
            client_openai=client_openai,
        )
    elif args.version:
        if args.base:
            print("[ERROR] --base 只能搭配 --new 使用", file=sys.stderr)
            sys.exit(1)
        cmd_embed(
            version=args.version,
            base=None,
            force_full=args.full,
            client_openai=client_openai,
        )
    else:
        # 傳統模式
        if args.base:
            print("[ERROR] --base 需搭配 --new 使用", file=sys.stderr)
            sys.exit(1)
        cmd_legacy(force_full=args.full, client_openai=client_openai)


if __name__ == '__main__':
    main()
