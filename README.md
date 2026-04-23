# 營造知識助理 — LangGraph RAG System

營造業內部知識問答系統，整合 Adaptive RAG 檢索、CRAG 閉環修正、LangGraph 狀態機、串流回覆與結構化表單生成。

---

## 目錄

1. [系統概覽](#系統概覽)
2. [技術棧](#技術棧)
3. [系統架構](#系統架構)
4. [LangGraph 狀態機設計](#langgraph-狀態機設計)
5. [RAG 檢索設計](#rag-檢索設計)
6. [記憶系統設計](#記憶系統設計)
7. [表單生成設計](#表單生成設計)
8. [資料庫設計](#資料庫設計)
9. [傳輸層設計](#傳輸層設計)
10. [安全性設計](#安全性設計)
11. [前端設計](#前端設計)
12. [可觀測性](#可觀測性)
13. [專案結構](#專案結構)
14. [環境設定與啟動](#環境設定與啟動)

---

## 系統概覽

```
使用者 → 前端 (Next.js) → FastAPI → LangGraph
                                       ├─ Adaptive 檢索路由（跳過不必要的向量搜尋）
                                       ├─ Hybrid RAG（ChromaDB + BM25 + RRF）
                                       ├─ CRAG 閉環修正（retrieval grader + query rewriter）
                                       ├─ 意圖分類（qa / form_request）
                                       ├─ 回覆生成（串流 SSE）
                                       ├─ 表單生成（Function Calling + Pydantic）
                                       └─ Token-based 記憶壓縮
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
| 可觀測性 | LangSmith |

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
│   ├── scripts/            # 向量資料建置腳本
│   └── tests/              # pytest 單元測試
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
    # 對話識別
    conversation_id: str
    user_id: str

    # 訊息歷史（add_messages reducer 自動 append）
    messages: Annotated[list[BaseMessage], add_messages]

    # 當前查詢
    query: str

    # RAG 結果
    retrieved_chunks: list[dict]   # [{document, metadata, distance}]
    context: str                   # 組裝後的 context 字串
    sources: list[dict]            # 格式化來源（供前端 SourcesPanel）

    # 意圖
    intent: str                    # 'qa' | 'form_request'
    form_type: Optional[str]       # 'checklist' | 'report' | 'plan' | 'table'

    # 生成結果
    response: str
    form_data: Optional[dict]      # 結構化表單 JSON

    # Compact 控制
    is_compact_needed: bool
    token_count: int
    summary: Optional[str]

    # 檢索路由
    need_retrieval: bool           # True = 進行檢索；False = 跳過

    # CRAG 閉環控制
    retrieval_grade: str           # 'sufficient' | 'insufficient'
    retry_count: int               # 已重試次數（上限 2）
    rewritten_query: Optional[str] # query_rewriter 改寫後的查詢
```

### 流程圖

```
START
  └─► compact_check（同步：tiktoken 計算 token 數）
        ├─ token > 8000 ──► summarizer（壓縮舊訊息 → 生成摘要）─┐
        └─ token ≤ 8000 ──────────────────────────────────────┘
                                                               ▼
                                                   retrieval_router（LLM 判斷是否需要檢索）
                                                    ├─ need_retrieval=True ──► retriever（Hybrid RAG）
                                                    │                               ↓
                                                    │                        context_builder
                                                    │                               ↓
                                                    │                        retrieval_grader ◄──────────────┐
                                                    │                         ├─ sufficient ────────────────►│
                                                    │                         │                              │ (loop ≤ 2)
                                                    │                         └─ insufficient ─► query_rewriter ─┘
                                                    │                               ↓（sufficient 或超過重試上限）
                                                    └─ need_retrieval=False ─► intent_classifier
                                                                               ├─ form_request（無 chunks）─► retriever（補做）
                                                                               ├─ form_request（有 chunks）─► form_structurer ─► responder
                                                                               └─ qa ───────────────────────────────────────► responder
                                                                                                                                  ↓
                                                                                                                                 END
```

### 節點說明

| 節點 | 類型 | 模型 | 功能 |
|------|------|------|------|
| `compact_check` | 同步 | — | tiktoken 計算 token 數，判斷是否超過 8000 token 閾值 |
| `summarizer` | 非同步 | llm_model | 保留最近 8 則訊息，壓縮舊訊息為 300 字摘要，RemoveMessage 刪除舊訊息 |
| `retrieval_router` | 非同步 | grader_model | LLM 判斷是否需要知識庫檢索；首輪對話直接回傳 True 不呼叫 LLM |
| `retriever` | 非同步 | — | Hybrid 搜尋（向量 top-20 + BM25 top-20），RRF 融合後回傳 top-8 |
| `context_builder` | 同步 | — | 將 chunks 格式化為 LLM 可讀的 context string，注入 Markdown 圖片語法 |
| `retrieval_grader` | 非同步 | grader_model | 評估 context 是否足以回答問題，輸出 sufficient / insufficient |
| `query_rewriter` | 非同步 | grader_model | 將 query 改寫為更貼近文件語言的版本，遞增 retry_count |
| `intent_classifier` | 非同步 | grader_model | 關鍵字快速判斷，模糊時 LLM 語意分類（偏向 form_request） |
| `form_structurer` | 非同步 | form_model | Function Calling + Pydantic 生成結構化 JSON 表單 |
| `responder` | 非同步 | llm_model | ChatOpenAI streaming=True，astream_events 捕捉逐 token 推送 SSE |

### 條件路由

```python
def _route_compact(state):
    return "summarizer" if state["is_compact_needed"] else "retrieval_router"

def _route_retrieval(state):
    return "retriever" if state.get("need_retrieval", True) else "intent_classifier"

def _route_grader(state):
    if state["retrieval_grade"] == "insufficient" and state.get("retry_count", 0) < 2:
        return "query_rewriter"
    return "intent_classifier"

def _route_intent(state):
    if state["intent"] == "form_request":
        # 若來自 skip 路徑（無 chunks），補做檢索
        return "form_structurer" if state.get("retrieved_chunks") else "retriever"
    return "responder"
```

### Adaptive 檢索路由

`retrieval_router` 使用 `grader_model` 做二元 YES/NO 判斷，決定是否跳過知識庫檢索：

**需要檢索（YES）：** 詢問技術規範、法規、施工流程、請求生成表單、問及新主題

**可跳過（NO）：** 追問改寫前一輪回答、對前一輪細節的延伸問題、致謝純確認

**安全設計：**
- 首輪對話（無 AI 回應歷史）→ 跳過 LLM 呼叫，直接回傳 True
- LLM 回應不明確（非 YES/NO）→ 預設 True（安全側）
- skip 路徑若遇到 form_request → `_route_intent` 自動補做 `retriever`

### CRAG 閉環修正

`retrieval_grader` 在取得 context 後評估品質：
- **sufficient**：context 足以回答 → 繼續 `intent_classifier`
- **insufficient**：context 不足 → `query_rewriter` 改寫查詢 → 重新 `retriever`
- 最多重試 **2 次**（超過上限強制繼續，避免無限循環）

### CheckPointer（短期記憶持久化）

- 使用 LangGraph 內建 `AsyncSqliteSaver`
- 每個 conversation 對應唯一 `thread_id = conversation_id`
- 狀態持久化於獨立的 `langgraph.db`（與業務資料庫分離）
- 啟動時 `await checkpointer.setup()` 自動建表

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
- 版本化設計：`chroma_versions/v1/` 等路徑，支援熱切換版本（`CHROMA_ACTIVE_VERSION` 設定）
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

兩路各取 top-20，以 ChromaDB document ID 去重後合併排序，最終回傳 top-8 chunks。

### Chunk 資料結構

```json
{
  "chunk_id": "uuid",
  "source_file": "010101動員開工作業檢核表",
  "section_code": "010101",
  "chapter": "01",
  "phase": "工務所設置管理",
  "document_type": "checklist",
  "tags": ["動員開工", "初期計畫", "採購發包"],
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

### Token-Based Compaction 壓縮流程

**觸發條件：** 對話 token 數超過 **8,000 tokens**

1. `compact_check`：tiktoken（cl100k_base）計算全部 messages 的 token 數
2. 超過閾值 → 進入 `summarizer`
3. 保留最近 **8 則訊息**（約 4 輪對話），其餘視為「舊訊息」
4. 呼叫 LLM 生成 ≤300 字繁體中文前情提要
5. `RemoveMessage` 批量刪除舊訊息
6. `upsert_summary()` 非同步寫入 SQLite（失敗不中斷主流程）

**摘要注入：** 每次對話開始前從 SQLite 載入 summary，注入 system prompt：
```
[前情摘要]
{summary}
```

---

## 表單生成設計

### Function Calling + Pydantic Schema

`form_structurer` 使用 OpenAI Function Calling（`with_structured_output`）搭配 Pydantic 保證輸出結構，取代過去不穩定的 prompt 自行 parsing：

```python
class FormSchema(BaseModel):
    form_type: Literal["checklist", "report", "plan", "table"]
    title: str
    subtitle: Optional[str] = None
    columns: list[str]           # 欄位名稱列表
    rows: list[str]              # pipe-separated 字串，e.g. "安全帽佩戴|必須佩戴|□"
    notes: Optional[str] = None
```

**rows 設計為 `list[str]`（pipe-separated）而非 `list[dict]`**，原因是 `list[dict[str, str]]` 在 JSON Schema 中產生 `additionalProperties`，導致模型略過該欄位。Python 側再轉換為 `list[dict[str, str]]` 供前端使用。

### SSE 表單事件流程

```
form_loading  ← form_structurer 開始執行，前端顯示「表單生成中...」
    ↓
（text tokens 串流，responder 輸出一句確認文字）
    ↓
form          ← graph 完成後由 aget_state() 讀取，一次性推送完整 JSON
    ↓
done
```

### 支援表單類型

| 類型 | 說明 |
|------|------|
| `checklist` | 作業檢核表（逐項勾核） |
| `report` | 報告書（填寫數據、記錄結果） |
| `plan` | 計畫書（規劃步驟、時程） |
| `table` | 一般資料表格（彙整資訊） |

前端可匯出為 **Excel（.xlsx）**，由 openpyxl 生成。

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
metadata        JSON           { sources: [...], form_data: {...} }
created_at      DATETIME

INDEX: (conversation_id, created_at)
```

**conversation_summaries 表**（1:1 對應 conversations）
```
id                        VARCHAR(36) PK
conversation_id           VARCHAR(36) FK UNIQUE → conversations.id (CASCADE DELETE)
summary                   TEXT           ≤300 字前情提要
summarized_message_count  INTEGER
updated_at                DATETIME
```

### ORM 設定

- **WAL 模式**：提升並發讀寫性能
- **PRAGMA foreign_keys=ON**：確保外鍵 CASCADE 正確執行
- **Alembic migration**：`render_as_batch=True` 支援 SQLite ALTER TABLE 限制
- **expire_on_commit=False**：避免 async 場景 lazy loading 問題

### 狀態機資料庫（langgraph.db）

- LangGraph `AsyncSqliteSaver` 管理，與 `app.db` 完全分離
- 儲存完整 GraphState checkpoint（含 messages、intent、summary 等）

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

POST /api/chat/stream         # 串流對話（SSE）
GET  /api/images/{filename}   # 取得知識庫圖片
```

### Server-Sent Events（SSE）串流

**事件格式：**
```
{"type": "text",         "content": "..."}  # 逐 token 串流文字
{"type": "form_loading"}                    # 表單生成開始（前端顯示 loading）
{"type": "sources",      "data": [...]}     # 參考來源（一次性）
{"type": "form",         "data": {...}}     # 完整表單 JSON（一次性）
{"type": "error",        "content": "..."}  # 錯誤訊息
{"type": "done"}                            # 串流結束
```

**前端接收（`lib/sse.ts`）：**
```typescript
streamChat(conversationId, message, {
  onText:        (chunk) => appendToMessage(chunk),
  onFormLoading: ()      => setIsFormLoading(true),
  onSources:     (data)  => setStreamingSources(data),
  onForm:        (data)  => { setIsFormLoading(false); setFormData(data); },
  onDone:        ()      => finalizeMessage(),
})
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
                                          path="/api/auth"
```

**Token Rotation：** 每次 `/auth/refresh` 同時輪換 Refresh Token，舊 token 失效

### 密碼安全

bcrypt 加鹽雜湊（`rounds=12`），`bcrypt.checkpw()` 時間安全比對（防 timing attack）

### API 保護

- 所有對話與聊天端點需驗證 Bearer Token
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
- `isFormLoading`：`form_loading` 事件觸發後顯示「表單生成中...」卡片
- `streamingFormData`：`form` 事件後渲染表單預覽 + 下載按鈕
- 串流結束後以 local 變數（非 React state closure）組裝 `finalMsg`，解決 sources stale closure 問題

### 訊息氣泡佈局（MessageBubble）

```
AI 訊息排列順序：
1. FormLoadingCard（表單生成中... spinner）← form_loading 事件後
2. FormPreview + ExportButton              ← form 事件後，文字前顯示
3. 回覆文字（串流 cursor）
4. SourcesPanel（串流結束後顯示）
```

### RWD 響應式設計

- 電腦版：固定 Sidebar（可收合），聊天區 `max-w-3xl` 置中
- 手機版：Overlay Sidebar（漢堡按鈕開關）、底部固定 InputBar
- 串流進行中且使用者已滾離底部 → 顯示浮動向下按鈕

---

## 可觀測性

### LangSmith Tracing

啟用後可在 LangSmith dashboard 觀察每次對話的完整 trace，包含：

- 各節點執行時間與 token 消耗
- `retrieval_router` 判斷結果（YES/NO）
- CRAG 重試次數與改寫後的 query
- `form_structurer` 的 Function Calling 輸出

**設定方式（`.env`）：**
```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=LangGraph-RAG
```

### 測試

```bash
cd backend
uv run pytest tests/test_retrieval_router.py -v
```

測試項目：首輪快速路徑（不呼叫 LLM）、追問跳過檢索、新主題觸發檢索、表單請求觸發檢索、模型回應不明確時的安全側預設。

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
│   ├── builder.py           # StateGraph 組裝、條件路由
│   ├── state.py             # GraphState TypedDict
│   └── nodes/
│       ├── compact.py       # compact_check、summarizer
│       ├── router.py        # retrieval_router（Adaptive 檢索路由）
│       ├── retrieval.py     # retriever（Hybrid RAG）
│       ├── context.py       # context_builder
│       ├── grader.py        # retrieval_grader、query_rewriter（CRAG）
│       ├── intent.py        # intent_classifier
│       ├── form.py          # form_structurer（Function Calling）
│       └── generation.py    # responder（串流）
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

backend/tests/
└── test_retrieval_router.py # retrieval_router 單元測試（mock LLM）
```

---

## 環境設定與啟動

### 環境變數（`.env`）

```env
# OpenAI
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-5.4
GRADER_MODEL=gpt-5.4-mini      # retrieval_router / retrieval_grader / query_rewriter / intent_classifier
FORM_MODEL=gpt-5.4             # form_structurer
EMBEDDING_MODEL=text-embedding-3-small

# Database
DATABASE_URL=sqlite+aiosqlite:///./app.db
SYNC_DATABASE_URL=sqlite:///./app.db
LANGGRAPH_DB_PATH=./langgraph.db

# JWT
SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=7

# ChromaDB
CHROMA_PERSIST_PATH=./chroma_db
CHROMA_VERSIONS_PATH=./chroma_versions
CHROMA_ACTIVE_VERSION=v1       # 留空 = 使用 CHROMA_PERSIST_PATH

# App
APP_ENV=development
CORS_ORIGINS=http://localhost:3000

# LangSmith（可選）
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=LangGraph-RAG
```

### 模型分工

| 設定 | 用途 | 建議模型 |
|------|------|---------|
| `LLM_MODEL` | 回覆生成、對話摘要 | gpt-5.4 / gpt-4o |
| `GRADER_MODEL` | 檢索路由、品質評估、查詢改寫、意圖分類 | gpt-5.4-mini / gpt-4o-mini |
| `FORM_MODEL` | 表單 Function Calling | gpt-5.4 / gpt-4o |

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
