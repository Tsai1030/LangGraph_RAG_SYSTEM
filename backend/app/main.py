import os
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import settings
from app.api import auth, conversations, chat, export
from app.graph.builder import build_graph


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

# 靜態圖片服務（data_markdown/img/ → /api/images/）
# 路徑：backend/app/main.py → ../../data_markdown/img/
_img_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data_markdown", "img")
)
if os.path.isdir(_img_dir):
    app.mount("/api/images", StaticFiles(directory=_img_dir), name="images")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
