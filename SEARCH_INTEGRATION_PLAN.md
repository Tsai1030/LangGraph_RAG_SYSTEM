# 鋼筋盤價助理 (SEARCH) 整合進 RAG 系統 — 詳細計畫書

> 版本：v1.2 | 日期：2026-05-18
> 變更：採納第三份審查中**對著當前程式碼驗證有效**的點（worktree .env、rollback、UUID format、defensive PRAGMA、no-relationship rule、docx async wrap、JWT 即時性備忘）
> 目標：把 `C:\Users\226376\Desktop\SEARCH` 整套搬進 `C:\Users\226376\Desktop\data`，當作 RAG 系統的一個子模組。前端透過 sidebar 一個新 tab 進入，後端共用同一個 FastAPI 進程；JWT 共用（只一次登入），SEARCH 自己的資料另存獨立 SQLite。

---

## v1.1 變更摘要（相對 v1.0）

| 影響範圍 | 修正內容 |
|---|---|
| Phase 0 | 強制 commit/stash 受影響檔；列出 SEARCH 全部需要的 dep |
| Phase 2.3 | Migration script 完全重寫：人工 username→user_id 映射表；三張表都處理；SQLite `.backup` API 處理 WAL；ALTER `started_by`/`updated_by` 改 nullable |
| Phase 2.5 | 移到 Phase 3 結尾；async `create_all` 改用 `run_sync` wrapper |
| Phase 3 | 加 dep 補齊步驟；加 LangGraph 0.2 → 1.1 升級檢查點；明列 `_reap_stranded_runs` 要搬 |
| Phase 4 | Router prefix 規則明確化；加 ownership check；先 grep admin 既有路由 |
| Phase 5 | 加 `QueryClientProvider` 安裝；加 frontend deps；逐元件改寫 axios API call；批次替換 CSS var |
| Phase 6 | 加 `app.db` 備份；加 build + install 步驟；加 sentinel files diff check |
| 1.4 | Admin 允許改自己的 `search_enabled`（is_active 才禁止） |

## v1.2 變更摘要（相對 v1.1）

| 影響範圍 | 修正內容 | 為什麼 |
|---|---|---|
| Phase 0.6 | `.env` 不是寫一份新的，而是「從主 checkout copy → 再 append」 | `.env` 是 gitignored，worktree 拿不到既有變數，啟動會炸 |
| Phase 2.3 | Migration script 加 `PRAGMA foreign_keys=OFF`（防禦性）+ UUID 格式驗證；UUID 來源規定走 SQL，不手打 | 當前 SEARCH 雖無 FK，但成本零的防禦；UUID 手打容易格式錯 |
| Phase 3.4 / 3.5 | 加硬規定：「禁止加 `relationship()`，要加就同時 `selectinload`」 | MissingGreenlet 是 async ORM 最常見的雷；當前 models 無 relation 但要防未來 |
| Phase 3.6 | `_node_render` 用 `await asyncio.to_thread(renderer.render, ...)` 包 sync 的 python-docx | docx render 是 CPU/IO 同步，會阻塞 event loop |
| Phase 6 | 新增 Step 6.5 「緊急 Rollback 程序」 | v1.1 只 backup 沒 rollback 指令，上線出事沒 SOP |
| §1.4 | 加備忘：「`get_current_user` 每次 hit DB，`search_enabled` 改完下一次 request 就生效；勿改為信任 JWT payload」 | 防止未來重構引入「需要重登」的回歸 |

---

## 0. 開工前的環境守則（重要）

### 0.1 RAG 系統正在生產（不能中斷）

- `C:\Users\226376\Desktop\data` 目前**正在線上服務**：PM2 跑 backend:8000 + frontend:3000，Caddy :9000 → Tailscale Funnel → `https://kccw0077.tail138ec9.ts.net:8443`
- **絕對不可以**直接在這個資料夾改檔（會觸發 Next.js 熱重載、可能讓使用者看到半成品 / 短暫 5xx）
- **必須使用 git worktree** 把整合工作隔離出去

### 0.2 動工前**強制**處理未 commit 的修改

> 之前 `git status` 顯示以下檔案有未 commit 修改。worktree 只繼承已 commit 的內容，這些檔案到時會在 worktree 內被覆寫，merge 必衝突。

**必須先 commit 或 stash 的檔案：**
```
M  frontend/app/favicon.ico
M  frontend/components/auth/AuthShell.tsx
M  frontend/components/layout/Sidebar.tsx       ← Phase 5.4 會再改一次，沒先 commit 一定爆
```

**動作（二選一）：**

```bash
# 選項 A：commit 進當前分支（推薦，因為這些看起來是 prod 在用的版本）
cd C:\Users\226376\Desktop\data
git add frontend/app/favicon.ico frontend/components/auth/AuthShell.tsx frontend/components/layout/Sidebar.tsx
git commit -m "chore(frontend): snapshot current prod UI state before search-module integration"

# 選項 B：stash（若不想立刻 commit）
git stash push -m "pre-search-integration" -- frontend/app/favicon.ico frontend/components/auth/AuthShell.tsx frontend/components/layout/Sidebar.tsx
```

**注意：** 未追蹤檔案（`backend/app.db.backup-*`、`form_structure.txt`、`token*.csv` 等）跟 worktree 無關，可以放著。

### 0.3 Worktree 設定

```bash
cd C:\Users\226376\Desktop\data
git worktree add -b feat/search-module C:\Users\226376\Desktop\data-search-module
```

- **Worktree 路徑**：`C:\Users\226376\Desktop\data-search-module`
- **分支名**：`feat/search-module`
- **工作流程**：所有 Phase 1~5 的 code change 都在 worktree 內進行
- **驗證**：在 worktree 內另開 backend:8002 + frontend:3001 跑開發版（不要佔 prod 用的 8000/3000）
- **完工**：所有 Phase 通過後合併回 `master`，主 checkout `git pull`，PM2 restart 一次

### 0.4 SEARCH 資料夾版本備份

