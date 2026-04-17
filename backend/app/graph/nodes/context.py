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

        # 若有圖片標籤，附加說明（提示 LLM 此處有相關圖示）
        if meta.get("has_images"):
            tags = meta.get("image_tags", [])
            if isinstance(tags, list) and tags:
                tag_str = ", ".join(str(t) for t in tags if t)
                if tag_str:
                    text += f"\n[相關圖示：{tag_str}]"

        context_parts.append(text)

    context = "\n\n---\n\n".join(context_parts) if context_parts else "（無相關文件）"

    return {"context": context}
