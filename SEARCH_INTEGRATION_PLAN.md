# 鋼筋盤價助理 (SEARCH) 整合進 RAG 系統 — 詳細計畫書

> 版本：v1.0 | 日期：2026-05-18
> 目標：把 `C:\Users\226376\Desktop\SEARCH` 整套搬進 `C:\Users\226376\Desktop\data`，當作 RAG 系統的一個子模組。前端透過 sidebar 一個新 tab 進入，後端共用同一個 FastAPI 進程；JWT 共用（只一次登入），SEARCH 自己的資料另存獨立 SQLite。

---

## 0. 開工前的環境守則（重要）

### 0.1 RAG 系統正在生產（不能中斷）

- `C:\Users\226376\Desktop\data` 目前**正在線上服務**：PM2 跑 backend:8000 + frontend:3000，Caddy :9000 → Tailscale Funnel → `https://kccc3798.tail138ec9.ts.net`
- **絕對不可以**直接在這個資料夾改檔（會觸發 Next.js 熱重載、可能讓使用者看到半成品 / 短暫 5xx）
- **必須使用 git worktree** 把整合工作隔離出去

### 0.2 Worktree 設定（動工時才建）

當決定要開始實作時，用以下指令把整合工作切到獨立目錄：

```bash
# 在 data repo 內執行（注意：當前分支 feat/tailscale-funnel-expose 有未 commit 的修改
# — 是否要先 commit 或 stash 由使用者決定，worktree 只繼承已 commit 的內容）
cd C:\Users\226376\Desktop\data
git worktree add -b feat/search-module C:\Users\226376\Desktop\data-search-module
```

- **Worktree 路徑**：`C:\Users\226376\Desktop\data-search-module`（跟 data 同層 sibling）
- **分支名**：`feat/search-module`
- **工作流程**：所有 Phase 1~5 的 code change 都在 worktree 內進行；data/ 主 checkout 完全不碰
- **驗證**：在 worktree 內可以另開 backend:8002 + frontend:3001 跑開發版（不要佔 prod 用的 8000/3000 port）
- **完工**：所有 Phase 通過後，把 `feat/search-module` 合併回 `master`（或當前 prod 分支），主 checkout `git pull` 拿到變更，PM2 restart 一次

### 0.3 SEARCH 資料夾版本備份（動工前要做）

SEARCH 不需要 worktree（不會在它上面繼續開發），但要做版本備份避免意外：

```bash
# 1) Git tag — 標一個 archive 點，之後永遠 checkout 得回來
cd C:\Users\226376\Desktop\SEARCH
git tag archive/pre-rag-integration-20260518 -m "Snapshot before SEARCH is merged into RAG as a module"

# 2) 整資料夾複製 — 包含 .env / .venv / node_modules 等非 git 追蹤檔案
xcopy /E /I /H "C:\Users\226376\Desktop\SEARCH" "C:\Users\226376\Desktop\SEARCH.archive-20260518"
```

- Git tag 是「程式碼層」的還原點
- xcopy 出來的副本是「整個執行環境」的還原點（包含 .env 內的 STEELNET 帳密、訓練好的 .venv 等）
- 整合完成、新系統穩定執行兩週後，才考慮把 SEARCH 本體刪除

### 0.4 PM2 / Caddy 完全不動

整個整合過程中：
- `ecosystem.config.js` 不改
- `C:\caddy\Caddyfile` 不改
- `start-system.bat` 不改
- 唯一動到 prod 環境的時機：merge PR 後 `pm2 restart all` 一次

---

## 1. 設計總綱

### 1.1 命名約定（全程使用）

| 概念 | 命名 |
|---|---|
| 子模組 Python 路徑 | `app.modules.search` |
| URL 前綴（後端） | `/api/search/*` |
| URL 前綴（前端） | `/search/*`、admin 部分 `/admin/search-*` |
| 第二個 DB 檔名 | `backend/search.db` |
| 權限欄位 | `users.search_enabled: bool` |
| 模組顯示名 | 「鋼筋盤價助理」 |
| 整合分支 | `feat/search-module` |
| Worktree 路徑 | `C:\Users\226376\Desktop\data-search-module` |

### 1.2 最終目錄結構（目標）

