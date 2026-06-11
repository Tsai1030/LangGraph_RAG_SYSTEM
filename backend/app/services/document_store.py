"""
document_store.py — 聊天文件上傳（PDF/DOCX/PPTX）的儲存、解析與索引。

流程（在 upload endpoint 內同步完成，endpoint 回傳即代表可檢索）：
  驗證 mime / 大小 / magic bytes → 存磁碟（settings.upload_dir/{user_id}/）
  → markitdown 轉 Markdown → chunk → embed 進對話專屬 session collection。

原始檔名存在 {document_id}{ext}.name sidecar（檔名本身用 server 端 uuid，
不信任 client 檔名落磁碟路徑）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.rag.doc_chunker import chunk_markdown
from app.rag.session_store import add_chunks
from app.services.upload_guard import read_limited, sniff_document_kind

logger = logging.getLogger("app.upload")

_ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}
_EXT_KIND = {".pdf": "pdf", ".docx": "zip", ".pptx": "zip"}
_MAX_BYTES = 20 * 1024 * 1024  # 20 MB
_MIN_TEXT_CHARS = 50  # 轉出文字低於此值視為掃描影像檔 / 空文件

# markitdown 初始化會載入 magika 模型，lazy singleton 避免重複成本
_markitdown = None


def _get_markitdown():
    global _markitdown
    if _markitdown is None:
        from markitdown import MarkItDown
        _markitdown = MarkItDown()
    return _markitdown


def _user_dir(user_id: str) -> Path:
    d = Path(settings.upload_dir) / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_document_upload(
    user_id: str,
    conversation_id: str,
    file: UploadFile,
) -> dict:
    """存上傳文件並建立對話專屬索引，回傳 {document_id, filename, chunk_count}。

    驗證失敗 / 無法擷取文字丟 ValueError（由 endpoint 轉 400）。
    """
    claimed = (file.content_type or "").lower()
    if claimed not in _ALLOWED_MIME:
        raise ValueError(
            f"不支援的文件類型：{claimed or 'unknown'}（僅 PDF / Word docx / PowerPoint pptx）"
        )
    ext = _ALLOWED_MIME[claimed]

    try:
        data = await read_limited(file, _MAX_BYTES)
    except ValueError as e:
        raise ValueError(f"文件{e}") from e

    if sniff_document_kind(data) != _EXT_KIND[ext]:
        raise ValueError("文件內容與宣告格式不符（僅 PDF / docx / pptx）")

    document_id = uuid.uuid4().hex
    filename = file.filename or f"{document_id}{ext}"
    path = _user_dir(user_id) / f"{document_id}{ext}"
    path.write_bytes(data)

    try:
        result = await asyncio.to_thread(_get_markitdown().convert, str(path))
        md_text = (result.text_content or "").strip()
    except Exception as e:
        path.unlink(missing_ok=True)
        logger.warning("[save_document_upload] markitdown 解析失敗 file=%s", filename, exc_info=True)
        raise ValueError("文件解析失敗，請確認檔案未損毀且格式正確") from e

    if len(md_text) < _MIN_TEXT_CHARS:
        path.unlink(missing_ok=True)
        raise ValueError(
            "文件無法擷取文字（可能為掃描影像檔），請改上傳文字版，或將內容截圖改用圖片上傳"
        )

    chunks = chunk_markdown(md_text, source_file=filename)
    chunk_count = await add_chunks(conversation_id, chunks, document_id)

    # sidecar 存原始檔名（resolve_document / 前端附件顯示用）
    path.with_name(path.name + ".name").write_text(filename, encoding="utf-8")

    logger.info(
        "[save_document_upload] user=%s conv=%s doc=%s file=%s → %d chunks",
        user_id, conversation_id, document_id, filename, chunk_count,
    )
    return {"document_id": document_id, "filename": filename, "chunk_count": chunk_count}


def resolve_document(user_id: str, document_id: str) -> dict | None:
    """把 (user_id, document_id) 解析回 {id, path, filename}；找不到回 None。

    安全：document_id 必須是 32 位純 hex（uuid4().hex），且只在該使用者
    目錄下找 → 防 path traversal、防跨使用者引用（同 resolve_image）。
    """
    if not (len(document_id) == 32 and all(c in "0123456789abcdef" for c in document_id)):
        return None
    udir = Path(settings.upload_dir) / user_id
    for ext in _ALLOWED_MIME.values():
        p = udir / f"{document_id}{ext}"
        if p.is_file():
            name_file = p.with_name(p.name + ".name")
            try:
                filename = name_file.read_text(encoding="utf-8").strip()
            except OSError:
                filename = p.name
            return {
                "id": document_id,
                "path": str(p),
                "filename": filename,
                "size": p.stat().st_size,
            }
    return None
