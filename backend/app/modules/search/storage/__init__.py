"""SEARCH module storage layer (async SQLAlchemy on search.db).

models.py — table definitions, all inheriting SearchBase.
*_repo.py — query/transaction helpers, accept AsyncSession.

Phase 3.4 will populate models.py. Until then this package is intentionally
empty so importing app.modules.search at startup is a cheap no-op.
"""