```
data/
├── backend/
│   ├── app/
│   │   ├── main.py                ← 多 include 一個 router
│   │   ├── database.py            ← 不變 (app.db, async)
│   │   ├── search_database.py     ← 新增 (search.db, async, 獨立 engine)
│   │   ├── models/user.py         ← 加 search_enabled 欄位
│   │   ├── api/admin.py           ← 加 search 權限 toggle endpoint
│   │   ├── core/dependencies.py   ← 加 require_search_permission
│   │   └── modules/
│   │       └── search/
│   │           ├── __init__.py
│   │           ├── api/
│   │           │   ├── generation.py    (prefix /api/search/generation)
│   │           │   ├── csc.py           (prefix /api/admin/search-csc)
│   │           │   └── usage.py         (prefix /api/admin/search-usage)
│   │           ├── core/
│   │           │   ├── orchestrator.py  (LangGraph，幾乎不動)
│   │           │   ├── slot_schema.py
│   │           │   ├── graph_state.py
│   │           │   ├── dates.py
│   │           │   └── csc_products.py
│   │           ├── sources/             (fengxing, weekly_market, …)
│   │           ├── llm/                 (openai_client)
│   │           ├── output/              (docx_renderer)
│   │           └── storage/
│   │               ├── models.py        (async SQLAlchemy, 指向 search.db)
│   │               ├── history_repo.py
│   │               ├── csc_repo.py
│   │               └── run_repo.py
│   ├── scripts/
│   │   └── migrate_search_db.py    ← 一次性，把 SEARCH/backend/data/app.db 改造成 search.db
│   ├── templates/
│   │   └── meeting_template.docx    ← 從 SEARCH/backend/templates 搬來
│   ├── app.db                       ← 既有
│   ├── langgraph.db                 ← 既有
│   └── search.db                    ← 新增（migration 跑完後產生）
│
└── frontend/
    ├── app/
    │   └── (app)/
    │       ├── admin/
    │       │   ├── search-csc/page.tsx       ← SEARCH 的 CSC 維護
    │       │   └── search-usage/page.tsx     ← SEARCH 的 usage 統計
    │       └── search/
    │           ├── layout.tsx
    │           ├── generate/page.tsx
    │           └── no-access/page.tsx
    ├── components/
    │   ├── layout/Sidebar.tsx        ← 加一個 "鋼筋盤價助理" 入口
    │   └── search/
    │       ├── generate-view.tsx
    │       ├── loading-overlay.tsx
    │       ├── stepper.tsx
    │       └── csc-admin-view.tsx
    └── lib/
        └── search/
            └── types.ts              ← SEARCH 專用 DTO type
```

### 1.3 模組邊界（為了可維護性，絕對不能跨）

- `app/modules/search/**` 只能 import：
  - `app.modules.search.*`（自己內部）
  - `app.models.user`、`app.core.dependencies`、`app.core.security`、`app.search_database`、`app.config`（共用基礎設施）
- `app/modules/search/**` **禁止 import**：
  - `app.models.conversation/message/summary`
  - `app.rag.*`、`app.graph.*`
  - `app.api.{chat,conversations,export}`
- `app/**`（非 search）**禁止 import** `app.modules.search.*`
- 兩邊只透過 `user_id (UUID 字串)` 溝通，不互相 join

> **為什麼這條重要**：未來如果決定把 SEARCH 真的拆成獨立服務，這條邊界讓重構成本只剩搬檔案。

### 1.4 已敲定的設計決策（對話結果）

| 決策 | 結論 |
|---|---|
| 資料夾結構 | 合併進 `data/` 當子模組 |
| DB 切法 | 另開 `search.db`，users 表只在 `app.db` |
| ORM 風格 | 全改 async SQLAlchemy（跟 RAG 對齊） |
| 權限欄位 | 單一布林 `search_enabled` |
| Admin 頁面位置 | 進 RAG admin 區（`/admin/search-csc`、`/admin/search-usage`） |
| user 識別 | SEARCH 內部存 `user_id` (UUID 字串) |
| 既有 SEARCH `app.db` 處理 | 寫一次性 migration script 轉成 `search.db`；原檔不動 |
| JWT 共用 | SEARCH 不再簽 token，完全用 RAG 既有 SECRET_KEY；`.env` 殘留 `JWT_SHARED_SECRET` / `SEARCH_SESSION_SECRET` / `RAG_USERS_DB_PATH` 全部刪 |