```bash
# 1) Git tag — 程式碼層還原點
cd C:\Users\226376\Desktop\SEARCH
git tag archive/pre-rag-integration-20260518 -m "Snapshot before SEARCH is merged into RAG as a module"

# 2) 整資料夾複製 — 環境層還原點。用 robocopy 排除 node_modules/.venv/.next 加速
robocopy "C:\Users\226376\Desktop\SEARCH" "C:\Users\226376\Desktop\SEARCH.archive-20260518" /MIR /XD node_modules .venv .next .next-* __pycache__
```

整合完成、新系統穩定執行兩週後，才考慮把 SEARCH 本體刪除。

### 0.5 Prod 環境檔案禁止觸碰清單（worktree 內）

下列檔案在整合工作期間**禁止修改**：

- `ecosystem.config.js`
- `start-system.bat`
- 雖然 `C:\caddy\Caddyfile` 不在 repo 裡（不用管 git），但動工期間也不可改

**驗證機制：** PR 送出前必須跑：
```bash
git diff master..feat/search-module -- ecosystem.config.js start-system.bat
# 輸出必須空白
```

### 0.6 環境變數 (`data/.env`) 整併

> ⚠️ **重要**：`.env` 在 `.gitignore` 內，worktree 建出來時**沒有 .env**。必須先從主 checkout 複製整份過去，再 append SEARCH 新變數。若只寫一份只含 SEARCH 變數的 .env，啟動會因找不到 `OPENAI_API_KEY` / `SECRET_KEY` 等而炸。

```powershell
# 1) 先把主 checkout 的 .env 整份複製到 worktree
Copy-Item "C:\Users\226376\Desktop\data\.env" "C:\Users\226376\Desktop\data-search-module\.env"

# 2) 再 append SEARCH 的新變數（注意：放在檔尾、編碼用 UTF-8 with no BOM）
Add-Content -Path "C:\Users\226376\Desktop\data-search-module\.env" -Encoding utf8 -Value @"

# ─── SEARCH module (added by integration plan v1.2) ───
STEELNET_USER=bestw
STEELNET_PASSWORD=hb092820
STEELNET_BASE=https://www.steelnet.com.tw
SEARCH_DB_PATH=./search.db
"@
```

**驗證：**
```bash
cd C:\Users\226376\Desktop\data-search-module\backend
uv run python -c "from app.config import settings; print('openai:', settings.openai_api_key[:10], 'steelnet:', settings.steelnet_user, 'search_db:', settings.search_db_path)"
```
三個值都印出來才算通過。

---

## 1. 設計總綱

### 1.1 命名約定

| 概念 | 命名 |
|---|---|
| 子模組 Python 路徑 | `app.modules.search` |
| URL 前綴（後端） | `/api/search/*`、`/api/admin/search-*` |
| URL 前綴（前端） | `/search/*`、`/admin/search-*` |
| 第二個 DB 檔名 | `backend/search.db` |
| 權限欄位 | `users.search_enabled: bool` |
| 模組顯示名 | 「鋼筋盤價助理」 |
| 整合分支 | `feat/search-module` |
| Worktree 路徑 | `C:\Users\226376\Desktop\data-search-module` |
| Frontend dev port | 3001（避開 prod 3000） |
| Backend dev port | 8002（避開 prod 8000） |

### 1.2 最終目錄結構（同 v1.0，略）

### 1.3 模組邊界

- `app/modules/search/**` 只能 import：
  - `app.modules.search.*`（自己內部）
  - `app.models.user`、`app.core.dependencies`、`app.core.security`、`app.search_database`、`app.config`
- `app/modules/search/**` **禁止 import**：
  - `app.models.conversation/message/summary`
  - `app.rag.*`、`app.graph.*`
  - `app.api.{chat,conversations,export}`
- `app/**`（非 search）**禁止 import** `app.modules.search.*`
- 兩邊只透過 `user_id (UUID 字串)` 溝通

### 1.4 已敲定的設計決策

| 決策 | 結論 |
|---|---|
| 資料夾結構 | 合併進 `data/` 當子模組 |
| DB 切法 | 另開 `search.db`，users 表只在 `app.db` |
| ORM 風格 | 全改 async SQLAlchemy（跟 RAG 對齊） |
| 權限欄位 | 單一布林 `search_enabled` |
| Admin 頁面位置 | 進 RAG admin 區（`/admin/search-csc`、`/admin/search-usage`） |
| user 識別 | SEARCH 內部存 `user_id` (UUID 字串) |
| 既有 SEARCH `app.db` 處理 | 一次性 migration script（人工映射表）；對不到 username 的存 NULL |
| 舊 outputs/ | **不搬**；舊 docx 接受失效，前端顯示「已過期」 |
| Admin self-toggle search_enabled | **允許**（只有 is_active 才禁止自我關閉） |
| JWT 共用 | SEARCH 不再簽 token；用 RAG 既有 `SECRET_KEY` |
| 權限變更生效時機 | **即時**（`get_current_user` 每次都 hit DB 重抓 `User`）；**不需要重登**。**禁止**未來改成從 JWT payload 讀 `search_enabled`，否則會引入「改完權限要重登」的回歸 |

### 1.5 SEARCH 依賴對照表（補進 RAG）

**Backend (`backend/pyproject.toml`)** 新增：
```toml
"httpx>=0.27",
"beautifulsoup4>=4.12",
"lxml>=5.3",
"tenacity>=9.0",
"python-multipart>=0.0.20",
"langchain>=0.3",
```
> 不加 `sqlmodel`（我們改寫成 async SQLAlchemy）、不加 `psycopg`（RAG 用 aiosqlite）。`openai`、`langchain-openai`、`langgraph` RAG 已有但版本不同 → 用 RAG 較新的版本（**Phase 3 要驗證 SEARCH 程式碼相容**）。

**Frontend (`frontend/package.json`)** 新增：
```json
"@tanstack/react-query": "^5",
"react-hook-form": "^7",
"zod": "^3",
"@hookform/resolvers": "^3"
```
> lucide-react / clsx 等視 RAG 既有版本是否相容決定要不要動。

---

## Phase 0 — 準備工作

