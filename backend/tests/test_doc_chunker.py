"""doc_chunker / upload_guard.sniff_document_kind 單元測試"""

from app.rag.doc_chunker import (
    MAX_TOKENS,
    MIN_TOKENS,
    _count_tokens,
    chunk_markdown,
)
from app.services.upload_guard import sniff_document_kind


# ── chunk_markdown ─────────────────────────────────────────────

def test_header_split_and_metadata():
    md = (
        "# 文件標題\n\n"
        "## 第一章\n\n" + "這是第一章的內容。" * 30 + "\n\n"
        "### 1.1 小節\n\n" + "小節內容說明文字。" * 30 + "\n\n"
        "## 第二章\n\n" + "第二章內容。" * 30
    )
    chunks = chunk_markdown(md, source_file="test.pdf")

    assert len(chunks) >= 3
    for i, c in enumerate(chunks):
        assert c["metadata"]["source_file"] == "test.pdf"
        assert c["metadata"]["origin"] == "uploaded"
        assert c["metadata"]["chunk_index"] == i

    # 標題階層有被記錄
    h2s = {c["metadata"].get("parent_h2") for c in chunks}
    assert "第一章" in h2s
    assert "第二章" in h2s
    h3_chunk = next(c for c in chunks if c["metadata"].get("parent_h3") == "1.1 小節")
    assert "小節內容" in h3_chunk["document"]


def test_token_caps():
    # 超長無標題文字 → 全部 chunk 都不超過 MAX_TOKENS
    md = "段落內容測試文字。" * 2000
    chunks = chunk_markdown(md, source_file="long.docx")
    assert len(chunks) > 1
    for c in chunks:
        assert _count_tokens(c["document"]) <= MAX_TOKENS


def test_tiny_sections_merged():
    # 多個過小段落應合併，而不是各自成 chunk
    md = "## A\n\n短。\n\n## B\n\n也短。\n\n## C\n\n" + "夠長的內容。" * 50
    chunks = chunk_markdown(md, source_file="t.pptx")
    assert all(
        _count_tokens(c["document"]) >= MIN_TOKENS for c in chunks[:-1]
    ) or len(chunks) == 1


def test_empty_input():
    assert chunk_markdown("", source_file="empty.pdf") == []


def test_no_none_in_metadata():
    # ChromaDB metadata 不接受 None：無標題文件不能帶 parent_h* key
    md = "純文字內容沒有任何標題。" * 40
    chunks = chunk_markdown(md, source_file="plain.pdf")
    for c in chunks:
        assert None not in c["metadata"].values()
        assert "parent_h1" not in c["metadata"]


# ── sniff_document_kind ───────────────────────────────────────

def test_sniff_pdf():
    assert sniff_document_kind(b"%PDF-1.7 rest...") == "pdf"


def test_sniff_zip():
    assert sniff_document_kind(b"PK\x03\x04rest...") == "zip"


def test_sniff_garbage():
    assert sniff_document_kind(b"MZ\x90\x00 exe header") is None
    assert sniff_document_kind(b"") is None
