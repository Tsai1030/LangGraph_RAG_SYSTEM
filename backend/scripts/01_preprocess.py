"""
01_preprocess.py — 前處理腳本

功能：
1. 掃描 data_markdown/*.md（51 份文件）
2. 識別文件類型 A / B / C
   - Type A：檔名含「作業檢核表」
   - Type C：內容含 ```text 的逐頁 code block
   - Type B：其餘（一般標準內文）
3. Type C：移除 ```text ... ``` code block（保留周圍內容）
4. 所有類型：正規化圖片引用
   - 將所有 data_markdown/img/ → /api/images/（包含 ![]() 和 backtick 路徑）
   - 對「只有路徑沒有 ![]()」的圖片區塊，補上 Markdown 圖片語法
5. 輸出清理後的 .md 至 scripts/output/cleaned/

執行方式：
    cd backend
    uv run python scripts/01_preprocess.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ── 路徑設定 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
DATA_ROOT = BACKEND_DIR.parent  # Desktop/data/
MD_DIR = DATA_ROOT / "data_markdown"
OUTPUT_DIR = SCRIPT_DIR / "output" / "cleaned"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── 型別偵測 ──────────────────────────────────────────────────

def detect_file_type(filename: str, content: str) -> str:
    """
    回傳 'A', 'B', 或 'C'
    - A: 作業檢核表（純表格）
    - C: 掃描 PDF 轉換（有逐頁 ```text code block）
    - B: 其餘標準內文
    """
    if "作業檢核表" in filename:
        return "A"
    if "```text" in content or "``` text" in content:
        return "C"
    return "B"


# ── 圖片路徑正規化 ─────────────────────────────────────────────

# 匹配 data_markdown/img/ 開頭的路徑（在 ![]() 或 backtick 中）
_PATH_PREFIX = r"data_markdown/img/"
_API_PREFIX = "/api/images/"


def _replace_img_path(match: re.Match) -> str:
    """把 data_markdown/img/... 換成 /api/images/..."""
    return match.group(0).replace(_PATH_PREFIX, _API_PREFIX)


def normalize_img_paths(text: str) -> str:
    """
    將所有 data_markdown/img/ 替換為 /api/images/
    涵蓋：
    - ![alt](data_markdown/img/folder/file.png)
    - `data_markdown/img/folder/file.png`
    - data_markdown/img/folder/file.png（裸路徑）
    """
    # 全域替換所有出現的路徑前綴
    return text.replace(_PATH_PREFIX, _API_PREFIX)


# ── 補充缺失的 Markdown 圖片語法 ──────────────────────────────

# 匹配各種「只有路徑沒有 ![]()」的圖片區塊
# 格式：「- 圖片路徑：`/api/images/...`」或「* 圖片路徑：`/api/images/...`」
_IMG_PATH_LINE = re.compile(
    r'^([*\-])\s*(?:圖片路徑|image_path)\s*[：:]\s*`(/api/images/[^`]+)`',
    re.MULTILINE,
)

# 匹配「#### IMG-NNN」區塊（Type C 的圖片索引區塊）
_IMG_BLOCK_SECTION = re.compile(
    r'^#{1,4}\s*IMG-\d+\s*$',
    re.MULTILINE | re.IGNORECASE,
)


def _find_preceding_markdown_img(text: str, match_start: int) -> bool:
    """
    檢查在 match_start 前 5 行內是否已有 ![...](...)
    """
    preceding = text[max(0, match_start - 400):match_start]
    # 找最後一個圖片語法的位置
    last_img = list(re.finditer(r'!\[.*?\]\(.*?\)', preceding))
    if not last_img:
        return False
    last_pos = last_img[-1].end()
    # 如果在前 400 字元末段，視為「已有」
    return (len(preceding) - last_pos) < 200


def add_missing_img_syntax(text: str) -> str:
    """
    對於「只有圖片路徑行，沒有前置 ![]()」的情況，
    在路徑行後面插入 Markdown 圖片語法。

    同時處理 IMG-NNN block 格式（Type C）。
    """
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # 偵測「圖片路徑」行（例：`- 圖片路徑：`/api/images/...`）
        m = _IMG_PATH_LINE.match(line)
        if m:
            img_path = m.group(2)  # /api/images/...
            filename = Path(img_path).stem  # 001, page-05, 流程圖_4_2 ...

            # 往上找說明文字（在同一區塊內的圖片敘述/說明行）
            alt_text = filename  # 預設用檔名
            for j in range(max(0, i - 5), i):
                prev = lines[j]
                if re.search(r'圖片(?:敘述|說明|描述|標題)\s*[：:]', prev):
                    desc = re.sub(r'^[*\-]\s*(?:圖片(?:敘述|說明|描述|標題))\s*[：:]\s*', '', prev).strip()
                    if desc:
                        alt_text = desc[:80]
                    break

            result.append(line)

            # 檢查接下來幾行是否已有 ![]()
            next_block = '\n'.join(lines[i + 1:i + 5])
            if f'!['  not in next_block or img_path not in next_block:
                result.append(f'\n![{alt_text}]({img_path})\n')
        else:
            result.append(line)

        i += 1

    return '\n'.join(result)


# ── Type C：移除逐頁 code block ────────────────────────────────

def remove_page_code_blocks(text: str) -> str:
    """
    移除 ```text ... ``` 區塊（通常是 PDF 轉換的頁碼 header）。
    保留區塊前後的其他內容。
    """
    # 移除 ```text\n...\n``` 區塊（跨行匹配）
    text = re.sub(
        r'```(?:text)?\n.*?```\n?',
        '',
        text,
        flags=re.DOTALL,
    )
    # 清理因刪除產生的多餘空行（最多保留 2 個連續空行）
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ── 移除重複的圖片索引區塊（Type C 文末）──────────────────────

def remove_duplicate_img_index(text: str) -> str:
    """
    移除 Type C 文末的「## 圖片索引」彙整區塊。
    這些圖片說明已在文內各頁出現過，移除避免重複 Embedding。

    偵測方式：以 `## 圖片索引` 或 `## 8. 圖片索引` 作為分隔點，
    若在文件最後 30% 位置，則截斷。
    """
    # 找 ## 圖片索引（可能含數字編號）
    pattern = re.compile(r'^#{1,3}\s*\d*\.?\s*圖片索引\s*$', re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return text

    # 取最後一個匹配
    last_match = matches[-1]
    # 只有在文件最後 40% 才截斷（避免誤刪）
    if last_match.start() > len(text) * 0.6:
        return text[:last_match.start()].rstrip() + '\n'
    return text


# ── 主流程 ────────────────────────────────────────────────────

def preprocess_file(md_path: Path) -> dict:
    """
    前處理單一 .md 檔，回傳處理摘要。
    """
    content = md_path.read_text(encoding='utf-8')
    file_type = detect_file_type(md_path.name, content)

    original_len = len(content)
    steps = []

    # Step 1：Type C 移除逐頁 code block
    if file_type == 'C':
        content = remove_page_code_blocks(content)
        steps.append('removed_code_blocks')

    # Step 2：正規化圖片路徑
    content = normalize_img_paths(content)
    steps.append('normalized_img_paths')

    # Step 3：補充缺失的 Markdown 圖片語法（主要針對 Type C/B 的路徑型圖片）
    content = add_missing_img_syntax(content)
    steps.append('added_missing_img_syntax')

    # Step 4：移除 Type C 文末重複的圖片索引彙整
    if file_type in ('B', 'C'):
        content = remove_duplicate_img_index(content)
        steps.append('removed_img_index_section')

    # 輸出
    out_path = OUTPUT_DIR / md_path.name
    out_path.write_text(content, encoding='utf-8')

    return {
        'file': md_path.name,
        'type': file_type,
        'original_chars': original_len,
        'cleaned_chars': len(content),
        'steps': steps,
    }


def main():
    md_files = sorted(MD_DIR.glob('*.md'))
    if not md_files:
        print(f"[ERROR] 找不到 .md 檔案於 {MD_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(md_files)} 份 Markdown 文件，開始前處理...\n")

    type_counts = {'A': 0, 'B': 0, 'C': 0}
    results = []

    for md_path in md_files:
        result = preprocess_file(md_path)
        results.append(result)
        type_counts[result['type']] += 1
        print(f"  [{result['type']}] {result['file']}")
        print(f"       {result['original_chars']:,} → {result['cleaned_chars']:,} chars | steps: {', '.join(result['steps'])}")

    print(f"\n完成！")
    print(f"  Type A (作業檢核表): {type_counts['A']} 份")
    print(f"  Type B (標準內文):   {type_counts['B']} 份")
    print(f"  Type C (掃描PDF):   {type_counts['C']} 份")
    print(f"\n清理後的檔案輸出至：{OUTPUT_DIR}")


if __name__ == '__main__':
    main()