---

## Phase 0 — 準備工作（不寫程式碼）

| 步驟 | 動作 | 檔案 | 完成驗收 |
|---|---|---|---|
| 0.1 | 確認 data 主 checkout 乾淨（或先 commit/stash），SEARCH 也是 | git | `git status` 在兩邊都乾淨或已 stash |
| 0.2 | SEARCH 打 git tag `archive/pre-rag-integration-20260518` | SEARCH/.git | `git tag -l "archive/*"` 看得到 |
| 0.3 | xcopy SEARCH 整個資料夾到 `SEARCH.archive-20260518` | 檔案 | 副本資料夾存在且可開 |
| 0.4 | 在 data 開 worktree `feat/search-module` → `data-search-module/` | git | `git worktree list` 看得到兩個 entry |
| 0.5 | 在 worktree 內把 SEARCH 的 `templates/meeting_template.docx` 複製到 `data-search-module/backend/templates/` | 檔案 | 檔案在位 |
| 0.6 | 在 worktree 內準備 `data/.env`：新增 `STEELNET_USER`、`STEELNET_PASSWORD`、`STEELNET_BASE`、`SEARCH_DB_PATH=./search.db`；不要動既有任何 RAG 變數 | `.env` | `python -c "from app.config import settings; print(settings.openai_api_key[:10])"` 沒錯 |

**依賴**：無。
**為什麼先做**：把所有「來自外部的東西」先就位，之後每個 Phase 都是純程式碼工作，不會中斷去搬檔案。

---

## Phase 1 — User schema 與權限基礎

> 影響範圍：既有 RAG `app.db` 的 `users` 表。完成後 RAG 必須照常運作。

### Step 1.1 — `User` model 加欄位
- 檔案：`backend/app/models/user.py`
- 動作：加 `search_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)`
- 注意：`default=False` → 既有使用者全部預設**沒有權限**（之後手動開）

### Step 1.2 — Alembic migration
- 檔案：`backend/alembic/versions/<rev>_add_search_enabled.py`
- 動作：`op.add_column('users', sa.Column('search_enabled', sa.Boolean(), nullable=False, server_default='0'))`
- 注意：`server_default='0'` 才能在現有 row 上加 NOT NULL 欄位不炸
- 驗收：`alembic upgrade head`、`sqlite3 app.db ".schema users"` 看得到欄位
- **rollback 方式**：`alembic downgrade -1`

### Step 1.3 — Schema DTO 更新
- 檔案：`backend/app/schemas/auth.py` (`UserOut`)、`backend/app/schemas/admin.py` (`AdminUserOut`)
- 動作：兩個都加 `search_enabled: bool`
- 依賴：1.1 完成

### Step 1.4 — Admin endpoint：toggle 權限
- 檔案：`backend/app/api/admin.py`
- 新增：`PATCH /admin/users/{id}/search-permission`，body `{search_enabled: bool}`
- 規則：admin only（沿用 `get_current_admin`）；不能改自己（語意一致比較好維護）
- 驗收：curl 切換，看 DB 跟 `/auth/me` 回傳都變了

### Step 1.5 — 後端 dependency：權限守門員
- 檔案：`backend/app/core/dependencies.py`
- 新增：

```python
async def require_search_permission(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.search_enabled:
        raise HTTPException(403, "搜尋功能未開通，請聯絡管理員")
    return current_user
```

- 注意：跟 `get_current_admin` 同層級，admin **不**自動有 search 權限（要分開授權，避免「admin 就有所有功能」的假設）

### Step 1.6 — Frontend：User type 加欄位
- 檔案：`frontend/types/index.ts`、`frontend/types/admin.ts`
- 加 `search_enabled: boolean`
- 依賴：1.3 完成

### Step 1.7 — Admin Users 頁加 toggle column
- 檔案：`frontend/app/(app)/admin/users/page.tsx`
- 動作：表格多一欄「鋼筋盤價」，元件用小 switch（lucide `ToggleLeft`/`ToggleRight`），confirm 對話框跟現有 `onToggleActive` 同風格
- 注意：放在「狀態」欄旁邊；hover 顯示 tooltip
- 依賴：1.4 完成