| 步驟 | 動作 | 完成驗收 |
|---|---|---|
| 0.1 | 主 checkout 處理未 commit 修改（§0.2） | `git status` 三個 M 不見了 |
| 0.2 | SEARCH 打 git tag `archive/pre-rag-integration-20260518` | `git tag -l "archive/*"` 看得到 |
| 0.3 | robocopy SEARCH 整資料夾到 `SEARCH.archive-20260518` | 副本資料夾存在 |
| 0.4 | data 開 worktree `feat/search-module` → `data-search-module/` | `git worktree list` 兩個 entry |
| 0.5 | worktree 內把 SEARCH 的 `templates/meeting_template.docx` 複製到 `data-search-module/backend/templates/` | 檔案在位 |
| 0.6 | worktree 內把 §0.6 的 env 變數加進 `.env`（**不要**動既有變數） | python -c import settings 印出值 |
| 0.7 | worktree 內 `cd backend && uv sync` 安裝（dep 還沒加，先確認既有可跑） | `uv run uvicorn app.main:app --port 8002` 可起 |
| 0.8 | worktree 內 `cd frontend && yarn install`（dep 還沒加） | `yarn dev -p 3001` 可起 |

**為什麼先做：** 把所有「來自外部的東西」+ worktree + 環境都先就位，之後每個 Phase 都是純程式碼工作。

---

## Phase 1 — User schema 與權限基礎

### Step 1.1 — `User` model 加欄位
- 檔案：`backend/app/models/user.py`
- 動作：加 `search_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)`

### Step 1.2 — Alembic migration
- `alembic revision -m "add_search_enabled"`
- `op.add_column('users', sa.Column('search_enabled', sa.Boolean(), nullable=False, server_default='0'))`
- 注意：`server_default='0'` 才能在現有 row 上加 NOT NULL 欄位
- 驗收：`alembic upgrade head` 後 `sqlite3 app.db ".schema users"` 看得到欄位
- Rollback：`alembic downgrade -1`

### Step 1.3 — Schema DTO
- 檔案：`backend/app/schemas/auth.py` (`UserOut`)、`backend/app/schemas/admin.py` (`AdminUserOut`)
- 兩個都加 `search_enabled: bool`

### Step 1.4 — Admin toggle endpoint
- 檔案：`backend/app/api/admin.py`
- 新增：`PATCH /admin/users/{id}/search-permission`，body `{search_enabled: bool}`
- 規則：admin only（`get_current_admin`）
- **允許**改自己（`search_enabled` 失誤可從 DB 改回；不像 `is_active` 會鎖死登入）
- 對照：`is_active` 仍禁止改自己（既有邏輯不動）

### Step 1.5 — 後端 dependency
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
- admin **不**自動有 search 權限（要分開授權）

### Step 1.6 — Frontend type
- 檔案：`frontend/types/index.ts`、`frontend/types/admin.ts`
- 加 `search_enabled: boolean`

### Step 1.7 — Admin Users 頁加 toggle column
- 檔案：`frontend/app/(app)/admin/users/page.tsx`
- 多一欄「鋼筋盤價」放在「狀態」旁邊
- 元件：小 switch（`ToggleLeft`/`ToggleRight`）、confirm 對話框沿用 `onToggleActive` 模式
- **允許**對自己的 row 操作（不像 is_active toggle 要 disable）

**Phase 1 驗收：**
- 既有 RAG 流程正常
- Admin 可對任一使用者（含自己）開關 `search_enabled`
- 切換後 `/auth/me` 拿到新值
- 沒權限的 user 呼叫帶 `require_search_permission` 的 endpoint 拿到 403

---

## Phase 2 — 第二個 DB 與 storage 基礎

### Step 2.1 — 第二個 engine
- 新檔：`backend/app/search_database.py`
- 仿 `database.py` 結構，用 `SEARCH_DB_PATH` env
- export `SearchBase`、`SearchAsyncSessionLocal`、`get_search_db()`、`search_engine`
- **`SearchBase = declarative_base()` 必須跟 `app.database.Base` 是不同物件**

### Step 2.2 — Settings
- 檔案：`backend/app/config.py`
- 加：`search_db_path: str = "./search.db"`、`steelnet_user/password/base`
- 衍生屬性 `search_async_database_url`

### Step 2.3 — 一次性 migration script（**重點改寫**）

- 新檔：`backend/scripts/migrate_search_db.py`
- 檔頭加：`# ONE-SHOT SCRIPT — DO NOT RUN AFTER PRODUCTION`
- 接受 `--source <path>`（預設 SEARCH/backend/data/app.db）跟 `--force`

**步驟：**

1. **WAL-safe 複製**（解決 -wal 檔資料漏掉的問題）：
   ```python
   import sqlite3
   src = sqlite3.connect(args.source)
   dst = sqlite3.connect(target)
   src.backup(dst)   # 自動處理 WAL checkpoint
   src.close(); dst.close()
   ```

2. **連到 target 後立刻 `PRAGMA foreign_keys=OFF;`**（防禦性）
   - 當前 SEARCH schema 雖無 FK，但 script 含 DROP/重建表的 DDL，這條成本零、能擋未來若有人加 FK 引入的 cascade 風險
   - 同樣為了 SQLite ALTER 限制，script 過程中保持 OFF；script 結尾再 ON

3. **DROP users**：`DROP TABLE IF EXISTS users;`

4. **從 RAG app.db 直接抓 UUID**（不要手打、避免格式錯）：
   ```python
   # RAG users.id 永遠是 36-char 帶 hyphen 的 UUID (model: String(36) + str(uuid.uuid4()))
   rag = sqlite3.connect(RAG_APP_DB)
   rag_users = {row[1]: row[0] for row in rag.execute("SELECT id, email FROM users")}
   # rag_users 範例: {"chuang0279@gmail.com": "8a1f...-...-...", ...}

   # SEARCH username → RAG email 的人工對照（這部分要手填，因為跨系統語意不同）
   USERNAME_TO_EMAIL: dict[str, str | None] = {
       "admin": "chuang0279@gmail.com",
       # 'kccc01': 'someone@gmail.com',
       # ...對不到的不要列、會自動 NULL
   }

   # 自動轉成 username → uuid（純查表，沒有手打 UUID 的機會）
   USERNAME_TO_UUID: dict[str, str] = {
       u: rag_users[e] for u, e in USERNAME_TO_EMAIL.items()
       if e in rag_users
   }
   ```
   > 動工時先 `sqlite3 SEARCH/backend/data/app.db "SELECT username FROM users"` 看實際有哪些，跟 RAG `app.db "SELECT id, email FROM users"` 對照，填 `USERNAME_TO_EMAIL`。

