# 營造知識助理 — LangGraph RAG System

以營造工程管理知識為核心的企業內部 AI 助理。整合兩個功能模組:

- **RAG 問答 + 表單代填**(主系統)— 營造規範檢索(Adaptive RAG + CRAG 閉環 + Hybrid 檢索)、
  圖片理解(VLM)、聊天文件上傳即問即答、靜態 / 動態表單下載與 AI 代填
- **鋼筋盤價助理**(SEARCH 模組)— 每週鋼筋採購週會 Word 自動產出

> 🏗 **系統架構、演算法設計、LangGraph 流程圖、GraphState、意圖控制流的完整說明
> → [SYSTEM.md](SYSTEM.md)**

---

## 目錄

1. [功能總覽](#功能總覽)
2. [整體架構](#整體架構)
3. [設計流程](#設計流程)
4. [專案結構](#專案結構)
5. [技術棧](#技術棧)
6. [本地開發](#本地開發)
7. [生產部署](#生產部署)
8. [維運與已知地雷](#維運與已知地雷)
9. [延伸閱讀](#延伸閱讀)

---

## 功能總覽

### RAG 問答

- **規範問答**:51 份營造規範文件的語意檢索與整合回答,Hybrid 檢索
  (向量 + BM25 + RRF 融合)+ CRAG 自我修正閉環(grader 評估 → query 改寫 → 重檢索)
- **圖片理解(VLM)**:上傳工地照片 / 表單截圖,Gemini OCR + 描述併入檢索,
  responder 同時 grounding 原圖;多輪沿用「最近一張」
- **聊天文件上傳**:對話中附 PDF / Word / PPT,MarkItDown 轉 Markdown →
  切塊 → embed 進**對話專屬**向量索引(`session_{conversation_id}`),
  retriever 同時查知識庫與該索引;文件不進全域知識庫
- **語音輸入(STT)**:錄音 → Gemini 轉文字 → 填回輸入框

### 表單能力

- **靜態表單下載**:預建檢核表一鍵下載空白 .docx
- **靜態表單 AI 代填**:自然語言描述,agent 分組引導收集欄位 → 寫入模板回傳;
  支援批次編輯、跳段、AI 代寫
- **動態表單生成**:無對應靜態表時,依 RAG context 即時生成結構化表單
- **動態表單匯出**:上一輪生成的表單轉 .xlsx / .csv(不重打 LLM)

### 鋼筋盤價助理(SEARCH 模組)

6 步驟 wizard:設定會議日期 → 抓盤價(豐興 / 國際廢鋼 / 西本 / LME,LangGraph
平行爬取 90–180s)→ 預覽 → 中鋼 seed 調整 → 補內部資料 → 產出週會 Word。
獨立 `search.db`、獨立權限(`search_enabled`)、模組邊界禁止跨 import RAG 內部。

---

## 整體架構

```
                       使用者瀏覽器
                            │
                            ▼
              Tailscale Funnel (HTTPS) → Caddy :9000
                            │
              ┌─────────────┴─────────────┐
        /api/* → :8000               其他 → :3000
              ▼                           ▼
        FastAPI backend            Next.js 16 frontend
              │
              ├─ /api/auth/*                JWT 雙 token + bcrypt
              ├─ /api/chat/stream           SSE: LangGraph 串流回覆
              ├─ /api/chat/upload           圖片上傳(VLM)
              ├─ /api/chat/upload-document  文件上傳(PDF/DOCX/PPTX → session 索引)
              ├─ /api/conversations/*       對話 CRUD
              ├─ /api/forms/*               表單下載 / 已填寫檔
              ├─ /api/admin/*               admin 後台
              └─ /api/search/*              SEARCH 模組
              │
              ├─ app.db                     users / conversations / messages / summaries
              ├─ PostgreSQL                 LangGraph checkpointer(thread_id = conversation_id)
              ├─ chroma_db / chroma_versions  知識庫向量 + session_{conv_id} 文件索引
              ├─ uploads/{user_id}/         上傳圖片與文件原檔
              └─ search.db                  SEARCH 模組獨立 DB
```

兩個模組共用同一個 FastAPI 進程、同一個 Next.js bundle、同一份 `.env`。

### 權限模型

| 欄位 | 控制 |
|---|---|
| `is_active` | 整體登入;停用即時失效(token_version bump) |
| `role`(user / admin) | 是否能進 `/admin/*` |
| `search_enabled` | 鋼筋盤價助理使用權;admin 也預設關閉,由 admin 介面切換、即時生效 |

---

## 設計流程

完整細節在 [SYSTEM.md](SYSTEM.md),這裡是鳥瞰圖。

### 一輪對話的生命週期

```
使用者送出訊息(可附圖片 id / 文件 id)
  → chat_stream:驗證所有權 → 存 user 訊息 → 載入摘要與前輪附件參照 → 組 initial_state
  → LangGraph 執行:
      vision_intake(有圖讀圖)→ compact_check(>8000 tokens 觸發摘要)
      → unified_intent(單一 LLM call 六分類 + need_retrieval)
      → [依 intent 分流] 檢索(KB + session 索引 RRF)→ CRAG 閉環(grader/rewriter,上限 2 次)
      → responder ∥ source_filter(並行)
  → SSE 逐 token 推送 → graph 完成推 sources / form_files → 存 assistant 訊息
```

### 知識庫建置(離線)

```
data_markdown/*.md → 清理 → 智慧切塊(類型 A/B/C,80–1000 tokens)
  → metadata 生成與審核 → embedding → ChromaDB(版本化)→ 驗證
```

線上系統對知識庫**只讀**;更新知識庫 = 重跑 scripts pipeline + admin 觸發 BM25 rebuild。

### 聊天文件上傳(線上)

```
PDF/DOCX/PPTX → 驗證(mime/20MB/magic bytes)→ MarkItDown 轉 Markdown
  → 通用 chunker(標題切分 + token 上限)→ 批次 embed → session_{conv_id} collection
  → retriever 之後每輪自動「KB + session」雙路檢索 RRF 融合
```

設計取捨:索引在 upload endpoint 內同步完成(回傳即可檢索),graph 零新增節點;
掃描型 PDF 抽不出文字 → 明確 400 引導改用圖片上傳(走 VLM OCR);
刪對話連動刪 session 索引,30 天自動清理。

### 關鍵設計決策

| 設計 | 為什麼 |
|---|---|
| 六種 intent 用單一 LLM call + code 越界防護 | 取代 keyword 混合架構,避免字面誤判與 keyword 膨脹 |
| Hybrid 檢索(向量 + BM25 jieba + RRF) | 語意與關鍵字互補;RRF 可變參數設計讓 session / 改寫多路共用同一融合 |
| CRAG rewriter 永遠基於原始 query 改寫 | 防多輪重試語意漂移 |
| responder ∥ source_filter 並行 | 來源過濾用 query 評估(不依賴 response),延遲被生成時間遮蔽 |
| 重資料不進 graph state | 圖片 base64 / 文件全文不進 checkpoint,只放路徑/id 參照 |
| 新文件上傳清除圖片沿用鏈 | 防「總結此檔案」被前輪舊圖綁架(實際踩過的 bug) |
| `form_fill_session` 走 checkpointer 跨輪持久化 | 前端不用管多輪填表狀態 |

---

## 專案結構

```
LangGraph_RAG_SYSTEM/
├── README.md                       本檔
├── SYSTEM.md                       系統架構與設計說明(mermaid 流程圖)
├── ecosystem.config.js             PM2 設定
├── .env                            ← 不入 git
│
├── backend/
│   ├── pyproject.toml              uv 依賴
│   ├── alembic/versions/           schema migrations
│   │
│   ├── app/
│   │   ├── main.py                 FastAPI app + lifespan(graph 編譯 / 清理任務)
│   │   ├── config.py               pydantic-settings(.env)
│   │   ├── api/                    auth / chat(SSE + 上傳)/ conversations / admin / export
│   │   ├── core/                   JWT / security / LLM factory(get_llm)
│   │   ├── graph/
│   │   │   ├── builder.py          StateGraph 組裝 + 條件路由
│   │   │   ├── state.py            GraphState(TypedDict)
│   │   │   └── nodes/              15 個節點(vision / intent / retrieval / grader / form / ...)
│   │   ├── rag/
│   │   │   ├── vector_store.py     ChromaDB client + embedding(LRU cache)
│   │   │   ├── retriever.py        Hybrid 檢索 + RRF + BM25(jieba)
│   │   │   ├── session_store.py    對話專屬文件索引(session_{conv_id})
│   │   │   ├── doc_chunker.py      上傳文件通用 chunker
│   │   │   └── form_lookup.py      靜態表單 registry
│   │   ├── services/               image_store / document_store / upload_guard /
│   │   │                           conversation_service / form_fill_writer / ...
│   │   ├── prompts/                所有 LLM prompt(版本化)
│   │   └── modules/search/         鋼筋盤價助理(獨立模組)
│   │
│   ├── scripts/                    01–07 知識庫 ingestion pipeline + 工具
│   └── tests/                      pytest(unified_intent / doc_chunker)
│
├── frontend/
│   ├── app/(auth)/                 register / login / 密碼重設
│   ├── app/(app)/                  new(歡迎頁)/ chat/[id] / admin / search
│   ├── components/chat/            InputBar / MessageBubble / DocumentCard /
│   │                               FormPickerButton / SourcesPanel / ...
│   ├── lib/                        api(axios+JWT)/ sse(直連 backend)
│   ├── store/                      Zustand(auth / chat)
│   └── types/                      TypeScript DTOs
│
└── data_markdown/                  知識庫原始 Markdown(51 份)+ 圖片
```

---

## 技術棧

### 後端

| 類別 | 套件 |
|---|---|
| Web | FastAPI + uvicorn |
| Agent 狀態機 | LangGraph 1.x + LangChain |
| LLM | OpenAI gpt-5.4 系列(主)+ Gemini 3.5 Flash(VLM / STT),由 `get_llm()` factory 依 .env 切換 |
| Embedding | text-embedding-3-small |
| 向量 DB | ChromaDB(PersistentClient,版本化路徑 + session collections) |
| 關鍵字檢索 | rank-bm25 + jieba(4,948 詞營造領域詞典) |
| 文件解析 | markitdown(PDF/DOCX/PPTX → Markdown) |
| 文件產出 | python-docx / openpyxl |
| Checkpointer | langgraph-checkpoint-postgres(SQLite fallback) |
| ORM | SQLAlchemy 2(async)+ aiosqlite + Alembic |
| 認證 | python-jose JWT + bcrypt;slowapi rate limit |
| 觀測 | LangSmith tracing |

### 前端

| 類別 | 套件 |
|---|---|
| Framework | Next.js 16(App Router)+ React 19 + TypeScript |
| 樣式 | Tailwind v4 |
| 狀態 | Zustand(auth / chat)+ React Query(SEARCH) |
| UI | shadcn + lucide-react + react-markdown(GFM) |

---

## 本地開發

```bash
# 1. clone + env
git clone https://github.com/Tsai1030/LangGraph_RAG_SYSTEM.git
cd LangGraph_RAG_SYSTEM
cp .env.example .env   # 補 OPENAI_API_KEY / GOOGLE_API_KEY / SECRET_KEY 等

# 2. backend
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. frontend(另一個 terminal)
cd frontend
yarn install
yarn dev               # http://localhost:3000

# 4. 知識庫(第一次或文件更新時)
cd backend
uv run python scripts/01_preprocess.py
uv run python scripts/02_chunk.py
uv run python scripts/05_embed_ingest.py

# 5. 測試
cd backend
uv run pytest tests/ -q
```

---

## 生產部署

拓樸:**Tailscale Funnel(HTTPS)→ Caddy :9000 → FastAPI :8000 / Next.js :3000(PM2)**

```powershell
# 部署新版
git pull
cd backend ; uv sync ; uv run alembic upgrade head ; cd ..
cd frontend ; yarn install ; yarn build ; cd ..   # next start 讀 .next/,不 build 不會更新
pm2 restart all
curl https://<host>/api/health
```

> ⚠ **COMODO EDR 限制**:本機環境不能用 PM2 spawn backend(python 子行程被擋,
> WSAEACCES 10013)。backend 必須由使用者前景 terminal 手動
> `uv run python run_server.py`,PM2 只跑 frontend。詳見 db.md §8.4。

---

## 維運與已知地雷

### 🔴 SQLite cascade-delete via `batch_alter_table`

歷史事故:alembic 用 `batch_alter_table` 在 SQLite ADD COLUMN,其「CREATE 新表 +
DROP 舊表」觸發 ON DELETE CASCADE 砍掉整條 conversations 鏈。
**SOP**:schema migration 前必備份 `app.db`;動到 `users` / `conversations` 的
migration 用 `op.add_column` / raw SQL,**不要用** `batch_alter_table`。

### 🔴 SQLite WAL/SHM 殘留

從備份還原 `app.db` 後,舊的 `-wal` / `-shm` 會讓新連線看到舊 schema。
還原後必刪:`Remove-Item app.db-wal, app.db-shm -Force`

### 🟡 SSE 直連 backend

`lib/sse.ts` 繞過 Next.js rewrites(rewrites 有 response buffering 會斷 SSE),
直連 backend → `.env` 的 `CORS_ORIGINS` 必須含前端 origin。

### 🟡 PM2 frontend 不會 hot-reload

`next start` 只讀啟動時的 `.next/`。改前端後:`yarn build` → `pm2 restart frontend`。

### 清理機制(自動)

- 每日背景任務:30 天以上的上傳圖片 / 文件、產出表單檔、session 向量索引
- 刪除對話:連動清 checkpoint thread、generated_forms、session collection
- 直接 SQL DELETE 繞過 service 層會留 orphan → `scripts/cleanup_orphan_forms.py`

### LangSmith Tracing

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=LangGraph-RAG
```

每個 node 的 input / output / latency / token / cost 自動上 LangSmith。

---

## 延伸閱讀

| 文件 | 內容 |
|---|---|
| [SYSTEM.md](SYSTEM.md) | **系統架構 / 演算法 / LangGraph 流程 / GraphState / 意圖控制流(mermaid)** |
| [SETUP.md](SETUP.md) | 從零 clone 到跑起來 |
| [agent_flow.md](agent_flow.md) | 歷史版 LangGraph 流程筆記 |
| [SEARCH_INTEGRATION_PLAN.md](SEARCH_INTEGRATION_PLAN.md) | SEARCH 模組整合計畫 + post-mortem |
| [DEPLOY.md](DEPLOY.md) | Docker 部署歷史方案 |
