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

    # OpenAI
    openai_api_key: str
    llm_model: str = "gpt-5.4"
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

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