**Phase 1 驗收**：
- 既有 RAG 流程一切正常（在 worktree 8002/3001 環境驗證）
- Admin 可以對任一使用者開關 `search_enabled`
- 被切換的 user 重新登入後 `/auth/me` 看得到新值

---

## Phase 2 — 第二個 DB 與 storage 基礎

> 完全不動既有 RAG 程式碼，新建獨立 engine + 第一張表。

### Step 2.1 — 第二個 engine
- 新檔：`backend/app/search_database.py`
- 內容：仿 `database.py` 結構，但用 `SEARCH_DB_PATH` env、export `SearchBase`、`SearchAsyncSessionLocal`、`get_search_db()`
- 注意：**兩個 Base 必須是不同的 declarative_base**——否則 `Base.metadata.create_all` 會把 RAG models 也建到 search.db 去
- 驗收：`get_search_db()` 拿得到 session

### Step 2.2 — Settings 加欄位
- 檔案：`backend/app/config.py`
- 加：`search_db_path: str = "./search.db"`、衍生 `search_async_database_url`
- 加 SEARCH 用到的 STEELNET 設定（沿用 RAG 既有的 `openai_api_key` / `llm_model`，**不要**為 SEARCH 再開一份 OpenAI key）

### Step 2.3 — 一次性 migration script
- 新檔：`backend/scripts/migrate_search_db.py`
- 動作（按順序）：
  1. 複製 `SEARCH/backend/data/app.db` → `backend/search.db`
  2. 連到 `search.db` 後 `DROP TABLE users`
  3. 跑 `SELECT DISTINCT started_by FROM generation_runs`，逐一對應到 RAG `users.email`
  4. `UPDATE generation_runs SET started_by = '<uuid>'`；對不到的留 NULL + log 警告
- 注意：
  - 純本機腳本，跑一次就丟
  - 要 idempotent（檢查 `search.db` 已存在就略過或要求 `--force`）
  - 檔頭加 `# ONE-SHOT SCRIPT — DO NOT RUN AFTER PRODUCTION`
- 驗收：`sqlite3 search.db ".tables"` 看到 SEARCH 的 4 張表、**沒有** users

### Step 2.4 — search 子模組 storage 骨架
- 新檔：
  - `backend/app/modules/search/__init__.py`
  - `backend/app/modules/search/storage/__init__.py`
  - `backend/app/modules/search/storage/models.py`（先空著，下個 Phase 填）
- 注意：所有 search models 繼承 `SearchBase`（從 `app.search_database` import），**絕對不**用 `app.database.Base`
- 依賴：2.1 完成

### Step 2.5 — main.py lifespan 補初始化
- 檔案：`backend/app/main.py`
- 動作：lifespan 啟動時，import `app.modules.search.storage.models` 並 `await SearchBase.metadata.create_all(engine)`
- 注意：跟既有 RAG lifespan 共用同一個 async context；search engine 的 disposal 要在 shutdown 處理
- 依賴：2.4 完成

**Phase 2 驗收**：
- uvicorn 啟得起來，看到 `[Startup] SEARCH_DB_PATH=...` log
- 既有 RAG 一切正常
- `search.db` 已經有完整資料但沒 users 表

---

## Phase 3 — 業務核心移植（純 Python，不碰 HTTP）

> 把 SEARCH 的「無框架依賴的核心」搬過來。這層的好處是純函式 → 移植成本低、可單元測試。

### Step 3.1 — 移植 core（最簡單，先做這個建立信心）
- 從 `SEARCH/backend/src/steel_backend/core/` 整個複製到 `backend/app/modules/search/core/`
- 改：
  - `from ..config import get_settings` → `from app.config import settings`
  - `from .graph_state import ...` 維持相對 import
- 不用改：`slot_schema.py`、`dates.py`、`csc_products.py`（純資料/邏輯）
- 驗收：`python -c "from app.modules.search.core import slot_schema; print(len(slot_schema.SLOTS_BY_KEY))"` 印出數字