5. **UUID 格式 sanity check**（防呆，防 hyphenated/no-hyphen 不一致）：
   ```python
   import re
   UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
   for u, uuid_str in USERNAME_TO_UUID.items():
       assert UUID_RE.match(uuid_str), f"{u}: UUID 格式不對 {uuid_str!r}"
   ```
   若任何一個 UUID 不是 36-char 帶 hyphen，整 script abort（避免寫進去後 Ownership Check 永遠 404）

6. **ALTER 三張表的 user 欄位改 nullable**（SQLite 不支援直接 ALTER COLUMN，要用 rename+create+copy）：
   ```python
   # 對 generation_runs, csc_price_state, csc_announcement_meta 各跑一次
   # 1. CREATE TABLE <name>_new (...同 schema, 但 started_by/updated_by 改 nullable...)
   # 2. INSERT INTO <name>_new SELECT * FROM <name>;
   # 3. DROP TABLE <name>; ALTER TABLE <name>_new RENAME TO <name>;
   ```

7. **三張表都做 UPDATE**：
   ```python
   for username, uuid in USERNAME_TO_UUID.items():
       cur.execute("UPDATE generation_runs SET started_by = ? WHERE started_by = ?", (uuid, username))
       cur.execute("UPDATE csc_price_state SET updated_by = ? WHERE updated_by = ?", (uuid, username))
       cur.execute("UPDATE csc_announcement_meta SET updated_by = ? WHERE updated_by = ?", (uuid, username))
   # 把沒對到的剩餘 username 改 NULL（避免殘留無意義字串）
   cur.execute("UPDATE generation_runs SET started_by = NULL WHERE started_by NOT IN (<list of UUIDs>) AND started_by IS NOT NULL")
   # 同理另兩張
   ```

8. **`PRAGMA foreign_keys=ON;`** 恢復；提交；關連線

9. **印出 audit log**：對應到 X 筆、留 NULL Y 筆、影響的 distinct username 列表

**驗收：**
- `sqlite3 search.db ".tables"` 看到 4 張表、**沒有 users**
- `sqlite3 search.db "SELECT DISTINCT started_by FROM generation_runs"` 全是 UUID 字串或 NULL
- `sqlite3 search.db ".schema generation_runs"` 看到 `started_by TEXT`（沒 NOT NULL）

### Step 2.4 — search 子模組 storage 骨架（先空著）

- 新檔：
  - `backend/app/modules/search/__init__.py`
  - `backend/app/modules/search/storage/__init__.py`
  - `backend/app/modules/search/storage/models.py`（先空，Phase 3.4 填）

### Step 2.5 — main.py lifespan 註冊空 router（**先不做 create_all**）

- 檔案：`backend/app/main.py`
- 動作：lifespan 加 import `from app.search_database import search_engine`；shutdown 處 dispose
- **不做** `create_all` — 等 Phase 3.4 models 寫完再加

**Phase 2 驗收：**
- uvicorn 啟得起來
- 既有 RAG 一切正常
- `search.db` 有完整資料、3 欄已改 nullable、沒 users 表

---

## Phase 3 — 業務核心移植

### Step 3.0 — Backend dependencies 補齊
- 檔案：`backend/pyproject.toml`
- 加入 §1.5 列的所有 backend dep
- 跑 `uv sync` 安裝
- 驗收：`python -c "import httpx, bs4, lxml, tenacity"` 不報錯

### Step 3.1 — 移植 core
- `SEARCH/backend/src/steel_backend/core/` → `backend/app/modules/search/core/`
- 改 import：`from ..config import get_settings` → `from app.config import settings`
- 不用改：`slot_schema.py`、`dates.py`、`csc_products.py`
- 驗收：`python -c "from app.modules.search.core import slot_schema; print(len(slot_schema.SLOTS_BY_KEY))"`

### Step 3.1.5 — LangGraph API 升版檢查（**新增**）
- RAG 用 `langgraph>=1.1.6`，SEARCH 原本 `langgraph>=0.2.50`，可能有 breaking change
- 動作：跑 `python -c "from app.modules.search.core.orchestrator import build_graph; build_graph()"`
- 預期 breaking points：
  - `from langgraph.graph import StateGraph, START, END` — API 大致穩定
  - `add_messages` 來源可能改 path
  - `TypedDict(total=False)` 用法 OK
- 若炸：對著 error 改 import / API；不要降版 langgraph
- 驗收：`build_graph()` 不報錯，回傳一個 compiled graph

### Step 3.2 — 移植 sources + 修正自註冊
- `SEARCH/backend/src/steel_backend/sources/` → `backend/app/modules/search/sources/`
- **修正**：在 `app/modules/search/__init__.py` 加：
  ```python
  # Explicitly import each adapter to trigger @register decorator
  from .sources import fengxing, market_narrator, weekly_market  # noqa: F401
  ```
- 為什麼：`sources/__init__.py` 只 export base，不會自動 cascading import 各 adapter
- 驗收：`from app.modules.search import sources; print(sources.SourceAdapter._registry)` 看到 3 個 adapter

### Step 3.3 — 移植 llm + output
- `llm/` → `backend/app/modules/search/llm/`
- `output/` → `backend/app/modules/search/output/`
- 注意：
  - `openai_client.py` 用 RAG 既有 `settings.openai_api_key`、`settings.llm_model`
  - `docx_renderer.py` 的 template 路徑改從 `settings.search_template_path` 讀絕對路徑（不要 hardcoded 相對路徑）

