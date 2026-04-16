"""
06_verify.py — ChromaDB 驗證腳本

功能：
1. 驗證 ChromaDB collection 存在且 chunk 數量合理
2. 執行 5 筆測試查詢，確認結果語意正確
3. 驗證 metadata 完整性（所有必要欄位）
4. 輸出驗證報告至 scripts/output/verify_report.txt

執行方式：
    cd backend
    uv run python scripts/06_verify.py
"""

from __future__ import annotations

import io
import os
import sys
import json
from datetime import datetime

# Windows cp950 終端機無法輸出 emoji，強制使用 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
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
OUTPUT_DIR = SCRIPT_DIR / "output"
REPORT_FILE = OUTPUT_DIR / "verify_report.txt"

CHROMA_PATH = str(BACKEND_DIR / "chroma_db")
COLLECTION_NAME = "construction_knowledge"

EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')

# ── 測試查詢 ──────────────────────────────────────────────────
TEST_QUERIES = [
    {
        "query": "動員開工需要哪些初期計畫",
        "expect_files": ["010101"],
        "description": "動員開工初期計畫（010101）",
    },
    {
        "query": "採購發包金額分級標準",
        "expect_files": ["020101"],
        "description": "採購發包金額分級（020101）",
    },
    {
        "query": "工務所辦公室設置的評估原則",
        "expect_files": ["010102"],
        "description": "工務所辦公室設置（010102）",
    },
    {
        "query": "協力廠商估驗及計價流程",
        "expect_files": ["020102"],
        "description": "協力廠商估驗計價（020102）",
    },
    {
        "query": "竣工報告應該包含哪些內容",
        "expect_files": ["030103"],
        "description": "竣工報告（030103）",
    },
]

REQUIRED_METADATA_FIELDS = [
    'chunk_id', 'source_file', 'section_code', 'chapter',
    'phase', 'document_type', 'file_type', 'chunk_index',
    'has_images', 'token_count',
]


def get_embedding(client: OpenAI, text: str) -> list[float]:
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding


def run_query_test(client_openai: OpenAI, collection, test: dict) -> dict:
    """執行單一測試查詢"""
    query_embedding = get_embedding(client_openai, test['query'])

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5,
        include=['documents', 'metadatas', 'distances'],
    )

    docs = results['documents'][0]
    metas = results['metadatas'][0]
    dists = results['distances'][0]

    # 檢查期望的 source_file 是否出現在結果中
    result_sections = [m.get('section_code', '') for m in metas]
    expect_hit = any(
        any(exp in sec for sec in result_sections)
        for exp in test['expect_files']
    )

    return {
        "query": test['query'],
        "description": test['description'],
        "passed": expect_hit,
        "top_results": [
            {
                "source_file": m.get('source_file', ''),
                "section_code": m.get('section_code', ''),
                "parent_h2": m.get('parent_h2', ''),
                "distance": round(d, 4),
                "preview": doc[:100].replace('\n', ' '),
            }
            for m, d, doc in zip(metas[:3], dists[:3], docs[:3])
        ],
    }


def check_metadata_completeness(collection) -> dict:
    """抽樣檢查 metadata 完整性"""
    sample = collection.get(limit=20, include=['metadatas'])
    metas = sample['metadatas']

    missing_fields: dict[str, int] = {}
    for meta in metas:
        for field in REQUIRED_METADATA_FIELDS:
            if field not in meta or meta[field] is None:
                missing_fields[field] = missing_fields.get(field, 0) + 1

    return {
        "sample_size": len(metas),
        "missing_fields": missing_fields,
        "completeness_ok": len(missing_fields) == 0,
    }


def check_source_coverage(collection) -> dict:
    """檢查各 source_file 的 chunk 分布"""
    all_metas = collection.get(include=['metadatas'])['metadatas']
    source_counts: dict[str, int] = {}
    for meta in all_metas:
        src = meta.get('source_file', 'unknown')
        source_counts[src] = source_counts.get(src, 0) + 1

    return {
        "total_sources": len(source_counts),
        "total_chunks": sum(source_counts.values()),
        "min_chunks_per_source": min(source_counts.values()) if source_counts else 0,
        "max_chunks_per_source": max(source_counts.values()) if source_counts else 0,
        "avg_chunks_per_source": round(sum(source_counts.values()) / len(source_counts), 1) if source_counts else 0,
        "sources": dict(sorted(source_counts.items())),
    }


