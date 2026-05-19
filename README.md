# 營造知識助理

內部員工系統，目前整合兩個功能模組：

- **RAG 問答 + 表單代填**（原系統）— 營造規範檢索、Adaptive RAG、CRAG 閉環、靜態 / 動態表單下載與 AI 代填
- **鋼筋盤價助理**（SEARCH 模組）— 每週鋼筋採購週會 Word 自動產出：豐興開盤、國際廢鋼、中鋼月/季盤、各種敘述段落、歷史價格表

公開網址（內部用）：`https://kccc3798.tail138ec9.ts.net`

---

## 目錄

1. [整體架構](#整體架構)
2. [權限模型](#權限模型)
3. [模組 A：RAG 問答 + 表單](#模組-a-rag-問答--表單)
4. [模組 B：鋼筋盤價助理 (SEARCH)](#模組-b-鋼筋盤價助理-search)
5. [專案結構](#專案結構)
6. [技術棧](#技術棧)
7. [本地開發](#本地開發)
8. [生產部署 — PM2 + Caddy + Tailscale](#生產部署--pm2--caddy--tailscale)
9. [維運與已知地雷](#維運與已知地雷)
10. [延伸閱讀](#延伸閱讀)

---

## 整體架構

```
                       使用者瀏覽器
                            │
                            ▼
        https://kccc3798.tail138ec9.ts.net (Tailscale Funnel)
                            │
                            ▼
                      Caddy :9000
                            │
              ┌─────────────┴─────────────┐
              │                           │
        /api/* → :8000               其他 → :3000
              │                           │
              ▼                           ▼
        FastAPI backend            Next.js frontend
        (PM2: backend)             (PM2: frontend)
              │
              ├─ /api/auth/*               JWT 雙 token + bcrypt
              ├─ /api/chat/stream         SSE: LangGraph 串流回覆 (RAG)
              ├─ /api/conversations/*     CRUD + 對話狀態
              ├─ /api/forms/*             RAG 表單下載 / 填寫
              ├─ /api/admin/*             admin 後台 + search_enabled toggle
              ├─ /api/search/generation/* SEARCH 模組：產 docx 流程
              ├─ /api/search/csc/*        SEARCH 模組：中鋼盤價 seed
              └─ /api/admin/search-usage  SEARCH 模組：使用統計
              │
              ├─ app.db          ← RAG: users + conversations + messages + summaries
              ├─ langgraph.db    ← LangGraph state checkpointer
              ├─ chroma_db / chroma_versions   ← RAG 向量庫
              └─ search.db       ← SEARCH 模組獨立資料庫 (price_history / csc_* / generation_runs)
              │
              ├─ OpenAI API (gpt-5.4 + embedding)
              └─ steelnet.com.tw (SEARCH 模組爬蟲, 會員認證)
```

兩個模組**共用同一個 FastAPI 進程**、**同一個 Next.js bundle**、**同一份 .env**。SEARCH 是 RAG 的子模組 (`app/modules/search/`)，邊界靠模組獨立 DB + 命名空間維護（不跨 import RAG 內部）。

---

## 權限模型

每個 user 有三個獨立的 flag：

| 欄位 | 控制 |
|---|---|
| `is_active` | 整體登入；停用後立刻失效（token_version bump） |
| `role` (`user` / `admin`) | 是否能進 `/admin/*` |
| `search_enabled` | 是否能用鋼筋盤價助理；**admin 也預設關閉**，要自己開 |

`search_enabled` 由 admin 在 `/admin/users` 介面切換，**即時生效**（每次 request `get_current_user` 都從 DB 重抓）。

無權限的 user 點 sidebar「鋼筋盤價助理」會被 `/search/layout` 攔截 → 跳 `/search/no-access` 並顯示聯絡 admin 的 email。

---

## 模組 A：RAG 問答 + 表單

### 能力

- **問答**：營造規範、流程、條文檢索與整合回答（Adaptive + CRAG 閉環）
- **靜態表單下載**：對 3 份預建檢核表（動員開工 / 工務所辦公室設置 / 工地文件管制）一鍵下載空白檔
- **靜態表單 AI 代填**：自然語言描述要填的內容，agent 寫好回傳；支援 section 分組引導、批次編輯、跳段、AI 代寫
- **動態表單生成**：對沒有對應靜態表的需求，依 RAG context 即時生成結構化檢核表 / 報告書 / 計畫書 / 一般表格
- **動態表單匯出**：把上一輪生成的動態表單轉成 .xlsx 或 .csv（不重新打 LLM）

### LangGraph 流程

```
START
  └─► compact_check (token > 8000 觸發摘要)
        ├─ true ─► summarizer ─┐
        └─ false ──────────────┘
                                ▼
                      unified_intent (單 LLM call，輸出 6 種 intent)
                       │
                       ├─ static_form_download → responder → END
                       ├─ static_form_fill → form_template_loader
                       │                      ↓
                       │                  form_fill_collector
                       │                      ├─ status=ready → form_filler → responder → END
                       │                      └─ status=collecting → responder → END
                       ├─ dynamic_form_export → form_exporter (純檔轉換) → responder → END
                       ├─ qa (need_retrieval=false) → responder → END
                       └─ qa / dynamic_form_generate / form_continuation
                              ↓
                          retriever → context_builder → retrieval_grader
                              ├─ insufficient (retry < 2) → query_rewriter → retriever
                              └─ sufficient / max retries
                                    ├─ form 類 → form_structurer → responder → END
                                    └─ qa ────────────────────► responder → END
```

完整 mermaid 圖 + 每節點細說：[agent_flow.md](agent_flow.md)。

### 關鍵設計

| 設計 | 為什麼 |
|---|---|
| 6 種 intent 用單一 LLM call (`unified_intent`) | 取代舊版「2 個 keyword + LLM」混合架構，避免 keyword 互打架 |
| Hybrid RAG (intra-query Vector+BM25 RRF + inter-query rewrite RRF) | 兼顧語義 + 關鍵字 + CRAG 重寫融合 |
| Form fill 用 `bulk_edits.label_keywords` (AND) | mini 模型不必列舉 N 筆 JSON；code 自己枚舉欄位 → 穩定 |
| Token-based compaction at 8000 tokens | 保留最近 8 則 + 摘要寫 SQLite |
| `form_fill_session` 跨輪持久化 | 透過 LangGraph checkpointer，前端不用管 |

詳細：見舊版 [README.md (git history) `acbb6fa^`](#) 或 [agent_flow.md](agent_flow.md)。

---

## 模組 B：鋼筋盤價助理 (SEARCH)

### 能力

把過去手動產的「鋼筋採購週會記錄」Word 全自動化。流程是個 6 步驟 wizard，每個 user 自己跑：

```
1. 設定會議日期 → 選下週一
2. 抓取盤價       → LangGraph 跑 fetch/validate/persist (90-180s)
                    抓豐興開盤、國際廢鋼、西本指數、LME 銅、國內+大陸市場分析
3. 抓取結果       → 預覽所有 slot 與信心級別
4. 中鋼盤價       → 預填上次 admin 設的 seed，可 per-run 調整 (per user, per run)
5. 補內部資料      → 工程資訊、會議結論、合約量
6. 下載 Word      → 透過 python-docx 把 {{slot}} 填入模板，產出 .docx
```

### 架構

- **HTTP 路由**：`/api/search/generation/*` (user 自己的) + `/api/search/csc/*` (seed 讀寫) + `/api/admin/search-usage` (admin 限定)
- **DB**：獨立 `search.db`（不汙染 RAG 的 app.db）— 4 張表：`price_history` / `csc_price_state` / `csc_announcement_meta` / `generation_runs`
- **跨 DB 關聯**：`generation_runs.started_by` 存 user UUID（app.db 的 RAG users.id），沒有真正的 FK
- **背景執行**：POST `/run` 跟 POST `/internal-data` 都是 `asyncio.create_task` fire-and-forget，前端 polling `/{run_id}` 拿 status；LangGraph 跑 2-3 分鐘不會撐爆 HTTP timeout
- **權限**：所有 `/api/search/*` 端點掛 `Depends(require_search_permission)`，沒 search_enabled 就 403

### LangGraph 流程

```
START
  ├─ fetch    parallel: fengxing / weekly_market / market_narrator (httpx + AsyncOpenAI)
  ├─ validate flag low-confidence / missing values
  ├─ persist  write price_history (key by opening_monday)
  ├─ narrate  build slot_values + confidence dicts;
              read history & CSC seed (or csc_override from wizard)
  └─ render   asyncio.to_thread(python-docx) → write .docx
END
```

完整移植記錄、為什麼從原 SEARCH repo 整合進來的設計決策、cascade-delete 事故與修法：[SEARCH_INTEGRATION_PLAN.md](SEARCH_INTEGRATION_PLAN.md)。

### 模組邊界

`app/modules/search/` 只能 import：
- 自己內部
- `app.models.user` / `app.core.dependencies` / `app.core.security`
- `app.search_database` / `app.config`

**禁止** import RAG 的 `app.api.{chat,conversations,export}` / `app.graph.*` / `app.rag.*` / `app.models.{conversation,message,summary}`。RAG 側對稱地禁止 import `app.modules.search.*`，只有 `main.py` mount router 的地方除外。

---

## 專案結構

```
data/
├── README.md                       本檔
├── SEARCH_INTEGRATION_PLAN.md      SEARCH 整合計畫書 + post-mortem
├── agent_flow.md                   RAG LangGraph 詳細流程
├── DEPLOY.md / SETUP.md / PLAN.md  其他歷史文件
├── ecosystem.config.js             PM2 設定 (backend:8000 / frontend:3000)
├── start-system.bat                Windows 一鍵啟動 (PM2 + Caddy + Tailscale)
├── .env                            ← 不入 git；OpenAI / JWT / SMTP / SEARCH / steelnet
│
├── backend/
│   ├── pyproject.toml              uv 依賴
│   ├── alembic/versions/           schema migrations
│   ├── app.db                      ← RAG: users + conversations + messages + summaries
│   ├── search.db                   ← SEARCH 模組獨立 DB
│   ├── langgraph.db                LangGraph state checkpointer
│   ├── chroma_db / chroma_versions RAG 向量庫
│   ├── templates/                  SEARCH 用的 .docx 模板
│   │
│   ├── app/
│   │   ├── main.py                 FastAPI app + lifespan (含 SEARCH 模組 bootstrap)
│   │   ├── config.py / database.py 共用設定 / RAG DB engine
│   │   ├── search_database.py      SEARCH 第二個 SQLAlchemy engine
│   │   │
│   │   ├── api/                    RAG: auth / chat (SSE) / conversations / admin / export
│   │   ├── core/                   JWT / security / dependencies (含 require_search_permission)
│   │   ├── models/                 RAG: User (含 search_enabled) / Conversation / Message / Summary
│   │   ├── schemas/                Pydantic DTOs
│   │   ├── graph/                  RAG LangGraph 節點與 builder
│   │   ├── rag/                    向量檢索 / 表單 registry / 模板 schemas
│   │   ├── services/               業務邏輯層
│   │   ├── prompts/                所有 LLM prompt
│   │   │
│   │   └── modules/
│   │       └── search/             ←─── 鋼筋盤價助理整套
│   │           ├── core/           LangGraph orchestrator + slot_schema + dates
│   │           ├── sources/        fengxing / weekly_market / market_narrator (httpx)
│   │           ├── llm/            OpenAIClient (AsyncOpenAI + LangSmith wrap)
│   │           ├── output/         python-docx renderer
│   │           ├── storage/        async SQLAlchemy models + repos
│   │           └── api/            generation / csc / usage routers
│   │
│   └── scripts/
│       ├── 01_preprocess.py … 07   RAG 向量化 pipeline
│       ├── build_form_schemas.py   RAG 表單 schema 產生器
│       ├── inspect_form.py         RAG 表單結構 dump
│       ├── cleanup_orphan_forms.py RAG 對話刪除後的副作用清理
│       ├── dev.py                  Worktree dev launcher (port 8002)
│       ├── smoke_search_orchestrator.py    SEARCH 模組 CLI smoke test
│       └── migrate_search_db.py    一次性: SEARCH/app.db → data/search.db
│
└── frontend/
    ├── package.json                yarn 依賴 (Next 16 + React 19 + axios + RQ)
    ├── next.config.ts              /api/* rewrite → BACKEND_URL
    ├── .env.local                  ← 不入 git；BACKEND_URL / NEXT_PUBLIC_BACKEND_URL
    │
    ├── app/
    │   ├── layout.tsx              字體掛載 (Geist / Instrument Serif / Noto Serif TC / JetBrains Mono)
    │   ├── globals.css             RAG tokens + SEARCH 模組 namespaced tokens (--search-*)
    │   ├── (auth)/                 register / login / forgot-password / reset-password
    │   └── (app)/                  認證後 layout (Sidebar + QueryClientProvider)
    │       ├── new/                歡迎 / 首次輸入
    │       ├── chat/[id]/          RAG 對話頁
    │       ├── admin/              admin 後台 (含 search-usage)
    │       └── search/             SEARCH 模組
    │           ├── layout.tsx      權限 guard (search_enabled = false → no-access)
    │           ├── generate/       6 步驟 wizard
    │           └── no-access/      無權限提示
    │
    ├── components/
    │   ├── layout/Sidebar.tsx      雙模組共用 sidebar (新對話 + 鋼筋盤價助理 + Recents)
    │   ├── chat/                   RAG 訊息泡泡 / SourcesPanel / 表單元件
    │   └── search/                 SEARCH 模組 wizard / loading / step / CSC editor
    │
    ├── lib/
    │   ├── api.ts                  axios baseURL=/api + JWT interceptor
    │   ├── sse.ts                  SSE 直連 backend (繞 Next.js dev rewrites)
    │   └── search/types.ts         SEARCH 模組 DTO types (Search* prefix)
    │
    ├── store/                      Zustand (auth / chat)
    └── types/                      RAG TypeScript DTOs
```

---

## 技術棧

### 後端 (`backend/pyproject.toml`)

| 類別 | 套件 |
|---|---|
| Web Framework | FastAPI |
| Agent / 狀態機 | LangGraph 1.x + LangChain |
| LLM | OpenAI gpt-5.4 系列 + AsyncOpenAI + LangSmith trace wrap |
| Embedding | text-embedding-3-small |
| 向量 DB | ChromaDB (PersistentClient, 版本化路徑) |
| BM25 | rank-bm25 + jieba (4,948 個營造業詞典) |
| 文件處理 | python-docx (RAG 表單代填 + SEARCH 模組 docx render) |
| HTTP | httpx (AsyncClient — SEARCH 爬蟲) |
| HTML 解析 | beautifulsoup4 + lxml (SEARCH 爬蟲) |
| 重試 | tenacity (SEARCH 爬蟲) |
| ORM | SQLAlchemy 2 (async) + aiosqlite |
| Migration | Alembic (`render_as_batch=False` for 含 FK 的表 — 見 §維運) |
| 認證 | python-jose JWT + bcrypt |
| Rate limit | slowapi |
| SMTP | aiosmtplib (密碼重設信) |

### 前端 (`frontend/package.json`)

| 類別 | 套件 |
|---|---|
| Framework | Next.js 16 (App Router) + React 19 + TypeScript |
| 樣式 | Tailwind v4 + tw-animate-css |
| Data fetching | axios + @tanstack/react-query (SEARCH 模組) |
| 狀態 | Zustand (auth / chat) + React Query (SEARCH wizard) |
| 表單 | react-hook-form + zod + @hookform/resolvers |
| UI | shadcn (base-ui) + lucide-react + recharts |
| Markdown | react-markdown + remark-gfm |
| 字體 | Geist / Geist Mono / Instrument Serif / JetBrains Mono / Noto Serif TC (sidebar 標題) |

---

## 本地開發

完整一鍵 setup：見 [SETUP.md](SETUP.md)。簡化版：

```bash
# 1. clone + env
git clone <repo>
cd data
cp .env.example .env
# 補 OPENAI_API_KEY / SECRET_KEY / STEELNET_USER/PASSWORD 等

# 2. backend
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. frontend (另一個 terminal)
cd frontend
yarn install
yarn dev      # 預設 3000

# 4. 知識庫 (第一次或更新時)
cd backend
uv run python scripts/01_preprocess.py
uv run python scripts/02_chunk.py
uv run python scripts/05_embed_ingest.py
```

開瀏覽器到 `http://localhost:3000`，註冊帳號後直接用。

### Worktree 隔離 dev (整合期使用過、現在可省略)

整合 SEARCH 模組期間用過 `data-search-module/` worktree 跑在 8002/3001 避免撞 prod。若以後要做大改動可重複此 pattern，見 [SEARCH_INTEGRATION_PLAN.md §0.3](SEARCH_INTEGRATION_PLAN.md)。

---

## 生產部署 — PM2 + Caddy + Tailscale

### 拓樸

```
網際網路
    │
    ▼  https://kccc3798.tail138ec9.ts.net (HTTPS — Tailscale 簽憑證)
Tailscale Funnel
    │
    ▼  本機 :9000
Caddy
    │  /api/*  →  127.0.0.1:8000  (FastAPI)
    │  /       →  127.0.0.1:3000  (Next.js prod build)
    │
PM2 (常駐)
    ├─ backend     uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
    └─ frontend    next start -H 0.0.0.0 -p 3000
```

`ecosystem.config.js` 描述 PM2 兩個 process。`C:\caddy\Caddyfile` 是反向代理（簡單兩條規則，不在 git 內）。

### 一鍵啟動

```powershell
# 開新 PowerShell (UAC 會跳出來，要按是) 跑 start-system.bat
.\start-system.bat
```

start-system.bat 流程：
1. `pm2 delete all` 然後 `pm2 start ecosystem.config.js`
2. 等 backend:8000 + frontend:3000 真的 listen
3. 殺舊 Caddy + 啟動新的（防止 Caddy 對舊上游 cache 502）
4. `tailscale funnel --bg 9000` 開放外網

### 手動操作

```powershell
pm2 restart all                # 只重啟 process，不動 Caddy / Tailscale
pm2 logs backend --lines 100   # 看 stdout（含 [Startup] 印的 SEARCH_DB_PATH）
pm2 logs backend --err         # 看 stderr（exception trace）
pm2 stop backend               # 停（緊急用）
pm2 list                       # 看 status / uptime / restart count
```

### 部署新版（cutover SOP）

> 整合 SEARCH 模組那次的詳細步驟、event order、rollback、cascade-delete 事故都在 [SEARCH_INTEGRATION_PLAN.md Phase 6](SEARCH_INTEGRATION_PLAN.md)。任何牽涉 schema migration 的部署前，務必照那份做。

通用版：

```powershell
cd C:\Users\226376\Desktop\data

# 1. 備份 (照原本命名習慣)
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
cp backend/app.db "backend/app.db.pre-deploy-$ts"

# 2. 拉新 code
git pull

# 3. backend deps + DB migration
cd backend
uv sync
uv run alembic upgrade head    # ⚠ schema migration 前先讀 §維運的 SQLite cascade 陷阱
cd ..

# 4. frontend deps + prod build (next start 讀 .next/，不 build 就不會更新)
cd frontend
yarn install
yarn build
cd ..

# 5. 重啟 PM2
pm2 restart all

# 6. 驗證
tailscale funnel status
curl https://kccc3798.tail138ec9.ts.net/api/health
```

---

## 維運與已知地雷

### 🔴 SQLite cascade-delete via `batch_alter_table` (歷史地雷)

整合 SEARCH 模組那次 alembic migration 用 `batch_alter_table` 在 SQLite 上 ADD COLUMN，導致 cascade-delete 砍掉 52 個 conversation + 321 個 message。

**根因**：`batch_alter_table` 在 SQLite 上是「CREATE _new + INSERT SELECT + DROP old + RENAME」。`DROP TABLE users` 觸發 ON DELETE CASCADE → users → conversations → messages → conversation_summaries 整條鏈被砍光。

**修法**：alembic migration 寫 `op.add_column(...)` 而**不要**用 `batch_alter_table`。SQLite 原生 ADD COLUMN with NOT NULL DEFAULT 從 3.2 就有。詳細 [commit fdcb726](#)。

**Schema migration 前的 SOP**：
1. **一定先備份 `app.db`** (帶 timestamp 命名跟既有 backup 一致)
2. 看 migration 是否動到 `users` / `conversations` 表
3. 是的話，**避免用 `batch_alter_table`**，改用 `op.add_column` / `op.execute(raw SQL)` 或乾脆 `PRAGMA foreign_keys=OFF` 包起來
4. 在 worktree 跑過一遍才上 prod

### 🔴 SQLite WAL/SHM 殘留導致 schema 視角錯亂

restore app.db 從備份蓋回時，舊的 `app.db-wal` / `app.db-shm` 還在，新連線會被它們蒙蔽看到舊 schema。

**症狀**：alembic 印 "已加 search_enabled column"，sqlite3 query 看得到欄位，但 aiosqlite 透過 SQLAlchemy 進來就說 "no such column"。

**修法**：每次 `cp backup app.db` 後**手動刪** `-wal` 跟 `-shm`：
```powershell
Remove-Item app.db-wal, app.db-shm -Force -ErrorAction SilentlyContinue
```

### 🟡 SEARCH 的 SSE 直連 backend (不走 Next.js rewrites)

`lib/sse.ts` 對 `/api/chat/stream` 跟 SEARCH 的長 polling 都是**直連** backend，繞過 Next.js dev rewrites（dev rewrite 有 response buffering、會切斷 SSE）。

→ 後果是 backend 的 CORS 必須允許 frontend 的 origin。`CORS_ORIGINS` 在 `.env` 設好。

### 🟡 PM2 frontend 不會自動 hot-reload

`next start` 啟動時讀一次 `.next/`，之後不會 watch 變更。修 code 後一定要：
```powershell
cd frontend ; yarn build ; cd .. ; pm2 restart frontend
```

### Backup 命名規範

| Pattern | 用途 |
|---|---|
| `app.db.backup-YYYYMMDD-HHMMSS` | 一般定期備份 |
| `app.db.pre-<feature>-YYYYMMDD-HHMMSS` | 重大變更前 (alembic 升級、重新 build) |
| `app.db.snapshot-before-rollback-...` | rollback 前的最後一份 |
| `app.db.broken-<reason>-...` | 出事的當下保存 (forensic) |

`.gitignore` 內 `*.db.backup-* / *.db.pre-* / *.db.snapshot-*` 都已排除 — 不會誤入 git。

### 對話刪除的副作用清理

`delete_conversation` 已自動清 `data/generated_forms/<conv_id>_*.docx` + langgraph.db checkpoint。但若直接 SQL DELETE 沒走 service 層，會留 orphan：

```bash
cd backend
uv run python scripts/cleanup_orphan_forms.py            # dry-run
uv run python scripts/cleanup_orphan_forms.py --apply    # 真刪
```

### LangSmith Tracing

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=LangGraph-RAG
```

每個 node 的 input / output / latency / token / cost 都會自動上 [LangSmith](https://smith.langchain.com)。RAG 的 `unified_intent` 三段 log (INPUT / LLM / STATE) 跟 SEARCH 的所有 OpenAI call (LangSmith.wrap_openai) 都會出現。

---

## 延伸閱讀

| 文件 | 內容 |
|---|---|
| [SETUP.md](SETUP.md) | 從零 clone 到跑起來的完整步驟 |
| [agent_flow.md](agent_flow.md) | RAG LangGraph 流程 mermaid + 每節點 system prompt 摘要 |
| [SEARCH_INTEGRATION_PLAN.md](SEARCH_INTEGRATION_PLAN.md) | SEARCH 模組從獨立 repo 整合進來的完整計畫 + post-mortem（cascade-delete + WAL）|
| [DEPLOY.md](DEPLOY.md) | Docker 容器化部署的歷史方案 (現在用 PM2 直跑、保留供參考) |
| [PLAN.md](PLAN.md) | RAG 系統原始計畫書 |
| `system.md` (worktree internal) | LangGraph node 設計筆記 (尚未 commit) |
