"""SEARCH module — 鋼筋盤價助理.

Owns: weekly steel rebar pricing fetch + LangGraph orchestration + DOCX
rendering. Persists into search.db (NOT app.db). References RAG users
only by UUID string from app.models.user — no cross-DB foreign keys.

The explicit adapter imports below are load-bearing: each module's
@register decorator only fires when the module is actually imported.
SEARCH's original main.py listed them by hand for the same reason;
the package's sources/__init__.py only re-exports the base, so a bare
`import .sources` does NOT cascade.
"""

from .sources import fengxing, fengxing_finder, market_narrator, weekly_market  # noqa: F401