### Step 3.2 — 移植 sources（網路爬蟲）
- 從 `SEARCH/backend/src/steel_backend/sources/` 複製到 `backend/app/modules/search/sources/`
- 改：import 路徑、`get_settings()` → `settings`
- 注意：`@register` 自註冊機制要小心 import order——在 `app.modules.search.__init__.py` 裡 `from . import sources`（就像 SEARCH 原本一樣）
- 依賴：3.1

### Step 3.3 — 移植 llm + output
- `SEARCH/backend/src/steel_backend/llm/` → `backend/app/modules/search/llm/`
- `SEARCH/backend/src/steel_backend/output/` → `backend/app/modules/search/output/`
- 注意：`openai_client.py` 用 RAG 既有的 `settings.openai_api_key`、`settings.llm_model`
- 依賴：3.1

### Step 3.4 — Storage models 改寫成 async SQLAlchemy
- 檔案：`backend/app/modules/search/storage/models.py`
- 動作：SEARCH 原本 5 張表（User 不要、PriceHistory、CscPriceState、CscAnnouncementMeta、GenerationRun）改寫成 async SQLAlchemy declarative class
- 改動點：
  - `class X(SQLModel, table=True)` → `class X(SearchBase): __tablename__ = 'x'`
  - 欄位改 `Mapped[T] = mapped_column(...)`
  - `started_by: str` → `started_by: str | None`（記 UUID）
- 注意：欄位名、index、表名 **必須跟 search.db 既有 schema 一字不差**，否則 ORM 對不上去
- 驗收：`SELECT * FROM price_history LIMIT 1` 透過 ORM 拿得到

### Step 3.5 — Repository 層（取代原本的 `*_store.py`）
- 新檔：
  - `backend/app/modules/search/storage/history_repo.py`
  - `backend/app/modules/search/storage/csc_repo.py`
  - `backend/app/modules/search/storage/run_repo.py`
- 動作：把原本 sync 的 SQLModel 查詢改寫成 async（接受 `db: AsyncSession`）
- 注意：簽名要乾淨，**不要**接 ORM session 以外的東西（一個 repo function 一個 transaction）
- 依賴：3.4

### Step 3.6 — Orchestrator 餵 async session
- 檔案：`backend/app/modules/search/core/orchestrator.py`
- 動作：原本 node 拿 `Session(engine)` 自開的，改成從 state / DI 注入 `AsyncSession`
- 注意：LangGraph state 本身不持有 session（每個 node 要時自己 acquire）；persist 跟 narrate node 改 async
- 依賴：3.5

### Step 3.7 — Smoke test 從 CLI 跑通
- 新檔：`backend/scripts/smoke_search_orchestrator.py`（從 SEARCH 原本的 smoke 改寫）
- 跑：`uv run python scripts/smoke_search_orchestrator.py`
- 期望：印出所有 slot value，產出 docx 在 `data/search_outputs/`
- 驗收：手動驗證產出檔正常

**Phase 3 驗收**：CLI 跑得起來、產出 docx。**還沒有 HTTP API**，但業務邏輯整套通了。

---

## Phase 4 — API 移植

### Step 4.1 — Generation API
- 新檔：`backend/app/modules/search/api/generation.py`
- 從 SEARCH `api/generation.py` 改寫：
  - `Depends(get_current_user)` → 同個（用 RAG 的）
  - 額外加 `Depends(require_search_permission)`
  - `started_by` 存 `str(current_user.id)` (UUID)
- prefix：`/api/search/generation`
- 注意：`asyncio.create_task` 的 fire-and-forget 模式保留（SEARCH 設計是好的），但 task 內部要拿自己的 session（不能複用 request scope 的）

### Step 4.2 — CSC admin API
- 新檔：`backend/app/modules/search/api/csc.py`
- 從 SEARCH `api/admin.py` 抽出 CSC 相關的 endpoints
- prefix：`/api/admin/search-csc`
- 依賴：`Depends(get_current_admin)`

### Step 4.3 — Usage API
- 新檔：`backend/app/modules/search/api/usage.py`
- prefix：`/api/admin/search-usage`
- 依賴：`Depends(get_current_admin)`

### Step 4.4 — Mount routers
- 檔案：`backend/app/main.py`
- 加：

