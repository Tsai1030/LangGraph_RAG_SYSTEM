"""
form_lookup.py — 靜態表單 Registry 查詢工具

lookup_forms：比對 query 關鍵字，回傳匹配的表單 metadata。
get_form_path：根據 form_id 取得實際檔案路徑（供下載端點使用）。
"""

from __future__ import annotations

import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent / "form_registry.json"
_FORMS_DIR = (
    Path(__file__).parent.parent.parent.parent / "data_markdown" / "form_data"
)

# 明確索取的動詞（需搭配表單名詞才算 explicit）
_EXPLICIT_VERBS = ["下載", "給我", "我要", "取得", "請給", "幫我拿"]
_FORM_NOUNS = ["表單", "表格", "表", "檢核表", "申請表"]

_registry: list[dict] | None = None


def _load_registry() -> list[dict]:
    global _registry
    if _registry is None:
        with open(_REGISTRY_PATH, encoding="utf-8") as f:
            _registry = json.load(f)
    return _registry


def lookup_forms(query: str) -> list[dict]:
    """
    根據 query 比對 registry keywords，回傳匹配的表單 metadata list。
    每個 dict 含 form_id, display_name, download_url。
    """
    matched = []
    for form in _load_registry():
        if any(kw in query for kw in form["keywords"]):
            matched.append({
                "form_id": form["form_id"],
                "display_name": form["display_name"],
                "download_url": f"/api/forms/{form['form_id']}/download",
            })
    return matched


def is_explicit_form_request(query: str) -> bool:
    """
    判斷使用者是否明確索取表單檔案（動詞 + 表單名詞同時出現）。
    """
    has_verb = any(v in query for v in _EXPLICIT_VERBS)
    has_noun = any(n in query for n in _FORM_NOUNS)
    return has_verb and has_noun


def get_form_path(form_id: str) -> Path | None:
    """
    根據 form_id 回傳實際檔案路徑，檔案不存在時回傳 None。
    """
    for form in _load_registry():
        if form["form_id"] == form_id:
            path = _FORMS_DIR / form["file_name"]
            return path if path.exists() else None
    return None
