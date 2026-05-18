"""SEARCH orchestrator smoke test — runs the LangGraph once and prints
what each source returned + writes a docx to data/search_outputs/.

Useful for verifying Phase 3 end-to-end without booting FastAPI.

Run:
    cd backend
    uv run python scripts/smoke_search_orchestrator.py 2026-05-04
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

# Make `app` importable when the script is invoked via `uv run python
# scripts/smoke_search_orchestrator.py` — uv doesn't add the script's
# parent to sys.path by default.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _force_utf8_stdout() -> None:
    """Windows console defaults to cp950; force utf-8 so Chinese prints
    don't blow up on the very thing we're trying to render."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]


async def main() -> int:
    _force_utf8_stdout()
    target = date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-05-04")
    print(f"Target date: {target.isoformat()}")
    print()

    # Triggers @register for all source adapters via the explicit imports
    # in app/modules/search/__init__.py
    import app.modules.search  # noqa: F401
    from app.modules.search.core.orchestrator import get_graph

    graph = get_graph()
    state = await graph.ainvoke({
        "run_id": -1,                       # not persisted
        "meeting_date": target,
        "fengxing_open_date": target,
        "started_by": "smoke",
        "internal_data": {
            "meeting_time": "17:00~17:30",
            "contract_remaining_tons": "57,198",
            "contract_usable_until": "116 年 1 月",
            "meeting_conclusion_last_week": "(測試)",
            "meeting_conclusion_this_week": "(測試)",
        },
        "retry_count": 0,
        "max_retries": 1,
    })

    print("Fetched results:")
    for r in state.get("validated", []):
        v = r.value if r.value is not None else "—"
        snippet = (r.raw_text or "")[:80].replace("\n", " ")
        print(f"  {r.slot_key:32s} = {v!s:>14}  [{r.confidence}]  {snippet}")

    print()
    print("LLM-generated paragraphs:")
    for key in (
        "intl_scrap_paragraph", "china_xiben_paragraph", "lme_copper_paragraph",
        "market_info_domestic", "market_info_china",
    ):
        text = state["slot_values"].get(key, "")
        print(f"\n--- {key} ---\n{text}")

    print()
    print(f"Output Word: {state.get('output_path')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
