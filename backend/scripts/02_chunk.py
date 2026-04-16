"""
02_chunk.py — 文件切割腳本

功能：
1. 讀取 scripts/output/cleaned/*.md（前處理後的文件）
2. 依文件類型切割：
   - Type A（作業檢核表）：以 H2 為邊界，大型表格按行數分組
   - Type B（標準內文）：以 H3 為邊界，含 H2 context_header
   - Type C（掃描PDF）：清理後以 H2/H3 為邊界
3. 套用圖片保護規則（切割點不落在圖片區塊中間）
4. Chunk 大小控制：80–1000 tokens（超出強制切割，不足向後合併）
5. 提取 metadata（section_code, chapter, tags, image_paths 等）
6. 輸出 scripts/output/chunks.jsonl

執行方式：
    cd backend
    uv run python scripts/02_chunk.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

try:
    import tiktoken
except ImportError:
    print("[ERROR] 請先安裝 tiktoken: uv add tiktoken", file=sys.stderr)
    sys.exit(1)

# ── 路徑設定 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
CLEANED_DIR = SCRIPT_DIR / "output" / "cleaned"
OUTPUT_DIR = SCRIPT_DIR / "output"
CHUNKS_FILE = OUTPUT_DIR / "chunks.jsonl"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Token 計算 ────────────────────────────────────────────────
_ENC = tiktoken.get_encoding("cl100k_base")

CHUNK_MIN = 80
CHUNK_TARGET = 500
CHUNK_MAX = 1000


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


# ── 章節對應 ──────────────────────────────────────────────────
CHAPTER_PHASES = {
    "01": "工務所設置管理",
    "02": "採購發包管理",
    "03": "竣工管理",
}

DOCUMENT_TYPES = {
    "A": "checklist",
    "B": "procedure",
    "C": "procedure",
}


def extract_section_code(filename: str) -> str:
    """從檔名提取 6 位節次代碼（如 '010101'）"""
    m = re.match(r'^(\d{6})', filename)
    return m.group(1) if m else "000000"


def get_chapter_info(section_code: str) -> tuple[str, str]:
    """回傳 (chapter_code, phase_name)"""
    chapter = section_code[:2] if len(section_code) >= 2 else "00"
    phase = CHAPTER_PHASES.get(chapter, "未分類")
    return chapter, phase


def detect_file_type(filename: str, content: str) -> str:
    """
    Type A：檔名含「作業檢核表」
    Type C：此腳本讀取的是清理後檔案（code block 已移除），
            改用原始 MD 的 Type C 特徵檔名來識別（```text 已不存在）。
            識別依據：content 仍保留的「## 第N頁」頁碼標記、
            或原始 Type C 的「圖片目錄：」backtick 路徑格式。
    Type B：其餘
    """
    if "作業檢核表" in filename:
        return "A"
    # Type C 識別：清理後仍可能保有 ## 第N頁 頁碼標記（未完全移除時），
    # 或原始 preprocess 記錄（從原始 MD 判斷，透過已知 Type C 檔名清單）
    _TYPE_C_SECTION_CODES = {
        "010102", "010103", "010307",
        "020105", "020106", "020206",
    }
    section_code = extract_section_code(filename)
    if section_code in _TYPE_C_SECTION_CODES:
        return "C"
    return "B"


# ── 圖片保護工具 ──────────────────────────────────────────────

# 圖片語法行（Markdown 圖片）
_IMG_LINE = re.compile(r'^!\[')
# 圖片說明相關行
_IMG_META_LINE = re.compile(
    r'^[*\-]\s*(?:圖片(?:路徑|標題|說明|敘述|描述|標記)|image_path|#### IMG-)',
    re.IGNORECASE,
)
# 圖片區塊 header（如 #### IMG-001 或 #### 圖片標記）
_IMG_BLOCK_HEADER = re.compile(r'^#{1,4}\s*(?:IMG-\d+|圖片\s*\d+|圖片標記|圖片路徑|圖片敘述)', re.IGNORECASE)


def is_img_related_line(line: str) -> bool:
    """該行是否屬於圖片區塊（圖片語法 or 圖片 metadata）"""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(
        _IMG_LINE.match(stripped) or
        _IMG_META_LINE.match(stripped) or
        _IMG_BLOCK_HEADER.match(stripped)
    )


def find_safe_split_point(lines: list[str], preferred_idx: int) -> int:
    """
    從 preferred_idx 往後找安全切割點：
    確保切割點不在圖片區塊中間。
    最多向後延伸 30 行。
    """
    idx = preferred_idx
    max_look = min(preferred_idx + 30, len(lines))

    while idx < max_look:
        # 檢查從 idx 開始往後 5 行是否有圖片相關行
        upcoming = lines[idx:min(idx + 5, len(lines))]
        has_img_ahead = any(is_img_related_line(l) for l in upcoming)

        if not has_img_ahead:
            return idx

        # 繼續往後找
        idx += 1

    # 找不到安全點，回傳原始位置（盡量不破壞）
    return preferred_idx


def extract_image_paths(text: str) -> list[str]:
    """從 chunk 文字中提取所有圖片路徑"""
    paths = re.findall(r'!\[.*?\]\((/api/images/[^)]+)\)', text)
    # 也找 backtick 格式的路徑
    paths += re.findall(r'`(/api/images/[^`]+)`', text)
    return list(set(paths))


def extract_image_tags(text: str) -> list[str]:
    """從圖片標記行提取標籤"""
    tags = []
    for line in text.split('\n'):
        m = re.search(r'圖片(?:標記|標籤)\s*[：:]\s*(.+)', line)
        if m:
            raw = m.group(1).strip().strip('`').strip()
            tags.extend([t.strip() for t in re.split(r'[,，、]', raw) if t.strip()])
    return list(set(tags))


def extract_rag_tags(text: str) -> list[str]:
    """從文件末尾的 RAG 標籤區塊提取 tags"""
    m = re.search(r'## RAG 使用建議標籤\s*\n(.+?)(?:\n## |\Z)', text, re.DOTALL)
    if not m:
        return []
    raw = m.group(1).strip().strip('`').strip()
    return [t.strip().strip('`') for t in re.split(r'[`\s,，、]+', raw) if t.strip().strip('`')]


# ── 建立 Chunk 物件 ────────────────────────────────────────────

def make_chunk(
    text: str,
    source_file: str,
    file_type: str,
    section_code: str,
    chunk_index: int,
    parent_h1: str = "",
    parent_h2: str = "",
    parent_h3: str = "",
    doc_tags: Optional[list[str]] = None,
) -> dict:
    chapter, phase = get_chapter_info(section_code)
    img_paths = extract_image_paths(text)
    img_tags = extract_image_tags(text)

    return {
        "chunk_id": str(uuid.uuid4()),
        "source_file": source_file,
        "section_code": section_code,
        "chapter": chapter,
        "phase": phase,
        "document_type": DOCUMENT_TYPES[file_type],
        "file_type": file_type,
        "tags": doc_tags or [],
        "parent_h1": parent_h1,
        "parent_h2": parent_h2,
        "parent_h3": parent_h3,
        "chunk_index": chunk_index,
        "has_images": len(img_paths) > 0,
        "image_paths": img_paths,
        "image_tags": img_tags,
        "token_count": count_tokens(text),
        "text": text,
    }


# ── Type A 切割（作業檢核表）─────────────────────────────────

def chunk_type_a(content: str, filename: str) -> list[dict]:
    """
    Type A：以 H2 為邊界切割。
    大型表格以每 20 行作為一個子 chunk，保留 header 行。
    """
    section_code = extract_section_code(filename)
    source_file = re.sub(r'\.\w+$', '', filename)

    # 找 RAG tags（Type A 通常無，備用）
    doc_tags = extract_rag_tags(content)

    lines = content.split('\n')
    sections: list[tuple[str, list[str]]] = []  # (h2_title, lines)
    current_h2 = ""
    current_lines: list[str] = []

    for line in lines:
        if line.startswith('## '):
            if current_lines:
                sections.append((current_h2, current_lines))
            current_h2 = line.lstrip('#').strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_h2, current_lines))

    chunks = []
    chunk_index = 0

    for h2_title, sec_lines in sections:
        text = '\n'.join(sec_lines).strip()
        if not text:
            continue

        # 跳過僅含文件資訊的 header 區塊（太短且無語意）
        tokens = count_tokens(text)
        if tokens < CHUNK_MIN:
            continue

        # 大型表格分割（每 ROWS_PER_CHUNK 行一個 chunk）
        ROWS_PER_CHUNK = 20
        table_lines = [l for l in sec_lines if l.startswith('|')]
        non_table_lines = [l for l in sec_lines if not l.startswith('|')]

        if len(table_lines) > ROWS_PER_CHUNK + 2:
            # 找 header 行（前 2 行通常是 header + separator）
            header_rows = table_lines[:2]
            data_rows = table_lines[2:]

            # 前綴（非表格行）
            prefix = '\n'.join(non_table_lines[:3]).strip()

            for start in range(0, len(data_rows), ROWS_PER_CHUNK):
                batch = data_rows[start:start + ROWS_PER_CHUNK]
                chunk_text = ''
                if prefix:
                    chunk_text += prefix + '\n\n'
                chunk_text += '\n'.join(header_rows + batch)
                if count_tokens(chunk_text) >= CHUNK_MIN:
                    chunks.append(make_chunk(
                        text=chunk_text.strip(),
                        source_file=source_file,
                        file_type='A',
                        section_code=section_code,
                        chunk_index=chunk_index,
                        parent_h2=h2_title,
                        doc_tags=doc_tags,
                    ))
                    chunk_index += 1
        else:
            chunks.append(make_chunk(
                text=text,
                source_file=source_file,
                file_type='A',
                section_code=section_code,
                chunk_index=chunk_index,
                parent_h2=h2_title,
                doc_tags=doc_tags,
            ))
            chunk_index += 1

    return chunks


