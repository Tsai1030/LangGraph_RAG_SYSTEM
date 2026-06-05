from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    image_ids: list[str] = []  # VLM：已上傳圖片的 id（POST /api/chat/upload 取得）；空 = 純文字
