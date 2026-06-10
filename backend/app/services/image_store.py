"""
image_store.py — VLM 圖片上傳的磁碟儲存與解析。

圖片 bytes 存磁碟（settings.upload_dir/{user_id}/{uuid}.{ext}）；graph state
只放路徑/id，base64 不進 checkpoint（計畫書 D3）。
"""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.services.upload_guard import read_limited, sniff_image_mime

# 允許的圖片 mime → 副檔名（Stage 0 已驗證 Gemini 讀 png；jpeg/webp 一併支援）
_ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _user_dir(user_id: str) -> Path:
    d = Path(settings.upload_dir) / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_upload(user_id: str, file: UploadFile) -> dict:
    """存一張上傳圖片，回傳 {image_id, mime_type}。

    驗證：client mime 先快篩 → 分塊讀（超限即斷）→ magic bytes 判實際格式
    （以 sniff 結果為準，不信任 client 宣告）。檔名用 server 端 uuid。
    驗證失敗丟 ValueError（由 endpoint 轉成 400）。
    """
    claimed = (file.content_type or "").lower()
    if claimed not in _ALLOWED_MIME:
        raise ValueError(f"不支援的圖片類型：{claimed or 'unknown'}（僅 png/jpeg/webp）")

    try:
        data = await read_limited(file, _MAX_BYTES)
    except ValueError as e:
        raise ValueError(f"圖片{e}") from e

    mime = sniff_image_mime(data)
    if mime is None or mime not in _ALLOWED_MIME:
        raise ValueError("圖片內容與允許格式不符（僅 png/jpeg/webp）")
    if mime != claimed:
        import logging
        logging.getLogger("app.upload").warning(
            "[save_upload] client 宣告 %s 但實際為 %s，以實際格式為準", claimed, mime
        )

    ext = _ALLOWED_MIME[mime]
    image_id = uuid.uuid4().hex
    (_user_dir(user_id) / f"{image_id}{ext}").write_bytes(data)
    return {"image_id": image_id, "mime_type": mime}


def resolve_image(user_id: str, image_id: str) -> dict | None:
    """把 (user_id, image_id) 解析回磁碟參照 {id, path, mime}；找不到回 None。

    安全：image_id 必須是 32 位純 hex（uuid4().hex），且只在該使用者目錄下找
    → 防 path traversal、防跨使用者引用。
    """
    if not (len(image_id) == 32 and all(c in "0123456789abcdef" for c in image_id)):
        return None
    udir = Path(settings.upload_dir) / user_id
    for mime, ext in _ALLOWED_MIME.items():
        p = udir / f"{image_id}{ext}"
        if p.is_file():
            return {"id": image_id, "path": str(p), "mime": mime}
    return None


def to_image_block(ref: dict) -> dict | None:
    """把磁碟圖片參照 {path, mime} 轉成 LLM 多模態 content block；讀檔失敗回 None。

    格式 = Stage 0 驗證過的 image_url data-url（格式 A）。vision_intake 與 responder
    共用此函式，確保多模態圖片格式單一來源（要換格式只改這裡）。
    """
    try:
        data = Path(ref["path"]).read_bytes()
    except OSError:
        return None
    b64 = base64.b64encode(data).decode()
    mime = ref.get("mime") or "image/png"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def cleanup_old_uploads(max_age_days: int = 30) -> int:
    """刪除超過 max_age_days 的上傳圖片（best-effort，回傳刪除數）。

    避免上傳目錄無限累積；啟動時掃一次即可（PM2 部署會在每次 deploy 重啟）。
    """
    root = Path(settings.upload_dir)
    if not root.is_dir():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed
