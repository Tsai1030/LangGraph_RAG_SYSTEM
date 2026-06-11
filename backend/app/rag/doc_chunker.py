"""
doc_chunker.py — 聊天上傳文件的通用 Markdown chunker

與 scripts/02_chunk.py 的差異：KB chunker 針對營造領域文件（Type A/B/C）
做客製切分；這裡處理的是使用者上傳的任意 PDF/DOCX/PPTX（經 markitdown
轉出的 Markdown），只做通用的「標題切分 + token 上限切分」。

Token 常數沿用 KB pipeline（cl100k_base）：MIN=80 / TARGET=500 / MAX=1000。
"""

from __future__ import annotations

import re

import tiktoken

MIN_TOKENS = 80
TARGET_TOKENS = 500
MAX_TOKENS = 1000
OVERLAP_TOKENS = 50  # 超長段落強制切分時的重疊量

_enc = tiktoken.get_encoding("cl100k_base")

_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _split_sections(md_text: str) -> list[dict]:
    """依 H1–H3 標題切段，並記錄每段的標題階層 context。

    回傳 [{text, h1, h2, h3}]；文件開頭沒有標題的內容自成一段（標題皆空）。
    """
    sections: list[dict] = []
    current_lines: list[str] = []
    h1 = h2 = h3 = ""

    def flush():
        text = "\n".join(current_lines).strip()
        if text:
            sections.append({"text": text, "h1": h1, "h2": h2, "h3": h3})
        current_lines.clear()

    for line in md_text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 1:
                h1, h2, h3 = title, "", ""
            elif level == 2:
                h2, h3 = title, ""
            else:
                h3 = title
        current_lines.append(line)
    flush()
    return sections


def _split_long_text(text: str) -> list[str]:
    """把超過 MAX_TOKENS 的文字切成多塊：先按段落累積到 TARGET，
    單一段落仍超長時按 token 硬切（帶 OVERLAP_TOKENS 重疊）。"""
    paragraphs = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    pieces: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    def flush_buf():
        nonlocal buf_tokens
        if buf:
            pieces.append("\n\n".join(buf))
            buf.clear()
            buf_tokens = 0

    for para in paragraphs:
        n = _count_tokens(para)
        if n > MAX_TOKENS:
            flush_buf()
            tokens = _enc.encode(para)
            step = TARGET_TOKENS - OVERLAP_TOKENS
            for start in range(0, len(tokens), step):
                window = tokens[start : start + TARGET_TOKENS]
                pieces.append(_enc.decode(window))
                if start + TARGET_TOKENS >= len(tokens):
                    break
            continue
        if buf_tokens + n > TARGET_TOKENS:
            flush_buf()
        buf.append(para)
        buf_tokens += n
    flush_buf()
    return pieces


def chunk_markdown(md_text: str, source_file: str) -> list[dict]:
    """把 markitdown 轉出的 Markdown 切成 chunks。

    回傳 [{document, metadata}]，metadata 與 KB chunks 對齊（source_file /
    parent_h2 / parent_h3），讓 context_builder 與 format_sources 不用改。
    注意：ChromaDB metadata 不接受 None，空標題直接省略 key。
    """
    raw_chunks: list[dict] = []  # [{text, h1, h2, h3}]
    pending: dict | None = None  # 過小段落暫存，併入下一段

    for section in _split_sections(md_text):
        text = section["text"]
        if pending is not None:
            # 標題 context 用當前段落的（合併後主要內容屬於當前段落）
            text = pending["text"] + "\n\n" + text
            section = {**section, "text": text}
            pending = None
        n = _count_tokens(text)
        if n < MIN_TOKENS:
            pending = {**section, "text": text}
            continue
        if n > MAX_TOKENS:
            for piece in _split_long_text(text):
                raw_chunks.append({**section, "text": piece})
        else:
            raw_chunks.append({**section, "text": text})

    if pending is not None:
        # 尾段過小：併入最後一個 chunk，沒得併就獨立成 chunk（總比丟掉好）
        if raw_chunks:
            raw_chunks[-1]["text"] += "\n\n" + pending["text"]
        else:
            raw_chunks.append(pending)

    chunks: list[dict] = []
    for i, c in enumerate(raw_chunks):
        metadata: dict = {
            "source_file": source_file,
            "origin": "uploaded",
            "chunk_index": i,
        }
        if c["h1"]:
            metadata["parent_h1"] = c["h1"]
        if c["h2"]:
            metadata["parent_h2"] = c["h2"]
        if c["h3"]:
            metadata["parent_h3"] = c["h3"]
        chunks.append({"document": c["text"], "metadata": metadata})
    return chunks