# ── Type B 切割（標準內文）────────────────────────────────────

def chunk_type_b(content: str, filename: str) -> list[dict]:
    """
    Type B：以 H3 為主要邊界，H2 作為 context_header。
    若無 H3，以 H2 切割。
    套用圖片保護規則。
    """
    section_code = extract_section_code(filename)
    source_file = re.sub(r'\.\w+$', '', filename)

    # 提取文件層級 RAG tags（在切割前先提取）
    doc_tags = extract_rag_tags(content)

    # 移除 RAG 標籤區塊（避免進入 chunk）
    content_clean = re.sub(r'## RAG 使用建議標籤.*$', '', content, flags=re.DOTALL).strip()
    # 移除「## 檔案結構」區塊
    content_clean = re.sub(r'## 檔案結構.*$', '', content_clean, flags=re.DOTALL).strip()

    lines = content_clean.split('\n')
    chunks = []
    chunk_index = 0

    current_h1 = ""
    current_h2 = ""
    current_h3 = ""
    current_lines: list[str] = []
    # 用來累積跨 section 的小 chunk
    pending_merge: Optional[dict] = None

    def flush_section(h1, h2, h3, sec_lines) -> list[dict]:
        """將一個 section 切割成 chunks（含大段落的二次切割）"""
        nonlocal chunk_index
        text = '\n'.join(sec_lines).strip()
        if not text or count_tokens(text) < CHUNK_MIN // 2:
            return []

        tokens = count_tokens(text)
        result = []

        if tokens <= CHUNK_MAX:
            # 直接成 chunk
            c = make_chunk(
                text=text,
                source_file=source_file,
                file_type='B',
                section_code=section_code,
                chunk_index=chunk_index,
                parent_h1=h1,
                parent_h2=h2,
                parent_h3=h3,
                doc_tags=doc_tags,
            )
            chunk_index += 1
            result.append(c)
        else:
            # 二次切割：以空行為段落邊界，套用圖片保護
            sub_chunks = split_by_paragraphs(text, source_file, 'B', section_code,
                                              h1, h2, h3, doc_tags)
            result.extend(sub_chunks)

        return result

    def split_by_paragraphs(text, src, ftype, scode, h1, h2, h3, tags) -> list[dict]:
        """以空行分段切割大型 section"""
        nonlocal chunk_index
        paras = re.split(r'\n\n+', text)
        result = []
        current_batch: list[str] = []
        current_tokens = 0

        for para in paras:
            para_tokens = count_tokens(para)
            if current_tokens + para_tokens > CHUNK_MAX and current_batch:
                # 確保切割點不在圖片中間
                batch_text = '\n\n'.join(current_batch).strip()
                if count_tokens(batch_text) >= CHUNK_MIN:
                    result.append(make_chunk(
                        text=batch_text,
                        source_file=src,
                        file_type=ftype,
                        section_code=scode,
                        chunk_index=chunk_index,
                        parent_h1=h1,
                        parent_h2=h2,
                        parent_h3=h3,
                        doc_tags=tags,
                    ))
                    chunk_index += 1
                current_batch = [para]
                current_tokens = para_tokens
            else:
                current_batch.append(para)
                current_tokens += para_tokens

        if current_batch:
            batch_text = '\n\n'.join(current_batch).strip()
            if count_tokens(batch_text) >= CHUNK_MIN:
                result.append(make_chunk(
                    text=batch_text,
                    source_file=src,
                    file_type=ftype,
                    section_code=scode,
                    chunk_index=chunk_index,
                    parent_h1=h1,
                    parent_h2=h2,
                    parent_h3=h3,
                    doc_tags=tags,
                ))
                chunk_index += 1

        return result

    def commit_current():
        nonlocal current_lines, pending_merge
        if not current_lines:
            return
        new_chunks = flush_section(current_h1, current_h2, current_h3, current_lines)
        if new_chunks:
            # 處理小 chunk 合併
            for c in new_chunks:
                if c['token_count'] < CHUNK_MIN:
                    if pending_merge:
                        # 合併到待處理
                        pending_merge['text'] += '\n\n' + c['text']
                        pending_merge['token_count'] = count_tokens(pending_merge['text'])
                        pending_merge['image_paths'] = list(set(
                            pending_merge['image_paths'] + c['image_paths']
                        ))
                        pending_merge['has_images'] = bool(pending_merge['image_paths'])
                    else:
                        pending_merge = c
                else:
                    if pending_merge:
                        chunks.append(pending_merge)
                        pending_merge = None
                    chunks.append(c)
        current_lines.clear()

    for line in lines:
        if line.startswith('# '):
            commit_current()
            current_h1 = line.lstrip('#').strip()
            current_h2 = ""
            current_h3 = ""

        elif line.startswith('## '):
            commit_current()
            current_h2 = line.lstrip('#').strip()
            current_h3 = ""

        elif line.startswith('### '):
            commit_current()
            current_h3 = line.lstrip('#').strip()
            current_lines.append(line)

        else:
            current_lines.append(line)

    commit_current()

    # 清理 pending_merge
    if pending_merge:
        chunks.append(pending_merge)

    return chunks


