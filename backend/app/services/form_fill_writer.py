"""
form_fill_writer.py — 將收集到的欄位值寫入 .docx 模板副本。

設計重點：
- 段落欄位：用 regex 取代 marker 後既有值（idempotent，重填會覆蓋而非追加）
- 表格欄位：直接覆寫 cell.text；checkbox 類型映射成 V / X 字元
- 不修改原模板，副本存到 GENERATED_DIR，filename 含 conversation_id 與 timestamp
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from docx import Document

from app.rag.form_lookup import get_form_path

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).parent.parent / "rag" / "form_schemas"
GENERATED_DIR = Path(__file__).parent.parent.parent / "data" / "generated_forms"

# checkbox 自然語言 → V / X
_AFFIRMATIVE = {
    "v", "✓", "✔", "○", "o", "yes", "y", "ok", "true", "1",
    "完成", "已完成", "做完", "已辦", "已做", "對", "是",
}
_NEGATIVE = {
    "x", "✗", "✘", "×", "no", "n", "false", "0",
    "未完成", "未辦", "沒做", "未做", "否", "錯",
}


# ──────────────────────────────────────────────────────────────────
# Schema 載入
# ──────────────────────────────────────────────────────────────────

def load_schema(form_id: str) -> dict[str, Any] | None:
    path = SCHEMAS_DIR / f"{form_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────
# 值正規化
# ──────────────────────────────────────────────────────────────────

def _normalize_value(value: Any, field_type: str) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if field_type == "checkbox_vx":
        low = text.lower()
        if low in _AFFIRMATIVE:
            return "V"
        if low in _NEGATIVE:
            return "X"
        # 含關鍵字判斷（例如「已完成」「未完成」）
        if any(k in text for k in ("完成", "已", "做")) and "未" not in text:
            return "V"
        if any(k in text for k in ("未", "沒", "尚未")):
            return "X"
        return text  # 不認得，原樣保留
    return text


# ──────────────────────────────────────────────────────────────────
# 段落填入：以 regex 取代 marker 後的既有值，達到 idempotent
# ──────────────────────────────────────────────────────────────────

def _fill_paragraphs(doc, schema: dict, collected: dict[str, str]) -> int:
    """
    將段落類型的欄位值寫入。同一段落內的多個 marker 一次處理完再 rewrite。
    """
    para_groups: dict[int, list[dict]] = defaultdict(list)
    for f in schema["fields"]:
        if f["loc"]["kind"] != "para":
            continue
        if f["key"] not in collected or collected[f["key"]] in (None, ""):
            continue
        para_groups[f["loc"]["para_idx"]].append(f)

    written = 0
    for para_idx, fields in para_groups.items():
        if para_idx >= len(doc.paragraphs):
            logger.warning("[form_fill] paragraph idx %d out of range", para_idx)
            continue
        para = doc.paragraphs[para_idx]
        text = para.text
        original = text
        for f in fields:
            marker = f["loc"]["marker"]
            value = _normalize_value(collected[f["key"]], f["type"])
            # marker 後吃掉到下一個 \t 或行尾的舊值，再寫入新值
            pattern = re.compile(re.escape(marker) + r"[^\t\n]*")
            new_text = pattern.sub(f"{marker} {value}", text, count=1)
            if new_text != text:
                text = new_text
                written += 1
        if text == original:
            continue
        # 重寫段落內容（保留第一個 run 的格式，其他清空）
        if not para.runs:
            para.add_run(text)
        else:
            para.runs[0].text = text
            for run in para.runs[1:]:
                run.text = ""
    return written


# ──────────────────────────────────────────────────────────────────
# 表格填入
# ──────────────────────────────────────────────────────────────────

def _fill_cells(doc, schema: dict, collected: dict[str, str]) -> int:
    written = 0
    for f in schema["fields"]:
        if f["loc"]["kind"] != "cell":
            continue
        if f["key"] not in collected or collected[f["key"]] in (None, ""):
            continue
        loc = f["loc"]
        try:
            table = doc.tables[loc["table_idx"]]
            cell = table.rows[loc["row"]].cells[loc["col"]]
        except (IndexError, KeyError):
            logger.warning("[form_fill] cell loc out of range: %s", loc)
            continue
        value = _normalize_value(collected[f["key"]], f["type"])
        cell.text = value
        written += 1
    return written


# ──────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────

def write_filled_docx(
    form_id: str,
    collected: dict[str, str],
    conversation_id: str,
) -> tuple[Path, int] | None:
    """
    開啟模板副本、寫入欄位、存到 GENERATED_DIR。
    回傳 (output_path, written_count) 或 None（找不到模板/schema）。
    """
    template_path = get_form_path(form_id)
    if template_path is None or not template_path.exists():
        logger.warning("[form_fill] template not found: %s", form_id)
        return None
    schema = load_schema(form_id)
    if schema is None:
        logger.warning("[form_fill] schema not found: %s", form_id)
        return None

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    doc = Document(str(template_path))
    written = _fill_paragraphs(doc, schema, collected) + _fill_cells(doc, schema, collected)

    out_name = f"{conversation_id}_{form_id}_{int(time.time())}.docx"
    out_path = GENERATED_DIR / out_name
    doc.save(str(out_path))
    logger.info("[form_fill] wrote %d fields to %s", written, out_path.name)
    return out_path, written


def get_filled_path(token: str) -> Path | None:
    """根據 token（filename）回傳 generated 檔案路徑。"""
    # 防護：不允許路徑分隔
    if "/" in token or "\\" in token or ".." in token:
        return None
    path = GENERATED_DIR / token
    return path if path.is_file() else None
