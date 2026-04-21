"""
context.py — Context 組裝節點

將 retrieved_chunks 組裝成 LLM 可使用的 context 字串。
同步節點，不呼叫 LLM。
"""

from __future__ import annotations

from app.graph.state import GraphState


def context_builder(state: GraphState) -> dict:
    """
    組裝 RAG context：
    - 為每個 chunk 加上來源標頭（source_file、chapter）
    - 若 chunk 有圖片，附加圖片標籤說明
    - 各 chunk 以分隔線隔開
    """
    chunks = state.get("retrieved_chunks", [])
    context_parts: list[str] = []

    for chunk in chunks:
        text = chunk.get("document", "")
        meta = chunk.get("metadata", {})

        # 來源標頭（幫助 LLM 理解資料來源）
        header_parts: list[str] = []
        if source := meta.get("source_file"):
            header_parts.append(f"【來源：{source}】")
        if h2 := meta.get("parent_h2"):
            header_parts.append(f"【章節：{h2}】")

        if header_parts:
            text = " ".join(header_parts) + "\n" + text

        # 若有圖片路徑，直接附加 Markdown 圖片語法讓 LLM 可直接引用
        if meta.get("has_images"):
            image_paths = meta.get("image_paths", [])
            image_tags = meta.get("image_tags", [])
            if isinstance(image_paths, list) and image_paths:
                img_lines: list[str] = []
                for i, path in enumerate(image_paths[:3]):  # 最多附加 3 張避免過長
                    if not path:
                        continue
                    alt = image_tags[i] if isinstance(image_tags, list) and i < len(image_tags) else "相關圖片"
                    img_lines.append(f"![{alt}]({path})")
                if img_lines:
                    text += "\n" + "\n".join(img_lines)

        context_parts.append(text)

    context = "\n\n---\n\n".join(context_parts) if context_parts else "（無相關文件）"

    return {"context": context}