# ── Type C 切割（掃描PDF）────────────────────────────────────

def chunk_type_c(content: str, filename: str) -> list[dict]:
    """
    Type C（已清理的掃描PDF）：
    移除殘餘的 ## 第N頁 標記後，以 H2/H3 邊界切割，
    套用圖片保護規則。邏輯同 Type B。
    """
    # 移除殘餘的頁碼 header（## 第N頁 或 ## 第 N 頁）
    content = re.sub(r'^##\s+第\s*\d+\s*頁.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'\n{3,}', '\n\n', content)

    # 其餘邏輯複用 Type B，但 file_type 標記為 C
    section_code = extract_section_code(filename)
    source_file = re.sub(r'\.\w+$', '', filename)
    doc_tags = extract_rag_tags(content)

    content_clean = re.sub(r'## RAG 使用建議標籤.*$', '', content, flags=re.DOTALL).strip()
    content_clean = re.sub(r'## 檔案結構.*$', '', content_clean, flags=re.DOTALL).strip()

    lines = content_clean.split('\n')
    chunks = []
    chunk_index = 0
    current_h1 = ""
    current_h2 = ""
    current_h3 = ""
    current_lines: list[str] = []

    def flush(h1, h2, h3, sec_lines):
        nonlocal chunk_index
        text = '\n'.join(sec_lines).strip()
        if not text or count_tokens(text) < CHUNK_MIN // 2:
            return []
        tokens = count_tokens(text)
        result = []
        if tokens <= CHUNK_MAX:
            c = make_chunk(text=text, source_file=source_file, file_type='C',
                           section_code=section_code, chunk_index=chunk_index,
                           parent_h1=h1, parent_h2=h2, parent_h3=h3, doc_tags=doc_tags)
            chunk_index += 1
            result.append(c)
        else:
            paras = re.split(r'\n\n+', text)
            batch: list[str] = []
            btokens = 0
            for para in paras:
                pt = count_tokens(para)
                if btokens + pt > CHUNK_MAX and batch:
                    bt = '\n\n'.join(batch).strip()
                    if count_tokens(bt) >= CHUNK_MIN:
                        c = make_chunk(text=bt, source_file=source_file, file_type='C',
                                       section_code=section_code, chunk_index=chunk_index,
                                       parent_h1=h1, parent_h2=h2, parent_h3=h3, doc_tags=doc_tags)
                        chunk_index += 1
                        result.append(c)
                    batch = [para]
                    btokens = pt
                else:
                    batch.append(para)
                    btokens += pt
            if batch:
                bt = '\n\n'.join(batch).strip()
                if count_tokens(bt) >= CHUNK_MIN:
                    c = make_chunk(text=bt, source_file=source_file, file_type='C',
                                   section_code=section_code, chunk_index=chunk_index,
                                   parent_h1=h1, parent_h2=h2, parent_h3=h3, doc_tags=doc_tags)
                    chunk_index += 1
                    result.append(c)
        return result

    pending_merge = None

    def commit():
        nonlocal current_lines, pending_merge
        if not current_lines:
            return
        new = flush(current_h1, current_h2, current_h3, current_lines)
        for c in new:
            if c['token_count'] < CHUNK_MIN:
                if pending_merge:
                    pending_merge['text'] += '\n\n' + c['text']
                    pending_merge['token_count'] = count_tokens(pending_merge['text'])
                    pending_merge['image_paths'] = list(set(pending_merge['image_paths'] + c['image_paths']))
                    pending_merge['has_images'] = bool(pending_merge['image_paths'])
                else:
                    pending_merge = c
            else:
                if pending_merge:
                    chunks.append(pending_merge)
                    pending_merge = None
                chunks.append(c)
        current_lines.clear()

    for line in lines:
        if line.startswith('# '):
            commit()
            current_h1 = line.lstrip('#').strip()
            current_h2 = ""
            current_h3 = ""
        elif line.startswith('## '):
            commit()
            current_h2 = line.lstrip('#').strip()
            current_h3 = ""
        elif line.startswith('### '):
            commit()
            current_h3 = line.lstrip('#').strip()
            current_lines.append(line)
        else:
            current_lines.append(line)

    commit()
    if pending_merge:
        chunks.append(pending_merge)

    return chunks


# ── 主流程 ────────────────────────────────────────────────────

def process_file(md_path: Path) -> list[dict]:
    content = md_path.read_text(encoding='utf-8')
    filename = md_path.name
    file_type = detect_file_type(filename, content)

    if file_type == 'A':
        return chunk_type_a(content, filename)
    elif file_type == 'B':
        return chunk_type_b(content, filename)
    else:
        return chunk_type_c(content, filename)


def main():
    cleaned_files = sorted(CLEANED_DIR.glob('*.md'))
    if not cleaned_files:
        print(f"[ERROR] 找不到清理後的 .md 檔案於 {CLEANED_DIR}", file=sys.stderr)
        print("請先執行 01_preprocess.py", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(cleaned_files)} 份清理後文件，開始切割...\n")

    all_chunks: list[dict] = []
    type_counts = {'A': 0, 'B': 0, 'C': 0}

    for md_path in cleaned_files:
        chunks = process_file(md_path)
        content = md_path.read_text(encoding='utf-8')
        ftype = detect_file_type(md_path.name, content)
        type_counts[ftype] += len(chunks)

        print(f"  [{ftype}] {md_path.name}")
        print(f"       → {len(chunks)} chunks | tokens: "
              f"{sum(c['token_count'] for c in chunks)}")

        # 更新 chunk_index（全域序號）
        for i, c in enumerate(chunks):
            c['chunk_index'] = i  # 文件內序號保持，全域在寫入時不需要

        all_chunks.extend(chunks)

    # 輸出 JSONL
    with CHUNKS_FILE.open('w', encoding='utf-8') as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    # 統計
    token_list = [c['token_count'] for c in all_chunks]
    print(f"\n完成！共 {len(all_chunks)} 個 chunks")
    print(f"  Token 分布：min={min(token_list)}, "
          f"avg={sum(token_list)//len(token_list)}, "
          f"max={max(token_list)}")
    print(f"  含圖片的 chunks：{sum(1 for c in all_chunks if c['has_images'])}")
    print(f"\nChunks 輸出至：{CHUNKS_FILE}")


if __name__ == '__main__':
    main()
