"""SEARCH module — 鋼筋盤價助理.

Owns: weekly steel rebar pricing fetch + LangGraph orchestration + DOCX
rendering. Persists into search.db (NOT app.db). References RAG users
only by UUID string from app.models.user — no cross-DB foreign keys.

Phase 3 will wire up `from .sources import fengxing, market_narrator,
weekly_market` here so the @register decorators fire at import time.
Leave that empty until those modules land.
"""
