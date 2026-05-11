"""
registry.py — Prompt 註冊表與查找入口。

設計：
- _ACTIVE 是 single source of truth：node role → module path（dot 路徑相對於 app.prompts）。
- get_prompt(name) 從 _ACTIVE 取出對應 module，回傳該 module 的 PROMPT 字串。
- 結果 cache 在 _CACHE，避免每次 LLM call 都做 importlib。

未來擴充：
- 換版本：改 _ACTIVE 那一行 pointer（例 "intent.v1" → "intent.v2"）。
- A/B 灰度：把 _ACTIVE.get(name) 換成 callable，依 settings / random 動態決定。
- 依 model 切變體：在 _resolve() 內判斷 settings.grader_model 再選 module。
"""

from __future__ import annotations

from importlib import import_module

# ────────────────────────────────────────────────────────────────
# Active prompt registry
# Key   = role name (節點端使用此名稱呼叫 get_prompt)
# Value = module path 相對 app.prompts（不含 .py），module 必須有 PROMPT 常數
# ────────────────────────────────────────────────────────────────
# 注意：此 dict 在 Step 2 暫時為空，Step 3 逐節點搬遷時逐一填入。
_ACTIVE: dict[str, str] = {
    "compact":       "compact.summarize_v1",
    "source_filter": "source_filter.v1",
    "grader":                "grader.grade_v1",
    "rewriter":              "grader.rewriter_v1",
    "form_structurer":       "form_structurer.v1",
    "form_fill.collector":   "form_fill.collector_v1",
    "responder.qa":          "responder.qa_v1",
    "responder.static":      "responder.static_download_v1",
    "responder.fill_collect": "responder.fill_collect_v1",
    "responder.fill_done":   "responder.fill_done_v1",
    "responder.export_done": "responder.dynamic_export_done_v1",
    # 後續節點搬遷時會逐步補上：
    # "intent":                 "intent.v1",
}

_CACHE: dict[str, str] = {}


def _resolve(name: str) -> str:
    """Map role name → module path. 未來要灰度／by-model 切換在此擴充。"""
    if name not in _ACTIVE:
        raise KeyError(
            f"prompt not registered: {name!r}. "
            f"已註冊：{sorted(_ACTIVE) or '(empty)'}"
        )
    return _ACTIVE[name]


def get_prompt(name: str) -> str:
    """取得 prompt 字串。

    Args:
        name: registry key（如 "intent"、"responder.qa"）。

    Returns:
        該 prompt module 內的 PROMPT 字串。

    Raises:
        KeyError: name 未註冊。
        AttributeError: 目標 module 沒有 PROMPT 常數。
    """
    if name in _CACHE:
        return _CACHE[name]

    target = _resolve(name)
    module = import_module(f"app.prompts.{target}")
    prompt = getattr(module, "PROMPT")
    _CACHE[name] = prompt
    return prompt


def list_registered() -> dict[str, str]:
    """除錯／後台用：列出目前所有註冊的 (role → module path)。"""
    return dict(_ACTIVE)


def clear_cache() -> None:
    """測試用：清掉 import cache（registry 改動後重讀）。"""
    _CACHE.clear()