### Step 3.4 — Storage models 改寫 async SQLAlchemy
- 檔案：`backend/app/modules/search/storage/models.py`
- 4 張表（不要 User）：`PriceHistory`、`CscPriceState`、`CscAnnouncementMeta`、`GenerationRun`
- 改寫：
  - `class X(SQLModel, table=True)` → `class X(SearchBase): __tablename__ = 'x'`
  - 欄位改 `Mapped[T] = mapped_column(...)`
  - `started_by: str` → `started_by: str | None = mapped_column(String(64), nullable=True)`
  - `updated_by` 同理
- **欄位名、index、表名必須跟 search.db 既有 schema 一字不差**
- 🔒 **硬規定（防 MissingGreenlet）**：**禁止**在這些 model 加 `relationship()`。若未來真有跨表查詢需求，必須在 query 端用 `select(...).options(selectinload(Model.relation))` eager-load；不能依賴 lazy loading（async session 下 lazy load 會 raise `MissingGreenlet`）。當前 SEARCH models 無 relation，這條是預防未來重構引入回歸。
- 驗收（**強化版**）：
  ```bash
  sqlite3 search.db ".schema" > new.sql
  sqlite3 SEARCH/backend/data/app.db ".schema" > orig.sql
  diff orig.sql new.sql   # 只差 users 表 + nullable 三欄
  ```
- 額外：`SELECT * FROM price_history LIMIT 3` 透過 ORM 拿得到、值正確

### Step 3.5 — Repository 層
- 新檔：
  - `storage/history_repo.py`
  - `storage/csc_repo.py`
  - `storage/run_repo.py`
- 把原本 sync SQLModel 查詢改成 async（接 `db: AsyncSession`）
- 一個 repo function = 一個 transaction

### Step 3.6 — Orchestrator 餵 async session + 包同步阻塞點
- `core/orchestrator.py` 的 persist/narrate node 改 async，session 從 DI 注入
- LangGraph state 不持有 session（每個 node 用時自己 acquire）
- **`_node_render` 必須包 `asyncio.to_thread`**（python-docx 是同步 CPU 密集，會阻塞整個 FastAPI event loop，跑 docx 期間 RAG 其他使用者會卡）：
  ```python
  async def _node_render(state: GenerationState) -> dict:
      renderer = DocxRenderer(...)
      # 同步、CPU 密集 → 必須丟到 thread pool，不能在 event loop 直接跑
      output_path = await asyncio.to_thread(
          renderer.render,
          state["slot_values"], state["confidence"], target_path
      )
      return {"output_path": output_path}
  ```
- 其他 node：`fetch`/`validate` 已是純 async（httpx.AsyncClient + AsyncOpenAI），不需要 to_thread；`persist`/`narrate` 改 async session 後也是純 async

### Step 3.7 — `_reap_stranded_runs` 搬進 RAG lifespan
- 從 SEARCH `main.py` 把 `_reap_stranded_runs` 函式整個搬到 `data/backend/app/main.py`
- 改成 async + 用 `SearchAsyncSessionLocal`
- 在 lifespan startup 接續 RAG 既有 init 後呼叫一次
- 為什麼：PM2 restart 時跑到一半的 generation 會 cancel，要把 status='running' 全部 reap 成 failed，否則前端輪詢無限轉

### Step 3.8 — Lifespan 補 `create_all`（移自 v1.0 Phase 2.5）
- 檔案：`backend/app/main.py`
- 加入（**正確 async pattern**）：
  ```python
  from app.search_database import search_engine, SearchBase
  from app.modules.search.storage import models as _search_models  # noqa: F401 — register tables

  async with search_engine.begin() as conn:
      await conn.run_sync(SearchBase.metadata.create_all)
  ```
- 角色：**greenfield 部署的保護網**（既有 DB 由 migration script 提供，這裡是 no-op）

### Step 3.9 — CLI smoke test
- 新檔：`backend/scripts/smoke_search_orchestrator.py`
- 跑前：`mkdir -p data/search_outputs/`
- 跑：`uv run python scripts/smoke_search_orchestrator.py`
- 驗收：印出 slot value、`data/search_outputs/` 有 docx 產出

**Phase 3 驗收：** CLI 跑得起來、產出 docx。**還沒有 HTTP API**。

---

## Phase 4 — API 移植

### Step 4.0 — 路由衝突檢查（**新增**）
- 先 grep 既有 RAG admin routes：
  ```bash
  grep -n "@router\.\(get\|post\|patch\|put\|delete\)" backend/app/api/admin.py
  ```
- 確認**沒有** `/admin/{some_var}/...` 這種會吃掉 `/admin/search-csc` 的動態路徑
- 若有，要改寫順序或重新命名

### Step 4.1 — Router prefix 規則（**修正**）

**規則：router 內 prefix 只到模組內路徑、由 main 統一加 `/api`**

- ❌ 錯：router `prefix="/api/search/generation"` + main `prefix="/api"` → `/api/api/...`
- ✅ 對：router `prefix="/search/generation"` + main `prefix="/api"` → `/api/search/generation`

### Step 4.2 — Generation API
- 新檔：`backend/app/modules/search/api/generation.py`
- `APIRouter(prefix="/search/generation", tags=["search-generation"])`
- 從 SEARCH `api/generation.py` 改寫：
  - `Depends(get_current_user)` 用 RAG 版
  - 額外 `Depends(require_search_permission)`
  - `started_by=str(current_user.id)` (UUID)
  - **加 ownership check**（見 4.5）
- `asyncio.create_task` 模式保留；task 內部自己 acquire `SearchAsyncSessionLocal` session（不能複用 request scope 的）

### Step 4.3 — CSC admin API
- 新檔：`backend/app/modules/search/api/csc.py`
- `APIRouter(prefix="/admin/search-csc", tags=["search-admin-csc"])`
- 從 SEARCH `api/admin.py` 抽 CSC endpoints
- 依賴：`Depends(get_current_admin)`

### Step 4.4 — Usage API
- 新檔：`backend/app/modules/search/api/usage.py`
- `APIRouter(prefix="/admin/search-usage", tags=["search-admin-usage"])`
- 依賴：`Depends(get_current_admin)`

