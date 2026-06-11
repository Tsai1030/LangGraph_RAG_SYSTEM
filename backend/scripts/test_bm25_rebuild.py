"""驗證 BM25 rebuild：兩次 rebuild 文件數穩定、retrieve 快照正常運作。

用法：uv run python scripts/test_bm25_rebuild.py
（只讀本地 Chroma；retrieve 會打 embedding API 一次）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag import retriever as r


async def main():
    n1 = await r.rebuild_bm25()
    print(f"rebuild #1 -> {n1} docs")
    assert n1 > 0

    state1 = r._bm25_state
    n2 = await r.rebuild_bm25()
    print(f"rebuild #2 -> {n2} docs")
    assert n2 == n1
    assert r._bm25_state is not state1, "rebuild 應換置新 tuple"

    chunks = await r.retrieve("動員開工檢核")
    print(f"retrieve -> {len(chunks)} chunks; top source = "
          f"{chunks[0].get('metadata', {}).get('source_file', '?') if chunks else 'N/A'}")
    assert len(chunks) > 0
    print("ALL PASS")


asyncio.run(main())
