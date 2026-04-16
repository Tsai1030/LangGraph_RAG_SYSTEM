import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api import auth, conversations, chat, export


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="Construction RAG API",
    version="0.1.0",
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

# Static image serving (data_markdown/img/ → /api/images/)
# Path: backend/ → ../../data_markdown/img/
_img_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data_markdown", "img")
)
if os.path.isdir(_img_dir):
    app.mount("/api/images", StaticFiles(directory=_img_dir), name="images")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
