"""
upload_guard.py — 上傳檔案的共用防護：分塊讀取限制大小 + magic bytes 驗證。

設計原則：
- read_limited：邊讀邊累計，超限立即中止 — 不再「整檔進記憶體後才檢查」，
  避免大檔 × 併發造成的記憶體放大。
- sniff_image_mime：圖片以檔頭 magic bytes 判型（client 的 content_type 可偽造）。
- sniff_audio_ok：音訊 container 變異太多（webm/mp4 codec 組合），只做輕量
  檢查供記 log 警告，不做硬性阻擋。
"""
from __future__ import annotations

from fastapi import UploadFile

_CHUNK = 1024 * 1024  # 1 MB


async def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """分塊讀取上傳檔，超過 max_bytes 立即丟 ValueError（由 endpoint 轉 400）。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"檔案過大（上限 {max_bytes} bytes）")
        chunks.append(chunk)
    if total == 0:
        raise ValueError("空檔案")
    return b"".join(chunks)


def sniff_image_mime(data: bytes) -> str | None:
    """以 magic bytes 判斷圖片實際格式，回傳 canonical mime；非支援格式回 None。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_document_kind(data: bytes) -> str | None:
    """以 magic bytes 判斷文件容器類型：'pdf'（%PDF-）/ 'zip'（docx/pptx 皆為
    OOXML zip）/ None。zip 內容是 docx 還是 pptx 交由 markitdown 解析時確認
    （宣告與內容不符會解析失敗）。"""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    return None


def sniff_audio_ok(data: bytes, mime: str) -> bool:
    """輕量檢查音訊檔頭是否像合法 container。

    僅供記 log 警告用（回傳 False 不代表一定是惡意檔，codec/container
    組合太多）；硬性防護仍靠 mime allowlist + 大小上限 + Gemini 端解析失敗。
    """
    if len(data) < 12:
        return False
    return (
        data[:4] == b"\x1aE\xdf\xa3"            # EBML（webm/mkv）
        or data[4:8] == b"ftyp"                  # mp4/m4a
        or (data[:4] == b"RIFF" and data[8:12] == b"WAVE")  # wav
        or data[:3] == b"ID3"                    # mp3（含 ID3 tag）
        or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")  # mp3 frame sync
        or data[:4] == b"OggS"                   # ogg
        or data[:4] == b"fLaC"                   # flac
    )