### Step 4.5 — Ownership check（**新增 / 安全強化**）

`GET /search/generation/{id}`、`POST /{id}/internal-data`、`GET /{id}/docx` 三個 endpoint：
```python
run = await run_repo.get(db, run_id)
if run is None:
    raise HTTPException(404)
is_owner = run.started_by == str(current_user.id)
is_admin = current_user.role == "admin"
if not (is_owner or is_admin):
    raise HTTPException(404)   # 用 404 不用 403 避免洩漏存在性
```

### Step 4.6 — Mount routers
- `backend/app/main.py`：
  ```python
  from app.modules.search.api import generation as search_gen
  from app.modules.search.api import csc as search_csc
  from app.modules.search.api import usage as search_usage
  app.include_router(search_gen.router, prefix="/api")
  app.include_router(search_csc.router, prefix="/api")
  app.include_router(search_usage.router, prefix="/api")
  ```

### Step 4.7 — 砍 SEARCH 原本的 auth
- SEARCH `auth/` 整段不搬
- 所有 import `get_current_user` 都改成 `from app.core.dependencies import get_current_user`

**Phase 4 驗收：**
- `curl -H "Authorization: Bearer <token>" http://localhost:8002/api/search/generation/run -d '{...}'` 拿到 run_id
- 沒權限的 user 拿到 403 「請聯絡管理員」
- 別人猜 id 下載別人的 docx → 404
- admin 進得去 `/api/admin/search-csc` 跟 `/api/admin/search-usage`

---

## Phase 5 — Frontend 移植

### Step 5.0 — Frontend dependencies 補齊
- `frontend/package.json` 加入 §1.5 列的所有 frontend dep
- `cd frontend && yarn install`
- 驗收：`node_modules/@tanstack/react-query/package.json` 存在

### Step 5.1 — QueryClientProvider 注入
- 檔案：`data/frontend/app/(app)/layout.tsx`
- 在 `<TooltipProvider>` 外層或內層包：
  ```tsx
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } }
  }));
  return <QueryClientProvider client={qc}>...</QueryClientProvider>;
  ```
- 為什麼：SEARCH 元件用 `useQuery`/`useMutation`，沒 provider 會 crash。包在 `(app)/layout` 比 `frontend/app/layout.tsx` 更精準（auth pages 不需要）

### Step 5.2 — Components 搬家
- `SEARCH/frontend/src/components/` → `data/frontend/components/search/`
- **不搬**：`providers.tsx`、`mac-shell.tsx`
- 搬：`generate-view.tsx`、`loading-overlay.tsx`、`stepper.tsx`、`csc-admin-view.tsx`、`admin-usage-view.tsx`

### Step 5.3 — 改寫 API 呼叫（**重點 / 不可省**）

SEARCH 元件原本：
```ts
import { api } from "@/lib/api";
const data = await api<UsageRow[]>("/api/admin/usage");
await api(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(...) });
```

RAG 元件用 axios：
```ts
import api from "@/lib/api";
const { data } = await api.get<UsageRow[]>("/admin/search-usage");
await api.patch(`/admin/users/${id}`, body);
```

**逐元件改寫規則：**

1. `api<T>(path, opts)` → `api.get/post/patch/delete<T>(...)`，拿 `.data`
2. 移除 path 開頭的 `/api`（axios baseURL 已是 `/api`）
3. URL 改：`/admin/csc/{group}` → `/admin/search-csc/{group}`、`/admin/usage` → `/admin/search-usage`、`/generation/...` → `/search/generation/...`
4. `JSON.stringify` body 改直接傳物件
5. error handling 從 `if (!res.ok)` 改成 axios `.catch`

**逐個元件清單：**
- `generate-view.tsx`：6 處左右 fetch
- `csc-admin-view.tsx`：3 處
- `admin-usage-view.tsx`：1 處
- `admin-users-view.tsx`：**不搬**（RAG 既有自己的 admin-users）

### Step 5.4 — CSS variables 批次替換（**新增**）

1. 把 SEARCH `globals.css` 的 macOS 風格 CSS variables（`--accent`、`--surface-*` 等）複製到 RAG `frontend/app/globals.css`，**全部加 `--search-` 前綴**：
   ```css
   :root {
     --search-accent: ...;
     --search-surface-1: ...;
     ...
   }
   ```
2. 對 `frontend/components/search/**/*.tsx` 做批次 sed：
   ```bash
   # PowerShell
   Get-ChildItem -Path frontend/components/search -Recurse -Include *.tsx |
     ForEach-Object { (Get-Content $_) -replace 'var\(--(accent|surface-\d+|elevated)\)', 'var(--search-$1)' | Set-Content $_ }
   ```
3. 驗收：`grep -r "var(--accent)" frontend/components/search/` 應該空

### Step 5.5 — `/search` 頁面

- 新檔：
  - `frontend/app/(app)/search/layout.tsx`：客戶端檢查 `user.search_enabled`，false → `router.replace('/search/no-access')`；true → 直接 render children。**不會閃內容**，因為 GenerateView 自己有 loading state
  - `frontend/app/(app)/search/generate/page.tsx`：包 `<GenerateView />`
  - `frontend/app/(app)/search/no-access/page.tsx`：「鋼筋盤價助理尚未開通，請聯絡系統管理員」+ 按鈕回 `/new`

### Step 5.6 — Admin 頁面
- `frontend/app/(app)/admin/search-csc/page.tsx`：包 `<CscAdminView />`
- `frontend/app/(app)/admin/search-usage/page.tsx`：包 `<AdminUsageView />`

### Step 5.7 — Sidebar 加入口
- 檔案：`frontend/components/layout/Sidebar.tsx`（**§0.2 commit 後的版本**）
- 在「新對話」按鈕下加一個 button「鋼筋盤價助理」（icon: `FileText` or `BarChart3`）
- 點擊：`router.push('/search/generate')`
- **不**依 search_enabled 決定要不要顯示（讓使用者知道有這功能；沒權限的點下去到 no-access 頁）