def main():
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        print("[ERROR] 未設定 OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client_openai = OpenAI(api_key=api_key)

    # 連接 ChromaDB
    print(f"連接 ChromaDB: {CHROMA_PATH}")
    try:
        chroma_client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = chroma_client.get_collection(COLLECTION_NAME)
    except Exception as e:
        print(f"[ERROR] 無法連接 ChromaDB collection '{COLLECTION_NAME}': {e}", file=sys.stderr)
        print("請先執行 05_embed_ingest.py", file=sys.stderr)
        sys.exit(1)

    total_chunks = collection.count()
    print(f"Collection '{COLLECTION_NAME}': {total_chunks} 個 chunks\n")

    report_lines = [
        f"ChromaDB 驗證報告",
        f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Collection：{COLLECTION_NAME}",
        f"總 chunk 數：{total_chunks}",
        "=" * 60,
    ]

    # ── 1. 基本數量檢查 ────────────────────────────────────────
    print("1. 基本數量檢查")
    if total_chunks < 100:
        status = "⚠️  WARNING"
        msg = f"chunk 數量偏少（{total_chunks} < 100），請確認資料管線是否正常"
    elif total_chunks > 2000:
        status = "⚠️  WARNING"
        msg = f"chunk 數量偏多（{total_chunks} > 2000），可能有重複 ingest"
    else:
        status = "✅ PASS"
        msg = f"chunk 數量正常（{total_chunks}）"
    print(f"   {status}: {msg}")
    report_lines += ["", f"1. 基本數量：{status}", f"   {msg}"]

    # ── 2. Metadata 完整性 ─────────────────────────────────────
    print("\n2. Metadata 完整性檢查")
    meta_result = check_metadata_completeness(collection)
    if meta_result['completeness_ok']:
        print(f"   ✅ PASS: 抽樣 {meta_result['sample_size']} 個 chunks，所有必要欄位均存在")
        report_lines += ["", "2. Metadata 完整性：✅ PASS",
                         f"   抽樣 {meta_result['sample_size']} 個 chunks，所有必要欄位均存在"]
    else:
        missing = meta_result['missing_fields']
        print(f"   ⚠️  WARNING: 以下欄位有缺失：{missing}")
        report_lines += ["", "2. Metadata 完整性：⚠️ WARNING",
                         f"   缺失欄位：{missing}"]

    # ── 3. Source 覆蓋率 ──────────────────────────────────────
    print("\n3. Source 文件覆蓋率")
    coverage = check_source_coverage(collection)
    print(f"   總文件數：{coverage['total_sources']}")
    print(f"   每份文件 chunks：min={coverage['min_chunks_per_source']}, "
          f"avg={coverage['avg_chunks_per_source']}, "
          f"max={coverage['max_chunks_per_source']}")
    report_lines += [
        "", "3. Source 覆蓋率：",
        f"   總文件數：{coverage['total_sources']}",
        f"   chunks 分布：min={coverage['min_chunks_per_source']}, "
        f"avg={coverage['avg_chunks_per_source']}, "
        f"max={coverage['max_chunks_per_source']}",
    ]
    # 列出各 source 的 chunk 數
    for src, count in coverage['sources'].items():
        report_lines.append(f"   {src}: {count} chunks")

    # ── 4. 測試查詢 ───────────────────────────────────────────
    print(f"\n4. 測試查詢（{len(TEST_QUERIES)} 筆）")
    report_lines += ["", "4. 測試查詢："]

    passed = 0
    for i, test in enumerate(TEST_QUERIES):
        print(f"   [{i+1}] {test['description']}", end=' ... ', flush=True)
        try:
            result = run_query_test(client_openai, collection, test)
            status_icon = "✅" if result['passed'] else "❌"
            print(f"{status_icon}")
            if result['passed']:
                passed += 1

            report_lines.append(f"\n   [{i+1}] {test['description']}: {status_icon}")
            report_lines.append(f"   查詢：「{test['query']}」")
            for r in result['top_results']:
                report_lines.append(
                    f"   → {r['source_file']} / {r['section_code']} "
                    f"(distance={r['distance']}) — {r['preview']}"
                )
        except Exception as e:
            print(f"ERROR: {e}")
            report_lines.append(f"\n   [{i+1}] ERROR: {e}")

    print(f"\n   測試結果：{passed}/{len(TEST_QUERIES)} 通過")
    report_lines.append(f"\n   總結：{passed}/{len(TEST_QUERIES)} 通過")

    # ── 5. 最終結論 ───────────────────────────────────────────
    all_pass = (
        100 <= total_chunks <= 2000 and
        meta_result['completeness_ok'] and
        passed >= len(TEST_QUERIES) * 0.8  # 至少 80% 通過
    )
    conclusion = "✅ 驗收通過，可進入 Phase 2" if all_pass else "⚠️  需要檢查以上問題再繼續"
    print(f"\n{'='*50}")
    print(f"結論：{conclusion}")

    report_lines += [
        "", "=" * 60,
        f"最終結論：{conclusion}",
    ]

    # 輸出報告
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text('\n'.join(report_lines), encoding='utf-8')
    print(f"驗證報告已輸出：{REPORT_FILE}")


if __name__ == '__main__':
    main()
