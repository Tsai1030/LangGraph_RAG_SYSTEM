"""
dynamic_form_export.py — 把動態 form_data 轉成 .xlsx / .csv 寫到 generated_forms/

複用既有 services/export_service.py 的 generate_excel / generate_csv（純函式產 bytes），
這裡多做一層：寫到磁碟 + 產生符合 download endpoint 規則的檔名。

下載路由共用 /api/forms/filled/{token}（既有靜態填寫檔下載端點），
驗權邏輯靠 token 開頭的 conversation_id（同既有靜態填寫機制）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal, Optional

from app.services.export_service import generate_csv, generate_excel
from app.services.form_fill_writer import GENERATED_DIR

logger = logging.getLogger(__name__)

ExportFormat = Literal["xlsx", "csv"]


def export_dynamic_form(
    form_data: dict,
    conversation_id: str,
    fmt: ExportFormat = "xlsx",
) -> Optional[dict]:
    """把 form_data 轉成檔案存到 GENERATED_DIR。

    Returns:
        {form_id, display_name, download_url} 或 None（form_data 不合法）
    """
    if not form_data or not form_data.get("columns"):
        logger.warning("[dynamic_form_export] form_data 不合法或缺 columns")
        return None
    if any(c in conversation_id for c in ("/", "\\", "..")):
        logger.warning("[dynamic_form_export] 拒絕路徑式 conversation_id: %r", conversation_id)
        return None

    title = form_data.get("title", "動態表單")

    if fmt == "csv":
        content = generate_csv(form_data)
        ext = "csv"
    else:
        content = generate_excel(form_data, title)
        ext = "xlsx"

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{conversation_id}_dyn_{int(time.time())}.{ext}"
    out_path = GENERATED_DIR / filename
    out_path.write_bytes(content)

    logger.info("[dynamic_form_export] wrote %s (%d bytes)", filename, len(content))

    return {
        "form_id": f"dyn_{ext}",
        "display_name": f"{title}（{ext.upper()}）",
        "download_url": f"/api/forms/filled/{filename}",
    }