### Step 5.8 — Admin nav 加入口
- 檔案：`frontend/app/(app)/admin/layout.tsx`
- 加兩個 nav item：「SEARCH - CSC 維護」、「SEARCH - 使用統計」

### Step 5.9 — Types
- 新檔：`frontend/lib/search/types.ts`
- SEARCH types 全部加 `Search` 前綴（e.g. `GenerationRun` → `SearchGenerationRun`）

**Phase 5 驗收：**
- 有權限 user：sidebar 點「鋼筋盤價助理」→ 真的產出 docx
- 沒權限 user：點下去到「請聯絡管理員」頁
- Admin 進得了 `/admin/search-csc` + `/admin/search-usage`
- 既有 RAG 聊天、export 等所有功能無影響

---

## Phase 6 — 整合測試與上線

### Step 6.1 — Worktree 內 E2E 冒煙測試
- backend:8002 + frontend:3001 跑起來
- admin 開兩個一般 user 的 `search_enabled`，一 true 一 false
- 三組情境跑一遍：admin / 有權限 / 無權限
- 確認所有 RAG 既有功能無壞

### Step 6.2 — Sentinel files diff check
```bash
git diff master..feat/search-module -- ecosystem.config.js start-system.bat
# 必須空白
```

### Step 6.3 — Merge 計畫
- 整理 worktree commits（rebase / squash 視 PR 大小）
- 把 `feat/search-module` merge 進 prod 分支
- 主 checkout `git pull` 拿到變更
- **此時還沒重啟 prod**

### Step 6.4 — Prod 切換步驟（**修正：補 backup + build + install**）

> 預計 downtime：1-2 分鐘（build + restart）；建議離峰時段

```bash
cd C:\Users\226376\Desktop\data

# Step 6.4.0 — 備份（沿用你既有命名習慣）
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
cp backend/app.db "backend/app.db.pre-search-integration-$ts"

# Step 6.4.1 — Backend deps
cd backend
uv sync
cd ..

# Step 6.4.2 — Frontend deps + build
cd frontend
yarn install
yarn build
cd ..

# Step 6.4.3 — DB migration
cd backend
uv run alembic upgrade head

# Step 6.4.4 — 一次性 SEARCH data migration（會產出 backend/search.db）
uv run python scripts/migrate_search_db.py --source "C:/Users/226376/Desktop/SEARCH/backend/data/app.db"
cd ..

# Step 6.4.5 — Restart
pm2 restart all

# Step 6.4.6 — Smoke
tailscale funnel status
curl https://kccw0077.tail138ec9.ts.net:8443/api/health
# 開瀏覽器測登入 + RAG 聊天 + search 頁面
```

### Step 6.5 — 緊急 Rollback 程序（若上線出事）

> 觸發條件：6.4.5 `pm2 restart all` 後，外網 RAG 完全壞、登入失敗、或 500 滿天飛。
> **時限**：發現異常後 5 分鐘內決定要不要 rollback；超過 5 分鐘代表你已經在 hotfix 模式。

```powershell
# 步驟順序固定：先停服 → 還原 → 重啟，避免「DB 還原但 code 還是新的」這種錯位
cd C:\Users\226376\Desktop\data

# 1) 停 PM2（避免新 code 繼續寫舊 DB）
pm2 stop all

# 2) 找最新的 pre-search backup
$backup = Get-ChildItem backend/app.db.pre-search-integration-* | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "Restoring from: $($backup.Name)"

# 3) 還原 app.db
Copy-Item -Force $backup.FullName backend/app.db
# 注意：search.db 不用刪，反正回到舊 code 不會碰它；留著下次再用

# 4) Git checkout 回 merge 前的 commit
git log --oneline | Select-Object -First 5    # 找出 merge commit 前一個的 SHA
git checkout <pre-merge-SHA>                   # 或 git revert <merge-commit>

# 5) 還原 frontend build（新 build 在 .next/，舊 build 沒留 → 重 build）
cd frontend
yarn install
yarn build
cd ..

# 6) 還原 backend deps
cd backend
uv sync
cd ..

# 7) 重啟
pm2 restart all
tailscale funnel status
curl https://kccw0077.tail138ec9.ts.net:8443/api/health
```

**Rollback 後該做：**
- 在 worktree 內排查問題，不要在 prod 主 checkout 修
- 確定問題前不要再 merge

### Step 6.6 — 上線後立刻做
- admin 帳號登入，把自己的 `search_enabled` 設 true
- 跑一次完整的 generation flow 驗證 prod 通

### Step 6.7 — 收尾
- worktree 移除：`git worktree remove C:\Users\226376\Desktop\data-search-module`
- 確認 `ecosystem.config.js`、Caddyfile、start-system.bat 都沒動
- 更新 `data/README.md` 加一節「鋼筋盤價助理模組」

### Step 6.8 — 舊 SEARCH 資料夾處理
- 新系統穩定執行 2 週後，把 `Desktop/SEARCH/` 移到 `Desktop/SEARCH.archive-DEPRECATED/`
- `SEARCH.archive-20260518/` 副本永久保留
- Git tag `archive/pre-rag-integration-20260518` 永久保留

---

## 跨 Phase 依賴關係

```
Phase 0 (準備 + worktree + SEARCH 備份 + commit/stash 未提交檔)
    ↓
Phase 1 (User schema + 權限)             ←─── 影響既有 RAG，最先做完
    ↓
Phase 2 (第二個 DB + migration script)   ←─── 純新增
    ↓
Phase 3 (業務核心 + 依賴 + reap stranded) ←─── 依賴 Phase 2 storage
    ↓
Phase 4 (API + ownership + 路由衝突檢查) ←─── 依賴 Phase 1 dep + Phase 3 業務
    ↓
Phase 5 (Frontend + RQ Provider + API 改寫 + 依賴) ←─── 依賴 Phase 4 API
    ↓
Phase 6 (backup + build + install + migrate + restart)
```