```python
from app.modules.search.api import generation as search_gen
from app.modules.search.api import csc as search_csc
from app.modules.search.api import usage as search_usage
app.include_router(search_gen.router, prefix="/api")
app.include_router(search_csc.router, prefix="/api")
app.include_router(search_usage.router, prefix="/api")
```

- 注意：路徑順序——更具體的（`/api/admin/search-*`）在前，避免被泛 admin 路徑吃掉

### Step 4.5 — 砍掉 SEARCH 原本的 auth
- SEARCH 的 `auth/` 整段不搬，`api/auth.py` 不搬
- 注意：所有 SEARCH 原本呼叫 `get_current_user` 的 import 都換成 `from app.core.dependencies import get_current_user`

**Phase 4 驗收**：
- `curl -H "Authorization: Bearer <token>" http://localhost:8002/api/search/generation/run -d '{...}'` 拿得到 run_id
- 沒權限的 user 拿到 403 + 文字「請聯絡管理員」
- admin 進得去 `/api/admin/search-csc`

---

## Phase 5 — Frontend 移植

### Step 5.1 — Components 搬家 + 樣式整理
- `SEARCH/frontend/src/components/` → `data/frontend/components/search/`
- **不搬**：`providers.tsx`（用 RAG 既有的）、`mac-shell.tsx`（用 RAG 既有的 layout）
- 搬：`generate-view.tsx`、`loading-overlay.tsx`、`stepper.tsx`、`csc-admin-view.tsx`、`admin-usage-view.tsx`
- 改：所有 `import api from "@/lib/api"` 直接沿用 RAG 既有 `api.ts`（會自動帶 Bearer token）
- 樣式：SEARCH 用的 macOS CSS variables（`--accent`、`--surface-*`）複製到 RAG `globals.css` 並加 namespace prefix `--search-*`，避免污染 RAG 既有顏色

### Step 5.2 — `/search` 頁面
- 新檔：
  - `frontend/app/(app)/search/layout.tsx`：客戶端檢查 `user.search_enabled`，false → `router.replace('/search/no-access')`
  - `frontend/app/(app)/search/generate/page.tsx`：包 `<GenerateView />`
  - `frontend/app/(app)/search/no-access/page.tsx`：顯示「鋼筋盤價助理尚未開通，請聯絡系統管理員」+ 按鈕回 `/new`
- 注意：`layout.tsx` 用 `(app)` 的既有 sidebar，不要自己再寫一個

### Step 5.3 — Admin 頁面
- 新檔：
  - `frontend/app/(app)/admin/search-csc/page.tsx`：包 `<CscAdminView />`
  - `frontend/app/(app)/admin/search-usage/page.tsx`：包 `<AdminUsageView />`
- 依賴：5.1 components 已在位

### Step 5.4 — Sidebar 加入口
- 檔案：`frontend/components/layout/Sidebar.tsx`
- 動作：在「新對話」按鈕下方加一個 nav 區，含一個 button「鋼筋盤價助理」
  - 點擊：`router.push('/search/generate')`（沒權限的話 layout 會擋）
  - icon：lucide `FileText` 或 `BarChart3`
  - 樣式：跟「新對話」一致
- 注意：是否顯示**不**依 `search_enabled`——不管有沒有權限都顯示，讓使用者知道有這個功能；沒權限的人點下去看到「請聯絡管理員」
- 依賴：5.2

### Step 5.5 — Admin nav 加入口
- 檔案：`frontend/app/(app)/admin/layout.tsx`（或對應的 admin nav 元件）
- 加兩個 nav item：「SEARCH - CSC 維護」、「SEARCH - 使用統計」
- 依賴：5.3

### Step 5.6 — API client types
- 新檔：`frontend/lib/search/types.ts`
- 動作：把 SEARCH `frontend/src/lib/types.ts` 搬進來
- 注意：所有 type 名字加 `Search` 前綴避免跟 RAG 的撞（e.g. `GenerationRun` → `SearchGenerationRun`）

**Phase 5 驗收**：
- 有權限的 user：sidebar 點「鋼筋盤價助理」→ 進 generate flow → 真的產出 docx
- 沒權限的 user：點下去看到「請聯絡管理員」
- Admin 進得了 `/admin/search-csc` + `/admin/search-usage`

---

