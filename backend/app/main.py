import logging
import os
from contextlib import asynccontextmanager

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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import settings
from app.api import auth, conversations, chat, export
from app.graph.builder import build_graph

from pathlib import Path

def _resolve_chroma_path() -> str:
    if settings.chroma_active_version:
        return str(Path(settings.chroma_versions_path) / settings.chroma_active_version)
    return settings.chroma_persist_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    應用程式生命週期管理：
    - Startup：開啟 aiosqlite 連線，初始化 AsyncSqliteSaver，編譯 LangGraph
    - Shutdown：aiosqlite 連線由 context manager 自動關閉
    """
    # aiosqlite connection 維持整個 server 生命週期
    async with aiosqlite.connect(settings.langgraph_db_path) as conn:
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()                   # 建立 langgraph.db 所需 tables
        app.state.graph = build_graph(checkpointer=checkpointer)

        print(f"[Startup] APP_ENV={settings.app_env}")
        print(f"[Startup] DATABASE_URL={settings.database_url}")
        print(f"[Startup] LANGGRAPH_DB_PATH={settings.langgraph_db_path}")
        print(f"[Startup] CHROMA_ACTIVE_VERSION={settings.chroma_active_version or '(default)'}")
        print(f"[Startup] RESOLVED_CHROMA_PATH={_resolve_chroma_path()}")
        print(f"[Startup] LLM_MODEL={settings.llm_model}")
        print(f"[Startup] GRADER_MODEL={settings.grader_model}")
        print(f"[Startup] FORM_MODEL={settings.form_model}")
        print(f"[Startup] EMBEDDING_MODEL={settings.embedding_model}")

        yield
    # yield 結束（server 關閉）後，async with 自動關閉 conn


app = FastAPI(
    title="Construction RAG API",
    version="0.3.0",
    lifespan=lifespan,
)

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

_img_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data_markdown", "img")
)


@app.get("/api/images/{image_path:path}")
async def serve_image(image_path: str):
    """
    圖片服務端點，支援兩種目錄結構：
    1. img/<folder>/<file>.png          （無括號，直接存取）
    2. img/<folder with date>/<folder>/<file>.png （有括號的父目錄，多一層）

    解析策略：先試直接路徑，找不到就在 img/ 下搜尋同名子目錄。
    """
    if not os.path.isdir(_img_dir):
        raise HTTPException(status_code=404, detail="Image directory not found")

    # 1. 直接路徑（現有可運作的路徑）
    direct = os.path.normpath(os.path.join(_img_dir, image_path))
    if direct.startswith(_img_dir) and os.path.isfile(direct):
        return FileResponse(direct)

    # 2. 搜尋：image_path = "010102工務所辦公室設置/017.png"
    #    → parts[0] = "010102工務所辦公室設置", filename = "017.png"
    parts = image_path.replace("\\", "/").split("/")
    if len(parts) >= 2:
        target_folder = parts[0]
        sub_path = "/".join(parts[1:])
        for entry in os.scandir(_img_dir):
            if not entry.is_dir():
                continue
            # 找名稱以 target_folder 開頭的父目錄（含括號版本）
            if entry.name.startswith(target_folder):
                candidate = os.path.normpath(
                    os.path.join(entry.path, target_folder, sub_path)
                )
                if candidate.startswith(_img_dir) and os.path.isfile(candidate):
                    return FileResponse(candidate)
                # 也試不含 target_folder 中間層的路徑
                candidate2 = os.path.normpath(
                    os.path.join(entry.path, sub_path)
                )
                if candidate2.startswith(_img_dir) and os.path.isfile(candidate2):
                    return FileResponse(candidate2)

    raise HTTPException(status_code=404, detail=f"Image not found: {image_path}")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
