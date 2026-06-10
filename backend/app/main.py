import asyncio
import contextlib
import logging
import mimetypes
import os
import re
import sys
from contextlib import asynccontextmanager

# Windows-only: psycopg (used by langgraph-checkpoint-postgres) cannot
# run on the default ProactorEventLoop. Must be set BEFORE asyncio/
# uvicorn create the loop, so do it at the very top of main.py.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_app_logger = logging.getLogger("app")
_app_logger.setLevel(logging.INFO)
if not _app_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _app_logger.addHandler(_h)
    _app_logger.propagate = False

# pydantic_settings 讀取 .env 但不寫回 os.environ，LangChain 需要從 os.environ 讀取
from app.config import settings as _s
if _s.langchain_api_key:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", _s.langchain_tracing_v2)
    os.environ.setdefault("LANGCHAIN_API_KEY", _s.langchain_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", _s.langchain_project)

import aiosqlite
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from urllib.parse import quote

from app.config import settings
from app.api import admin, auth, conversations, chat, export
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.database import get_db
from app.graph.builder import build_graph
from app.models.user import User
from app.rag.form_lookup import get_form_path, list_all_forms
from app.services.conversation_service import get_conversation
from app.services.form_fill_writer import get_filled_path

# 已填寫檔名格式：<conversation_id>_<form_id>_<timestamp>.docx
# conversation_id 為標準 UUID（含連字號，無底線），所以以第一個 "_" 為分界即可取出
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

from pathlib import Path

def _resolve_chroma_path() -> str:
    if settings.chroma_active_version:
        return str(Path(settings.chroma_versions_path) / settings.chroma_active_version)
    return settings.chroma_persist_path


async def _bootstrap_initial_admin() -> None:
    """若 INITIAL_ADMIN_EMAIL 已設定且該 user 已存在但未為 admin，啟動時自動升級。
    user 不存在則只印 warning（等對方註冊後重啟才會升級）。"""
    if not settings.initial_admin_email:
        return

    from app.database import AsyncSessionLocal
    from app.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == settings.initial_admin_email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"[Bootstrap] INITIAL_ADMIN_EMAIL={settings.initial_admin_email} not registered yet — skipping admin promotion")
            return
        if user.role == "admin":
            print(f"[Bootstrap] {user.email} is already admin — no change")
            return
        user.role = "admin"
        await db.commit()
        print(f"[Bootstrap] Promoted {user.email} to admin")


async def _periodic_cleanup() -> None:
    """每日清理：上傳圖片（30 天）+ 產出表單檔（30 天）。

    取代原本「啟動時掃一次」的做法 — PM2 長駐不重啟時也能持續清理。
    迴圈先清再睡，保留原啟動掃描行為。best-effort：失敗只記 log，下一輪再試。
    """
    from app.services.form_fill_writer import cleanup_old_generated
    from app.services.image_store import cleanup_old_uploads

    while True:
        try:
            # 磁碟掃描走 thread，避免大量檔案時卡住 event loop
            removed_uploads = await asyncio.to_thread(cleanup_old_uploads)
            removed_generated = await asyncio.to_thread(cleanup_old_generated)
            if removed_uploads or removed_generated:
                _app_logger.info(
                    "[cleanup] removed %d old upload(s), %d old generated form(s)",
                    removed_uploads, removed_generated,
                )
        except Exception:
            _app_logger.exception("[cleanup] periodic cleanup failed")
        await asyncio.sleep(86400)