## Phase 6 — 整合測試與上線

> 這 Phase 才會碰到 prod。先在 worktree 完成所有驗收，再 merge。

### Step 6.1 — Worktree 內端到端冒煙測試（手動）
- 在 worktree 開 backend:8002 + frontend:3001
- admin 帳號開兩個一般 user 的 `search_enabled`，一個 true 一個 false
- 三組情境跑一遍：admin / 有權限 user / 無權限 user
- 確認所有 RAG 既有功能（聊天、admin、document export）都沒壞

### Step 6.2 — Merge 計畫
- 在 worktree 把所有 Phase 的 commit 整理乾淨（rebase / squash 視大小決定）
- 從 worktree push `feat/search-module` 到遠端（如果有）
- 確認 PR / merge 流程：merge 進 `master` 或當前 prod 分支
- 主 checkout `git pull`
- **此時還沒重啟 prod**

### Step 6.3 — Prod 切換（短暫 downtime 接受）
- 預計影響：30 秒內，PM2 restart 期間 502
- 動作：
  1. 在主 checkout 跑 `alembic upgrade head`（加 `search_enabled` 欄位 — 既有 user 全部 false）
  2. 在主 checkout 跑 `python scripts/migrate_search_db.py` 一次性產出 `search.db`
  3. `pm2 restart all`
  4. `tailscale funnel status` 確認還在
  5. 從外網 `https://kccc3798.tail138ec9.ts.net/` 確認 RAG 還活著
  6. 用 admin 把自己的 `search_enabled` 設 true，測 `/search`

### Step 6.4 — 收尾
- worktree 移除：`git worktree remove C:\Users\226376\Desktop\data-search-module`
- 確認 PM2 `ecosystem.config.js`、Caddyfile、start-system.bat 都沒被動到
- 更新 `data/README.md` 加一節「鋼筋盤價助理模組」（要不要更新 PLAN.md 自由心證）

### Step 6.5 — 舊 SEARCH 資料夾處理
- 新系統穩定執行 2 週後，把 `Desktop/SEARCH/` 移到 `Desktop/SEARCH.archive-DEPRECATED/`
- `SEARCH.archive-20260518/` 副本永久保留
- Git tag `archive/pre-rag-integration-20260518` 永久保留

---

## 跨 Phase 依賴關係圖

```
Phase 0 (準備 + worktree + SEARCH 備份)
    ↓
Phase 1 (User schema + 權限)     ←─── 影響既有 RAG，最先做完
    ↓
Phase 2 (第二個 DB)              ←─── 純新增，不影響既有
    ↓
Phase 3 (業務核心)               ←─── 依賴 Phase 2 的 storage 基礎
    ↓
Phase 4 (API)                   ←─── 依賴 Phase 1 (dependency) + Phase 3 (業務)
    ↓
Phase 5 (Frontend)              ←─── 依賴 Phase 4 的 API 通了
    ↓
Phase 6 (整合測試 + 上 prod)
```

**關鍵依賴提醒**：
- Phase 1 完成前不要動 Phase 4（API 需要 `require_search_permission`）
- Phase 2.3（migration script）必須在 Phase 3.4（重寫 models）之前跑完，否則 ORM 對不上 schema
- Phase 5.4（sidebar 加入口）放在最後——前面都還沒接好就把入口放出來會 404

---

## 可維護性原則（貫穿所有 Phase）

### 1. 邊界守紀律
- `app/modules/search/**` 只 import：自己內部 + `app.models.user` + `app.core.dependencies` + `app.search_database` + `app.config`
- 違反就在 PR review 時擋下來

### 2. DB 完全隔離
- `app.database.Base` 跟 `app.search_database.SearchBase` 是兩個不同的 declarative base
- 兩邊 session 完全分開——絕對不在一個 request 裡同時用兩個 session 做 transaction（會有部分提交的風險）
- user_id 用「字串值複製」連接兩個世界，不靠任何 ORM FK

### 3. 命名前綴避免衝突
- Frontend type 加 `Search` 前綴
- CSS variable 加 `--search-` 前綴
- URL 路徑 `/api/search/*` + `/admin/search-*` 一致
- 元件資料夾 `components/search/`

