from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# data/.env is one level up from backend/
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI # .env 修改為主
    openai_api_key: str
    llm_model: str = "gpt-5.4"
    grader_model: str = "gpt-5.4" 
    form_model: str = "gpt-5.4"
    embedding_model: str = "text-embedding-3-small"

    # Database (SQLite)
    database_url: str
    sync_database_url: str
    langgraph_db_path: str = "./langgraph.db"

    # JWT
    secret_key: str
    access_token_expire_minutes: int = 120
    refresh_token_expire_days: int = 7

    # ChromaDB
    chroma_persist_path: str = "./chroma_db"
    chroma_versions_path: str = "./chroma_versions"  # 版本化 ChromaDB 的根目錄
    chroma_active_version: str = ""  # 留空 = 使用 chroma_persist_path；設為 "v1" 等使用版本化路徑

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"  # 用於組 password reset 連結

    # Admin Bootstrap
    initial_admin_email: str = ""

    # SMTP (for password reset email)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = ""

    # LangSmith (optional)
    langchain_tracing_v2: str = "false"
    langchain_api_key: str = ""
    langchain_project: str = "construction-rag"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
