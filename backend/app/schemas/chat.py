from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    image_ids: list[str] = []  # VLM：已上傳圖片的 id（POST /api/chat/upload 取得）；空 = 純文字
    document_ids: list[str] = []  # 已上傳文件的 id（POST /api/chat/upload-document 取得）