**關鍵依賴提醒：**
- §0.2 commit/stash → 0.4 worktree（不先做，Sidebar 必衝突）
- Phase 1 → Phase 4（API 需要 `require_search_permission`）
- Phase 2.3 migration → Phase 3.4 ORM（schema 對不上 ORM 對不上）
- Phase 3.0 deps → Phase 3.1（沒 httpx 等 import 就炸）
- Phase 5.0 deps → Phase 5.1 RQ Provider → Phase 5.2 元件搬家
- Phase 5.7 sidebar 入口最後做（前面沒接好放出來會 404）

---

## 可維護性原則

1. **邊界守紀律**：`app/modules/search/**` 只 import 自己 + `app.models.user` + `app.core.*` + `app.search_database` + `app.config`
2. **DB 完全隔離**：兩個 `Base`、兩個 session、不跨 transaction
3. **命名前綴**：URL `/search/`、`/admin/search-*`；CSS `--search-*`；TS type `Search*`
4. **設定集中**：所有 SEARCH 設定都在 `app/config.py` 同一個 `Settings`
5. **向 RAG 風格收斂**：sync → async；cookie auth → Bearer + refresh cookie；無 legacy adapter
6. **每 Phase 完成跑 smoke**：列在每 Phase 末尾的「驗收」
7. **Migration script 一次性**：標頭 `# ONE-SHOT`，跑完不維護
8. **文件不蓋既有 md**：SEARCH 的 SYSTEM.md / README.md 不搬

---

## 風險與緩解（v1.1）

| 風險 | 機率 | 緩解 |
|---|---|---|
| Migration script username 映射表沒填好 → 大量 NULL | 高 | 動工前先 dump 兩邊 users 對照；script 跑完印 audit log 看 NULL 比例 |
| 舊 -wal 資料漏掉 | 中 | 用 `sqlite3 .backup` API（會 auto-checkpoint） |
| LangGraph 1.x 跟 SEARCH 寫法不相容 | 中 | Phase 3.1.5 早期就跑一次 `build_graph()` |
| sync → async 漏改處塞住 event loop | 中 | Phase 3 結束時 debug 模式跑 smoke 看警告 |
| ORM schema 跟 search.db 對不上 | 中 | Phase 3.4 用 `.schema diff` 比對 |
| `@register` 沒跑到 | 低 | `app/modules/search/__init__.py` 顯式 import 各 adapter |
| Admin 自己沒權限沒辦法測 | 高 | Phase 1 完成立刻把自己 search_enabled 設 true（已允許自我 toggle） |
| `.env` 整併覆蓋 SECRET_KEY | 低 | Phase 0.6 用 diff 對照、只加不改 |
| Prod restart 中斷 | 低 | 6.4 離峰時段做；事先公告 |
| Frontend build 失敗才發現 dep 漏 | 中 | Phase 5.0 完成後馬上 `yarn build` 確認，不要拖到 6.4 |
| `api()` 改 axios 漏改一個元件 | 中 | 5.3 完成後 `grep -r 'api<' frontend/components/search/` 必須空 |
| API client baseURL 行為 `/api/api/` 雙前綴 | 中 | Phase 4.1 規則明確；E2E 測試實際 URL |
| 路由衝突 `/admin/{var}` 吃掉 `/admin/search-*` | 低 | Phase 4.0 強制 grep 既有 routes |
| `metadata.create_all` 用錯 sync API | 低 | Phase 3.8 範例已標明 `run_sync` |
| 既有未 commit 檔在 merge 時衝突 | 高 | Phase 0.2 強制 commit/stash |
| Caddyfile / ecosystem.config.js 被誤改 | 中 | Phase 6.2 sentinel diff check |
| 舊 docx 連結失效但使用者沒被告知 | 低 | 前端 download endpoint 拿到 404 時顯示「已過期，請重新產生」 |
| Worktree 內 .env 為空導致啟動失敗 | 高 | §0.6 先 copy 主 .env → 再 append SEARCH 變數，並驗證 settings 載入 |
| UUID 格式（hyphenated vs no-hyphen）不一致 → Ownership Check 永遠 404 | 中 | Migration script 規定走 SQL 抓 UUID，不手打；結尾 regex 驗證 |
| `_node_render` 跑 docx 時阻塞整個 event loop | 中 | Phase 3.6 用 `asyncio.to_thread` 包 `renderer.render` |
| 未來有人加 `relationship()` 後遇 MissingGreenlet | 低（防回歸） | Phase 3.4 標示硬規定 + 要加就同步加 `selectinload` |
| 未來有人把 `search_enabled` 改成從 JWT payload 讀 → 改完要重登 | 低（防回歸） | §1.4 明示禁止 + 為什麼禁止 |
| 上線後 RAG 完全壞但沒 rollback SOP | 高 | Step 6.5 緊急 rollback 程序 |

---

## 預估時程（單人開發）

| Phase | 工作量 | 主要消耗 |
|---|---|---|
| 0 | 45 分鐘 | 環境 + worktree + commit + 備份 |
| 1 | 1.5 小時 | Alembic + 前後端兩處改 |
| 2 | 2 小時 | 雙 engine + migration script（人工映射表 + WAL backup） |
| 3 | 4-5 小時 | sync→async 改寫 + LangGraph 升版排錯 |
| 4 | 2 小時 | API + ownership + 路由檢查 |
| 5 | 3-4 小時 | UI + RQ Provider + axios 改寫 + CSS |
| 6 | 1.5 小時 | backup + build + install + cutover |

**總計約 14-17 小時**，分 3 個工作天做完比較穩。

---

## 動工前 checklist

- [ ] 本計畫已被使用者 review（v1.1）
- [ ] data 主 checkout 三個 M 檔已 commit 或 stash
- [ ] SEARCH 已打 git tag `archive/pre-rag-integration-20260518`
- [ ] SEARCH 已 robocopy 一份到 `SEARCH.archive-20260518/`
- [ ] 已建立 worktree `data-search-module/` on branch `feat/search-module`
- [ ] worktree 內已驗證 backend:8002 / frontend:3001 可跑既有 RAG
- [ ] 已準備好 SEARCH 使用者名 → RAG UUID 對照表（用於 migration script）
- [ ] 已知會相關使用者 Phase 6 時會有 1-2 分鐘 restart