### 4. 設定集中
- 所有 SEARCH 用的設定都在 `app/config.py` 同一個 `Settings` class，不另開 `SearchSettings`
- 共用的（OPENAI_API_KEY、LLM_MODEL）絕不重複定義

### 5. 「兩個程式碼風格」過渡期可接受，但要朝 RAG 風格收斂
- SEARCH 原本 sync SQLModel → 全改 async SQLAlchemy
- SEARCH 原本兩個 cookie auth → 完全改用 RAG 的 Bearer + refresh cookie
- 不為了相容性留任何 "legacy adapter" 程式碼

### 6. 每個 Phase 完成都跑一次完整 smoke
- Phase 1：登入 → 看到 `user.search_enabled`
- Phase 2：啟動 → 看到 SEARCH_DB log
- Phase 3：CLI smoke 印出 slots
- Phase 4：curl API 拿到 run_id
- Phase 5：UI 從 sidebar 點進去拿到 docx
- Phase 6：prod 切換後外網訪問通

### 7. Migration script 是一次性的
- `migrate_search_db.py` 跑完就丟，不要當作長期工具維護
- 內部要明確標 `# ONE-SHOT SCRIPT — DO NOT RUN AFTER PRODUCTION`

### 8. 文件不蓋既有 md
- SEARCH 的 SYSTEM.md / README.md 不搬到 `data/`
- 新功能說明加在 `data/README.md` 一個小節就好

---

## 風險與緩解

| 風險 | 機率 | 緩解 |
|---|---|---|
| 重寫 sync→async 時漏改一處導致 event loop 阻塞 | 中 | Phase 3 結束時用 `asyncio.get_running_loop()` debug 模式跑 smoke；觀察是否有警告 |
| SEARCH 既有 app.db 有資料但 schema 跟新 ORM model 對不上 | 中 | Step 3.4 寫完先用 `SELECT *` 抽樣對欄位；migration script 完跑後做欄位 diff |
| LangGraph node import 順序錯誤、`@register` 沒跑到 | 低 | 在 `app/modules/search/__init__.py` 顯式 `from . import sources` 跟 SEARCH 原本一致 |
| 既有 RAG user 全部變成沒權限，admin 自己也沒辦法用 SEARCH | 高 | Phase 1.4 完成後立即手動把你自己的帳號 `search_enabled` 設 true |
| `.env` 整併時不小心覆蓋 RAG 的 SECRET_KEY 導致所有人 token 失效 | 低 | Phase 0.6 整理 env 時用 `diff` 對照、保留 RAG 既有 |
| Prod merge 後 `pm2 restart` 中斷使用者操作 | 低 | Step 6.3 選離峰時段做；事先公告 |
| Worktree 內改了 Caddyfile / ecosystem.config.js 然後 merge 回去意外影響 prod | 中 | 0.4 完成後立刻在 worktree 把這兩個檔加進 `.git/info/exclude` 或設 read-only |

---

## 預估時程（單人開發）

| Phase | 工作量 | 主要消耗 |
|---|---|---|
| 0 | 30 分鐘 | 環境整理 + worktree + SEARCH 備份 |
| 1 | 1.5 小時 | Alembic + 前後端兩處改 |
| 2 | 1 小時 | 雙 engine 設定 + migration script |
| 3 | 3-4 小時 | sync→async 改寫最花時間 |
| 4 | 1.5 小時 | API 改 import + 加 dependency |
| 5 | 2-3 小時 | UI 組件搬家 + 路由 + sidebar |
| 6 | 1 小時 | prod 切換 + 收尾 |

**總計約 10-13 小時純編碼**，分 2-3 個工作天做完比較穩。

---

## 動工前 checklist

- [ ] 確認本計畫已被使用者 review
- [ ] data 主 checkout `git status` 乾淨或已 stash
- [ ] SEARCH 已打 git tag `archive/pre-rag-integration-20260518`
- [ ] SEARCH 已 xcopy 一份到 `SEARCH.archive-20260518/`
- [ ] 已建立 worktree `data-search-module/` on branch `feat/search-module`
- [ ] 已準備好獨立的開發 port（backend 8002 / frontend 3001）
- [ ] 已通知相關使用者預期會有 prod restart 短暫中斷（Phase 6 時）
