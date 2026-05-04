"""
form_lookup.py — 靜態表單 Registry 查詢工具

lookup_forms：以 query 比對 registry keywords 做「候選召回」。
最終是否真的下載靜態表，由 unified_intent 節點的 LLM 決定（不再由關鍵字直接決策）。

get_form_path：根據 form_id 取得實際檔案路徑（供下載端點使用）。
"""

from __future__ import annotations

import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent / "form_registry.json"
_FORMS_DIR = (
    Path(__file__).parent.parent.parent.parent / "data_markdown" / "form_data"
)

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
    僅作候選召回，不代表使用者真的要該表單；最終決策由 unified_intent 處理。
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


def get_form_path(form_id: str) -> Path | None:
    """根據 form_id 回傳實際檔案路徑，檔案不存在時回傳 None。"""
    for form in _load_registry():
        if form["form_id"] == form_id:
            path = _FORMS_DIR / form["file_name"]
            return path if path.exists() else None
    return None


def get_form_meta(form_id: str) -> dict | None:
    """根據 form_id 回傳 metadata（form_id / display_name / download_url），找不到回 None。"""
    for form in _load_registry():
        if form["form_id"] == form_id:
            return {
                "form_id": form["form_id"],
                "display_name": form["display_name"],
                "download_url": f"/api/forms/{form['form_id']}/download",
            }
    return None
