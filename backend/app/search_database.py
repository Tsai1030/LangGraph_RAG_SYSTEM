"""Second SQLAlchemy engine — dedicated to the SEARCH module's tables.

Why a separate engine + Base:
    SEARCH (price_history, csc_*, generation_runs) lives in its own
    SQLite file so RAG and SEARCH can be backed up / rolled back / queried
    independently. Mixing them into app.db would couple two unrelated
    schema-evolution cadences and inflate every backup.

    `SearchBase` MUST be distinct from `app.database.Base`. If the same
    declarative base were shared, `Base.metadata.create_all(rag_engine)`
    would try to create SEARCH tables in app.db (and vice-versa).

    Users do NOT belong here. SEARCH references users only by UUID
    string at the application layer — no cross-DB foreign keys.
"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_search_url = settings.search_async_database_url
_is_sqlite = "sqlite" in _search_url
_connect_args = {"check_same_thread": False} if _is_sqlite else {}


search_engine = create_async_engine(
    _search_url,
    echo=settings.app_env == "development",
    connect_args=_connect_args,
)


@event.listens_for(search_engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _) -> None:
    """Mirror app.database's pragmas — WAL for concurrent reads, FK on for
    integrity (even though SEARCH has no FKs today, this guards against
    a future model adding one and silently being ignored)."""
    if _is_sqlite:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SearchAsyncSessionLocal = async_sessionmaker(
    search_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class SearchBase(DeclarativeBase):
    """Declarative base for SEARCH tables only. Never inherit RAG models
    from this, and never inherit SEARCH models from app.database.Base."""

    pass


async def get_search_db():
    """FastAPI dependency yielding a SEARCH session.

    Use this in routers under app.modules.search.api — never mix with
    get_db() in the same transaction. A request that needs both DBs
    must commit each independently.
    """
    async with SearchAsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
