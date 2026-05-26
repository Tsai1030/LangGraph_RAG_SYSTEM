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
    grader_model: str = "gpt-5.4-mini" 
    form_model: str = "gpt-5.4"
    embedding_model: str = "text-embedding-3-small"

    # Database (SQLite)
    database_url: str
    sync_database_url: str
    langgraph_db_path: str = "./langgraph.db"
    # If set (e.g. via env LANGGRAPH_DB_URL), use AsyncPostgresSaver
    # instead of AsyncSqliteSaver. Format:
    #   postgresql://user:pass@host:port/dbname
    langgraph_db_url: str | None = None

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

    # ─── Google OAuth ───
    # Web Application Client ID（從 Google Cloud Console → Credentials）。
    # 不需要 client secret — GIS ID-token flow 由前端拿 token、後端只負責驗證簽章。
    google_client_id: str = ""
    # 公司網域：只有此網域的 Google 帳號可登入/註冊。空字串 = 不限制（不建議用於 prod）。
    allowed_email_domain: str = ""
    # 是否允許新使用者用 email + 密碼註冊。false = 只能透過 Google 註冊。
    # 既有密碼帳號不受影響（仍可用 /auth/login 登入）。
    allow_password_register: bool = False

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

    # ─── SEARCH module (鋼筋盤價助理) ───
    # Separate SQLite file for SEARCH's tables (price_history, csc_*,
    # generation_runs). Users table stays in app.db — SEARCH references
    # users only by UUID string (no cross-DB FK).
    search_db_path: str = "./search.db"
    # If set (e.g. via env SEARCH_DATABASE_URL), overrides search_db_path
    # — used after PG migration.
    search_database_url: str | None = None
    # Template + output paths. Both relative to backend/ at runtime (cwd
    # when uvicorn starts). Kept as strings here, resolved to absolute
    # Path objects in the orchestrator so the template is independent of
    # the working directory the script was invoked from.
    search_template_path: str = "./templates/meeting_template.docx"
    search_output_dir: str = "./data/search_outputs"
    # steelnet.com.tw — source for 豐興 weekly opening + intl scrap paragraph.
    # Article body is behind member login.
    steelnet_user: str = ""
    steelnet_password: str = ""
    steelnet_base: str = "https://www.steelnet.com.tw"
    # 西本新幹線（steelx2.com）人民幣→新台幣換算比率，用於 §六.3 大陸方面段落
    # 的 NT$ 括號數字。範例 PDF 用的 ratio = 4.541；要更貼合實際匯率可改 .env
    # CNY_TO_TWD_RATE。
    cny_to_twd_rate: float = 4.541

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def search_async_database_url(self) -> str:
        """SQLAlchemy URL for the SEARCH database.

        Precedence:
            1. field search_database_url (set via env SEARCH_DATABASE_URL
               or .env line of the same name; pydantic-settings reads
               this at Settings init)
            2. fallback: build SQLite URL from search_db_path (legacy)
        """
        if self.search_database_url:
            return self.search_database_url
        path = self.search_db_path.lstrip("./").lstrip(".\\")
        return f"sqlite+aiosqlite:///{path}"


settings = Settings()
