"""SEARCH SQLAlchemy models — placeholder until Phase 3.4.

Phase 3.4 will translate SEARCH's SQLModel tables (PriceHistory,
CscPriceState, CscAnnouncementMeta, GenerationRun) into async
SQLAlchemy declarative classes inheriting SearchBase. Field types,
column names, indexes MUST match search.db's existing schema exactly
(see scripts/migrate_search_db.py for the source-of-truth shape).

Until then this file is empty so app.modules.search.storage is
importable but the metadata is empty (Phase 2.5 wires lifespan but
omits create_all precisely because there's nothing to create yet).

Hard rule for Phase 3.4 onwards:
    No `relationship()` here. Async SQLAlchemy raises MissingGreenlet
    on implicit lazy-load. If you ever need a relation, eager-load
    explicitly via `select(...).options(selectinload(Model.relation))`
    in the repo layer; never let the ORM trigger an implicit load.
"""

from app.search_database import SearchBase  # noqa: F401 — re-export anchor

__all__: list[str] = []