@asynccontextmanager
async def _make_checkpointer():
    """Yield a LangGraph checkpointer appropriate for the configured backend.

    Precedence:
        1. settings.langgraph_db_url  → AsyncPostgresSaver  (post-migration)
        2. else                       → AsyncSqliteSaver    (legacy fallback)
    """
    if settings.langgraph_db_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(settings.langgraph_db_url) as cp:
            yield cp
    else:
        async with aiosqlite.connect(settings.langgraph_db_path) as conn:
            yield AsyncSqliteSaver(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    應用程式生命週期管理：
    - Startup：建立 LangGraph checkpointer (PG or SQLite based on env)，
      編譯 graph，bootstrap admin
    - Shutdown：context manager 自動關閉 checkpointer / DB 連線
    """
    async with _make_checkpointer() as checkpointer:
        await checkpointer.setup()                   # 建立 checkpointer 所需 tables
        app.state.graph = build_graph(checkpointer=checkpointer)
        app.state.checkpointer = checkpointer        # 供 conversation 刪除時清 thread state

        print(f"[Startup] APP_ENV={settings.app_env}")
        print(f"[Startup] DATABASE_URL={settings.database_url}")
        if settings.langgraph_db_url:
            print(f"[Startup] LANGGRAPH backend = PostgreSQL ({settings.langgraph_db_url.split('@')[-1]})")
        else:
            print(f"[Startup] LANGGRAPH backend = SQLite ({settings.langgraph_db_path})")
        print(f"[Startup] CHROMA_ACTIVE_VERSION={settings.chroma_active_version or '(default)'}")
        print(f"[Startup] RESOLVED_CHROMA_PATH={_resolve_chroma_path()}")
        print(f"[Startup] LLM_MODEL={settings.llm_model}")
        print(f"[Startup] GRADER_MODEL={settings.grader_model}")
        print(f"[Startup] FORM_MODEL={settings.form_model}")
        print(f"[Startup] VISION_MODEL={settings.vision_model}")
        print(f"[Startup] AUDIO_MODEL={settings.audio_model}")
        print(f"[Startup] EMBEDDING_MODEL={settings.embedding_model}")

        await _bootstrap_initial_admin()

        # ─── 每日清理任務（上傳圖 + 產出表單；啟動即先掃一輪）───
        cleanup_task = asyncio.create_task(_periodic_cleanup())

        # ─── SEARCH module bootstrap ───
        # Side-effect imports:
        #   - app.modules.search triggers each @register decorator via the
        #     explicit adapter imports in its __init__.py.
        #   - app.modules.search.storage.models populates SearchBase.metadata
        #     with the tables create_all needs to know about below.
        from app.search_database import SearchAsyncSessionLocal, search_engine, SearchBase
        import app.modules.search  # noqa: F401 — register source adapters
        from app.modules.search.storage import models as _search_models  # noqa: F401
        from app.modules.search.storage import run_repo

        # create_all is a SAFETY NET for greenfield deploys. In prod the
        # tables already exist (created by scripts/migrate_search_db.py),
        # so this is a no-op. Without it, an empty search.db file would
        # silently 500 every /api/search/* request.
        #
        # metadata.create_all is sync — the run_sync wrapper hands it the
        # sync connection that the async engine pools internally.
        async with search_engine.begin() as conn:
            await conn.run_sync(SearchBase.metadata.create_all)

        # Reap any 'running' runs left behind by the previous process.
        # PM2 restart / dev reload / crash all kill background asyncio
        # tasks mid-run; without this sweep the frontend would poll those
        # rows forever.
        async with SearchAsyncSessionLocal() as db:
            reaped = await run_repo.reap_stranded(db)
            if reaped:
                print(f"[Startup] SEARCH reaped {reaped} stranded run(s) to 'failed'", flush=True)

        # flush=True so prints land in the PM2 / uvicorn log immediately;
        # python's default stdout is block-buffered when not on a TTY.
        print(f"[Startup] SEARCH_DB_PATH={settings.search_db_path}", flush=True)
        print(f"[Startup] SEARCH_ENGINE_URL={search_engine.url}", flush=True)

        try:
            yield
        finally:
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task
            await search_engine.dispose()
    # yield 結束（server 關閉）後，async with 自動關閉 conn


app = FastAPI(
    title="Construction RAG API",
    version="0.3.0",
    lifespan=lifespan,
)

# Rate limiting (slowapi) — must be wired before other middleware/routers
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# ─── SEARCH module routers ───
# Each router declares its own module-local prefix (e.g. "/search/generation",
# "/admin/search-csc"). main.py adds /api here exactly once so URLs end up as
# /api/search/... and /api/admin/search-*. The routers are split by surface
# (generation = user-facing; csc + usage = admin-only) to keep auth deps
# localised and avoid a giant grab-bag file.
from app.modules.search.api import csc as search_csc
from app.modules.search.api import generation as search_generation
from app.modules.search.api import usage as search_usage

app.include_router(search_generation.router, prefix="/api")
app.include_router(search_csc.router, prefix="/api")
app.include_router(search_usage.router, prefix="/api")

_img_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data_markdown", "img")
)
_IMG_BASE = Path(_img_dir).resolve()


def _contained_file(candidate: Path) -> Path | None:
    """resolve 後確認仍在 img/ 內且為檔案；否則 None。

    用 is_relative_to 而非字串 startswith — 字串比對會被同層的
    img_xxx 兄弟目錄與 .. 穿越繞過。
    """
    resolved = candidate.resolve()
    if resolved.is_relative_to(_IMG_BASE) and resolved.is_file():
        return resolved
    return None


def _resolve_kb_image(image_path: str) -> Path | None:
    """解析 KB 圖片路徑，支援兩種目錄結構：
    1. img/<folder>/<file>.png          （無括號，直接存取）
    2. img/<folder with date>/<folder>/<file>.png （有括號的父目錄，多一層）

    解析策略：先試直接路徑，找不到就在 img/ 下搜尋同名子目錄。
    不在 img/ 內（路徑穿越）或檔案不存在 → None。
    """
    if not _IMG_BASE.is_dir():
        return None

    # 1. 直接路徑（現有可運作的路徑）
    if found := _contained_file(_IMG_BASE / image_path):
        return found

    # 2. 搜尋：image_path = "010102工務所辦公室設置/017.png"
    #    → parts[0] = "010102工務所辦公室設置", filename = "017.png"
    parts = image_path.replace("\\", "/").split("/")
    if len(parts) >= 2:
        target_folder = parts[0]
        sub_path = "/".join(parts[1:])
        for entry in os.scandir(_IMG_BASE):
            if not entry.is_dir():
                continue
            # 找名稱以 target_folder 開頭的父目錄（含括號版本）
            if entry.name.startswith(target_folder):
                if found := _contained_file(Path(entry.path) / target_folder / sub_path):
                    return found
                # 也試不含 target_folder 中間層的路徑
                if found := _contained_file(Path(entry.path) / sub_path):
                    return found

    return None


@app.get("/api/images/{image_path:path}")
async def serve_image(
    image_path: str,
    current_user: User = Depends(get_current_user),
):
    """KB 圖片服務端點（聊天回覆中的知識庫附圖）。需登入 — 前端
    MessageBubble 對 /api/ 開頭的圖改用 AuthImage 帶 token 抓 blob。"""
    path = _resolve_kb_image(image_path)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Image not found: {image_path}")
    return FileResponse(str(path))


@app.get("/api/forms")
async def list_forms(current_user: User = Depends(get_current_user)):
    """列出所有靜態表單 metadata，供前端表單選單使用。"""
    return list_all_forms()


@app.get("/api/forms/{form_id}/download")
async def download_form(
    form_id: str,
    current_user: User = Depends(get_current_user),
):
    """下載靜態表單 .docx 檔案（空白模板）"""
    path = get_form_path(form_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Form not found: {form_id}")
    encoded_name = quote(path.name, safe="")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@app.get("/api/forms/filled/{token}")
async def download_filled_form(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下載 agent 已填寫的表單 .docx。

    權限：token 中的 conversation_id 必須屬於當前使用者；否則 404（避免洩露存在性）。
    """
    # 1. token 解析：conv_id 為第一個 '_' 之前的 UUID
    parts = token.split("_", 1)
    if len(parts) < 2 or not _UUID_RE.match(parts[0]):
        raise HTTPException(status_code=404, detail="Filled form not found")
    conv_id = parts[0]

    # 2. 所屬權驗證（get_conversation 失敗即 404）
    try:
        await get_conversation(db, conv_id, str(current_user.id))
    except HTTPException:
        # 對話不存在或不屬於使用者 → 統一回 404 不洩露細節
        raise HTTPException(status_code=404, detail="Filled form not found")

    # 3. 取檔，依副檔名選擇 mime type（同一 endpoint 服務 docx / xlsx / csv 三種）
    path = get_filled_path(token)
    if path is None:
        raise HTTPException(status_code=404, detail="Filled form not found")
    mime, _ = mimetypes.guess_type(path.name)
    if mime is None:
        mime = "application/octet-stream"
    encoded_name = quote(path.name, safe="")
    return FileResponse(
        str(path),
        media_type=mime,
        filename=path.name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}
