"""
app.prompts — 集中管理所有 LLM prompt。

節點端使用方式：
    from app.prompts import get_prompt
    system_text = get_prompt("intent")

每個 prompt 由 registry._ACTIVE 對應到 app/prompts/<group>/<variant>.py 中的 PROMPT 常數。
要切版本就改 registry 一行 pointer；要做 A/B 就把 registry._resolve 改成可路由的 callable。
"""

from app.prompts.registry import get_prompt

__all__ = ["get_prompt"]
