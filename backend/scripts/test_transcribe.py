"""一次性驗證 /chat/transcribe 用的 STT service（不啟動 server，直接呼叫 service）。

用法：uv run python scripts/test_transcribe.py <音檔路徑> [mime]
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.audio_transcribe import transcribe_audio


async def main():
    path = Path(sys.argv[1])
    mime = sys.argv[2] if len(sys.argv) > 2 else "audio/wav"
    data = path.read_bytes()
    text = await transcribe_audio(data, mime)
    print(f"--- transcript ({len(text)} chars) ---")
    print(text)


asyncio.run(main())
