# 營造知識助理 — LangGraph RAG System

營造業內部知識問答系統，整合 RAG 檢索、LangGraph 狀態機、串流回覆與結構化表單生成。

---

## 目錄

1. [系統概覽](#系統概覽)
2. [技術棧](#技術棧)
3. [系統架構](#系統架構)
4. [LangGraph 狀態機設計](#langgraph-狀態機設計)
5. [RAG 檢索設計](#rag-檢索設計)
6. [記憶系統設計](#記憶系統設計)
7. [資料庫設計](#資料庫設計)
8. [傳輸層設計](#傳輸層設計)
9. [安全性設計](#安全性設計)
10. [前端設計](#前端設計)
11. [專案結構](#專案結構)
12. [環境設定與啟動](#環境設定與啟動)

---

## 系統概覽

```
使用者 → 前端 (Next.js) → FastAPI → LangGraph
                                       ├─ RAG 檢索 (ChromaDB + BM25)
                                       ├─ 意圖分類
                                       ├─ 回覆生成 / 表單生成 (OpenAI)
                                       └─ 記憶壓縮 (token-based compaction)
                                   ↓
                              SQLite (對話記錄 + 摘要)
                              ChromaDB (向量索引)
                              langgraph.db (對話 state checkpoint)
```

---

## 技術棧

### 後端
| 類別 | 套件 |
|------|------|
| Web Framework | FastAPI |
| 狀態機 / Agent | LangGraph、LangChain |
| LLM / Embedding | OpenAI API（GPT、text-embedding-3-small） |
| 向量資料庫 | ChromaDB（本地持久化） |
| BM25 搜尋 | rank-bm25 |
| 中文分詞 | jieba（含自訂領域詞典） |
| Token 計算 | tiktoken |
| ORM | SQLAlchemy（Async）+ aiosqlite |
| Migration | Alembic |
| 認證 | python-jose（JWT）、bcrypt |
| 匯出 | openpyxl（Excel） |

### 前端
| 類別 | 套件 |
|------|------|
| Framework | Next.js 15（App Router）、TypeScript |
| 樣式 | Tailwind CSS |
| 狀態管理 | Zustand |
| Markdown 渲染 | react-markdown、remark-gfm |
| UI 元件 | shadcn/ui |

---

## 系統架構

```
data/
├── backend/                # FastAPI 後端
│   ├── app/
│   │   ├── api/            # REST + SSE 端點（auth / conversations / chat / images）
│   │   ├── core/           # 安全性（JWT、bcrypt）
│   │   ├── graph/          # LangGraph 狀態機
│   │   │   ├── builder.py  # 組裝 StateGraph
│   │   │   ├── state.py    # GraphState TypedDict
│   │   │   └── nodes/      # 各節點邏輯
│   │   ├── models/         # SQLAlchemy ORM 模型
│   │   ├── rag/            # 檢索層（向量 + BM25）
│   │   ├── services/       # 業務邏輯（對話 CRUD、摘要）
│   │   ├── config.py       # Pydantic Settings（環境變數）
│   │   ├── database.py     # 非同步資料庫引擎
│   │   └── main.py         # FastAPI 應用與 lifespan
│   ├── alembic/            # 資料庫 migration
│   └── scripts/            # 向量資料建置腳本
├── frontend/               # Next.js 前端
│   ├── app/                # App Router 頁面
│   ├── components/         # 共用元件（chat / layout / form）
│   ├── lib/                # API 工具、SSE 串流
│   └── store/              # Zustand 全域狀態
└── data_markdown/          # 知識庫原始 Markdown 文件
```

---

## LangGraph 狀態機設計

### GraphState

```python
class GraphState(TypedDict):
    query: str                    # 使用者輸入
    messages: Annotated[list[BaseMessage], add_messages]  # 對話歷史（含 reducer）
    context: str                  # RAG 組裝的參考文件
    retrieved_chunks: list[dict]  # 原始 chunk 清單
    sources: list[dict]           # 格式化來源（供前端 SourcesPanel）
    intent: str                   # 'qa' | 'form_request'
    response: str                 # 生成的回覆
    form_data: dict | None        # 結構化表單 JSON
    summary: str                  # 長期記憶摘要
    token_count: int              # 當前 messages token 數
    is_compact_needed: bool       # 是否觸發壓縮
    conversation_id: str          # 對應 SQLite conversation ID
```

### 流程圖

```
START
  └─► compact_check（同步：tiktoken 計算 token 數）
        ├─ token > 8000 ──► summarizer（壓縮舊訊息 → 生成摘要 → 寫入 SQLite）
        └─ token ≤ 8000 ──► retriever（Hybrid RAG 檢索）
                                  ↓
                           context_builder（組裝 context string）
                                  ↓
                           intent_classifier（關鍵字 → LLM 語意分類）
                                  ├─ form_request ──► form_structurer（JSON 表單生成）
                                  │                         ↓
                                  └─ qa ──────────────► responder（串流回覆 SSE）
                                                              ↓
                                                           END
```

### 節點說明

| 節點 | 類型 | 功能 |
|------|------|------|
| `compact_check` | 同步 | tiktoken 計算 token 數，判斷是否超過 8000 token 閾值 |
| `summarizer` | 非同步 | 保留最近 8 則訊息，將舊訊息壓縮成 300 字摘要，RemoveMessage 刪除舊訊息，摘要寫入 SQLite |
| `retriever` | 非同步 | Hybrid 搜尋（向量 top-20 + BM25 top-20），RRF 融合後回傳 top-8 |
| `context_builder` | 同步 | 將 chunks 格式化為 LLM 可讀的 context string，注入 Markdown 圖片語法 |
| `intent_classifier` | 非同步 | 關鍵字快速判斷（form / qa），模糊時 LLM 語意分類 |
| `form_structurer` | 非同步 | 依據 context 生成結構化 JSON 表單（可匯出 Excel） |
| `responder` | 非同步 | ChatOpenAI streaming=True，astream_events 捕捉逐 token 推送 SSE |

### 條件路由

```python
def _route_compact(state):
    return "summarizer" if state["is_compact_needed"] else "retriever"

def _route_intent(state):
    return "form_structurer" if state["intent"] == "form_request" else "responder"
```

### CheckPointer（短期記憶持久化）

- 使用 LangGraph 內建 `AsyncSqliteSaver`
- 每個 conversation 對應唯一 `thread_id = conversation_id`
- 狀態持久化於獨立的 `langgraph.db`（與業務資料庫分離）
- 啟動時 `await checkpointer.setup()` 自動建表
- 支援中斷恢復：重新連線同一 `thread_id` 可繼續對話上下文

---

## RAG 檢索設計

### Hybrid Search 架構

```
query
  ├─ OpenAI Embedding → ChromaDB 向量搜尋（top-20）
  └─ jieba 分詞 → BM25 關鍵字搜尋（top-20）
        ↓
   RRF（Reciprocal Rank Fusion，k=60）
        ↓
   merged top-8 chunks
```

### 向量搜尋

- 模型：`text-embedding-3-small`（OpenAI）
- 資料庫：ChromaDB PersistentClient，本地存儲
- 版本化設計：`chroma_versions/v1/` 等路徑，支援熱切換版本（`chroma_active_version` 設定）
- ChromaDB 為同步 API，以 `asyncio.to_thread` 包裝避免阻塞 FastAPI event loop

### BM25 搜尋

- 套件：`rank_bm25`（BM25Okapi）
- **Lazy 初始化**：第一次 query 時載入全部 chunks 建索引，之後 singleton 快取
- **分詞器**：jieba + 領域自訂詞典（4,948 個營造業專有名詞，從 chunks 的 tags 欄位自動產生）
- 解決純向量搜尋對條文編號、專業術語語意落差的問題

### RRF 融合

```python
score(d) = Σ 1 / (k + rank(d))   # k=60
```

- 兩路各取 top-20，以 ChromaDB document ID 去重後合併排序
- 最終回傳 top-8 chunks

### Chunk 資料結構

每個 chunk 包含以下 metadata：

```json
{
  "chunk_id": "uuid",
  "source_file": "010101動員開工作業檢核表",
  "section_code": "010101",
  "chapter": "01",
  "phase": "工務所設置管理",
  "document_type": "checklist",
  "tags": ["動員開工", "初期計畫", "採購發包"],
  "parent_h1": "",
  "parent_h2": "檢核表",
  "has_images": false,
  "image_paths": [],
  "token_count": 1720
}
```

---

## 記憶系統設計

### 雙層記憶架構

```
短期記憶（LangGraph）          長期記憶（SQLite）
─────────────────────          ──────────────────
add_messages reducer           conversation_summaries 表
RemoveMessage 動態刪除          upsert_summary() 更新
AsyncSqliteSaver 持久化         每次壓縮後覆寫摘要
thread_id = conversation_id     300 字繁體中文前情提要
```

### 短期記憶（LangGraph State）

- `messages` 欄位使用 `add_messages` reducer，自動合併 HumanMessage / AIMessage
- `RemoveMessage(id=msg.id)` 可從 state 中刪除指定訊息
- 每次對話恢復時，LangGraph 從 `langgraph.db` 載入完整 state

### 長期記憶（Token-Based Compaction）

**觸發條件：** 對話 token 數超過 **8,000 tokens**

**壓縮流程：**

1. `compact_check`：tiktoken（cl100k_base）計算全部 messages 的 token 數
2. 超過閾值 → 進入 `summarizer` 節點
3. 保留最近 **8 則訊息**（約 4 輪對話），其餘視為「舊訊息」
4. 將舊訊息格式化為 `使用者：{content}\nAI 助理：{content}` 的對話文字
5. 呼叫 LLM 生成 ≤300 字繁體中文前情提要
6. `RemoveMessage` 批量刪除舊訊息（LangGraph state 同步更新）
7. `upsert_summary()` 非同步寫入 SQLite（失敗不中斷主流程）

**摘要注入：** 每次對話開始前，從 SQLite 載入 summary，注入 system prompt：
```
[前情摘要]
{summary}
```

---

## 資料庫設計

### 業務資料庫（SQLite + SQLAlchemy Async）

**users 表**
```
id            VARCHAR(36) PK   UUID
email         VARCHAR(255)     UNIQUE, INDEX
password_hash VARCHAR(255)     bcrypt rounds=12
display_name  VARCHAR(100)     nullable
is_active     BOOLEAN          default=True
created_at    DATETIME
updated_at    DATETIME
```

**conversations 表**
```
id          VARCHAR(36) PK
user_id     VARCHAR(36) FK → users.id (CASCADE DELETE), INDEX
title       VARCHAR(200)    nullable（首次訊息前 30 字自動設定）
is_archived BOOLEAN         default=False
created_at  DATETIME
updated_at  DATETIME
```

**messages 表**
```
id              VARCHAR(36) PK
conversation_id VARCHAR(36) FK → conversations.id (CASCADE DELETE)
role            VARCHAR(20)    'user' | 'assistant' | 'system'
content         TEXT
metadata        JSON           { sources: [...], form_data: {...}, token_count: N }
created_at      DATETIME

INDEX: (conversation_id, created_at)  ← 歷史查詢加速
```

**conversation_summaries 表**（1:1 對應 conversations）
```
id                        VARCHAR(36) PK
conversation_id           VARCHAR(36) FK UNIQUE → conversations.id (CASCADE DELETE)
summary                   TEXT           ≤300 字前情提要
summarized_up_to_message_id VARCHAR(36)  nullable
summarized_message_count  INTEGER        已壓縮的訊息數
updated_at                DATETIME
```

### ORM 設定

```python
engine = create_async_engine(
    "sqlite+aiosqlite:///app.db",
    connect_args={"check_same_thread": False},
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # 避免 async 場景 lazy loading 問題
)
```

- **WAL 模式**（Write-Ahead Logging）：提升並發讀寫性能
- **PRAGMA foreign_keys=ON**：確保外鍵 CASCADE 正確執行
- **Alembic migration**：`render_as_batch=True` 支援 SQLite ALTER TABLE 限制

### 狀態機資料庫（langgraph.db）

- LangGraph `AsyncSqliteSaver` 管理
- 儲存完整 GraphState checkpoint（含 messages list、intent、summary 等）
- 與業務資料庫 `app.db` 完全分離，互不影響

---

## 傳輸層設計

### API 架構

```
POST /api/auth/register       # 註冊
POST /api/auth/login          # 登入（回傳 access token + 設定 refresh cookie）
POST /api/auth/refresh        # 換發 access token
POST /api/auth/logout         # 清除 refresh cookie

GET  /api/conversations       # 對話列表
POST /api/conversations       # 建立對話
GET  /api/conversations/{id}  # 取得對話詳情（含訊息）
DEL  /api/conversations/{id}  # 刪除對話

POST /api/chat/{id}/stream    # 串流對話（SSE）
GET  /api/images/{filename}   # 取得知識庫圖片
```

### Server-Sent Events（SSE）串流

後端串流流程：
```python
async def chat_stream(conversation_id, body, ...):
    async for event in graph.astream_events(initial_state, config, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"].content
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        elif event["event"] == "on_chain_end" and node == "retriever":
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
```

前端接收流程（`lib/sse.ts`）：
```typescript
const es = new EventSource(`/api/chat/${conversationId}/stream`, ...)
es.onmessage = ({ data }) => {
  const msg = JSON.parse(data)
  if (msg.type === "chunk")   onChunk(msg.content)
  if (msg.type === "sources") onSources(msg.sources)
  if (msg.type === "done")    onDone()
}
```

### CORS 設定

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # 環境變數控制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 安全性設計

### JWT 雙 Token 機制

```
登入成功
  ├─ Access Token（JWT HS256，120 分鐘）→ 前端 memory（非 localStorage）
  └─ Refresh Token（JWT HS256，7 天）→ HttpOnly Cookie
                                          secure=True（非 development）
                                          samesite="strict"
                                          path="/api/auth"（限縮存取範圍）
```

**Token Rotation：** 每次 `/auth/refresh` 同時輪換 Refresh Token，舊 token 失效

**Token 驗證：**
```python
def verify_token(token, token_type="access") -> str | None:
    payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    if payload.get("type") != token_type:   # 防止 access token 冒用 refresh endpoint
        return None
    return payload.get("sub")              # 回傳 user_id
```

### 密碼安全

- bcrypt 加鹽雜湊，`rounds=12`
- `bcrypt.checkpw()` 時間安全比對（防 timing attack）

### API 保護

- 所有 `/api/conversations`、`/api/chat` 端點需驗證 Bearer Token
- FastAPI `Depends(get_current_user)` 統一注入使用者身份
- 查詢資料時強制帶入 `user_id` 過濾，防止越權存取

---

## 前端設計

### 頁面結構（Next.js App Router）

```
app/
├── (auth)/login/        # 登入頁
├── (app)/
│   ├── layout.tsx       # 主版型（Sidebar + 內容區）
│   ├── new/             # 新對話頁（歡迎畫面 + 輸入框）
│   └── chat/[id]/       # 對話頁（訊息列表 + 串流）
```

### 全域狀態（Zustand）

```typescript
useChatStore {
  conversations: ConversationOut[]    // sidebar 對話列表
  currentMessages: MessageOut[]       // 當前對話訊息
  pendingMessage: string | null       // /new 頁跨頁傳遞的首則訊息
}
```

### 串流訊息渲染

- `streamingMessage`：串流中的 AI 訊息（局部更新 content）
- `streamingSources`：串流中累積的來源（on done 後顯示）
- `streamingFormData`：串流中的表單資料
- 串流結束後以 local 變數（非 React state closure）組裝 `finalMsg`，解決 sources 需 reload 才顯示的 stale closure 問題

### RWD 響應式設計

- 電腦版：固定 Sidebar（可收合），聊天區 `max-w-3xl` 置中
- 手機版：Overlay Sidebar（漢堡按鈕開關）、底部固定 InputBar
- Sidebar 操作（重新命名 / 刪除）：電腦版 hover 顯示按鈕；手機版三點選單 inline 展開（避免 absolute dropdown overflow clipping 與觸控穿透問題）

### 串流指示器

- 串流進行中且使用者已滾離底部 → 顯示三點動畫浮動按鈕（可點擊 scroll 到底）
- 串流結束且未在底部 → 顯示圓形向下箭頭按鈕
- 使用 `absolute` 定位於 `relative` 容器內，避免 `fixed` 在 Sidebar 開關時位移

---

## 專案結構

```
backend/app/
├── api/
│   ├── auth.py              # 註冊 / 登入 / refresh / logout
│   ├── chat.py              # SSE 串流端點
│   ├── conversations.py     # 對話 CRUD
│   └── images.py            # 靜態圖片服務
├── core/
│   └── security.py          # JWT 簽發 / 驗證、bcrypt
├── graph/
│   ├── builder.py           # StateGraph 組裝、lifespan 初始化
│   ├── state.py             # GraphState TypedDict
│   └── nodes/
│       ├── compact.py       # compact_check、summarizer
│       ├── retrieval.py     # retriever
│       ├── context.py       # context_builder
│       ├── intent.py        # intent_classifier
│       ├── form.py          # form_structurer
│       └── generation.py    # responder
├── models/
│   ├── user.py
│   ├── conversation.py
│   ├── message.py
│   └── summary.py
├── rag/
│   ├── vector_store.py      # ChromaDB + OpenAI embedding（async 包裝）
│   ├── retriever.py         # Hybrid BM25 + Vector + RRF
│   └── jieba_dict.txt       # 4,948 個營造業自訂詞典
├── services/
│   └── conversation_service.py  # CRUD + upsert_summary + get_summary
├── config.py                # Pydantic BaseSettings
├── database.py              # async engine、get_db dependency
└── main.py                  # FastAPI app、lifespan、CORS
```

---

## 環境設定與啟動

### 環境變數（`.env`）

```env
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o
EMBEDDING_MODEL=text-embedding-3-small

DATABASE_URL=sqlite+aiosqlite:///./app.db
SYNC_DATABASE_URL=sqlite:///./app.db
LANGGRAPH_DB_PATH=./langgraph.db

SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=7

CHROMA_PERSIST_PATH=./chroma_db
CHROMA_VERSIONS_PATH=./chroma_versions
CHROMA_ACTIVE_VERSION=v1

APP_ENV=development
CORS_ORIGINS=http://localhost:3000
```

### 啟動後端

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

### 啟動前端

```bash
cd frontend
npm install
npm run dev
```

### 建置向量索引

```bash
cd backend
uv run python scripts/build_vectorstore.py
```
