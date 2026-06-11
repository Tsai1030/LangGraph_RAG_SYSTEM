"""
audio_transcribe.py — 語音輸入（STT）轉錄服務。

方案 A：轉錄發生在進 graph 之前（/api/chat/transcribe 端點），graph / state 零改動。
前端錄音（MediaRecorder）→ POST 音訊 → 這裡用 get_llm("audio")（AUDIO_MODEL，
預設 Gemini 多模態）轉成文字 → 前端填回輸入框，使用者確認後才送出。

音訊 bytes 不落磁碟、不進 state/checkpoint——轉錄是一次性的，文字才是 query。
"""
from __future__ import annotations

import base64
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_llm

logger = logging.getLogger("app.audio")

# MediaRecorder 各瀏覽器產出：Chrome/Edge/Firefox → webm(opus)；Safari → mp4(aac)。
# 其餘為常見音訊格式（Gemini 官方支援 wav/mp3/aiff/aac/ogg/flac）。
ALLOWED_AUDIO_MIME = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/aac",
    "audio/flac",
}
MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB（約 10+ 分鐘 opus 錄音，遠超實際需求）

_SYSTEM = (
    "你是語音轉文字助手。請把使用者的語音逐字轉錄成文字（繁體中文為主，"
    "夾雜的英文/數字照原樣保留）。只輸出轉錄文字本身：不要加標題、引號、"
    "說明或評論；可加入適當標點符號。若音訊無語音內容，輸出空字串。"
)


async def transcribe_audio(data: bytes, mime: str) -> str:
    """把音訊 bytes 轉錄成文字。驗證失敗丟 ValueError（由 endpoint 轉 400）。"""
    mime = (mime or "").lower().split(";")[0].strip()  # 去掉 ";codecs=opus" 參數
    if mime not in ALLOWED_AUDIO_MIME:
        raise ValueError(f"不支援的音訊類型：{mime or 'unknown'}")
    if not data:
        raise ValueError("空音訊檔")
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError(f"音訊過大（{len(data)} bytes，上限 {MAX_AUDIO_BYTES}）")

    b64 = base64.b64encode(data).decode()
    llm = get_llm("audio", temperature=0)
    resp = await llm.ainvoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=[
            {"type": "text", "text": "請轉錄這段語音。"},
            {"type": "audio", "base64": b64, "mime_type": mime},
        ]),
    ])

    # .text 是 LangChain 跨 provider 統一文字 accessor（同 vision_intake 的取法）
    text = getattr(resp, "text", None) or (
        resp.content if isinstance(resp.content, str) else ""
    )
    text = text.strip()
    logger.info("[transcribe] %d bytes (%s) → %d 字", len(data), mime, len(text))
    return text
