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
                                       ├─ Adaptive 檢索路由（LLM structured output RouterDecision）
                                       ├─ 兩層 Hybrid RAG（intra-query: Vector+BM25 RRF；inter-query: rewrite RRF）
                                       ├─ CRAG 閉環修正（GraderOutput + query rewriter，上限 2 次）
                                       ├─ 意圖分類（qa / form_request，多重 fast-path）
                                       ├─ 回覆生成（串流 SSE）
                                       ├─ 靜態表單 Registry（關鍵字比對 + 認證下載）
                                       ├─ 動態表單生成（Function Calling + Pydantic + 多輪延續）
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
    form_data: Optional[dict]      # 動態生成的結構化表單 JSON

    # Compact 控制
    is_compact_needed: bool
    token_count: int
    summary: Optional[str]

    # 檢索路由
    need_retrieval: bool           # True = 進行檢索；False = 跳過

    # CRAG 閉環控制
    retrieval_grade: str           # 'sufficient' | 'insufficient'
    retry_count: int               # 已重試次數（上限 2）
    retrieval_query: Optional[str] # query_rewriter 或 router 設定的改寫查詢
    grader_reason: Optional[str]             # grader 的判斷依據
    grader_missing_information: Optional[str]  # grader 指出的缺漏資訊（供 rewriter 參考）

    # 靜態表單 Registry
    matched_forms: list[dict]      # [{form_id, display_name, download_url}]
    form_explicit: bool            # True = 使用者明確索取靜態表單檔案

    # 多輪表單延續
    is_form_continuation: bool     # True = router 判定為延續上一輪表單
    prev_form_data: Optional[dict] # 最近一輪生成的表單（避免重複、保持格式一致）
```

### 流程圖

```
START
  └─► compact_check（同步：tiktoken 計算 token 數）
        ├─ token > 8000 ──► summarizer（壓縮舊訊息 → 生成摘要）─┐
        └─ token ≤ 8000 ──────────────────────────────────────┘
                                                               ▼
                                                   retrieval_router（LLM → RouterDecision JSON）
                                                    ├─ form_explicit=True ──────────────────────────────────────► intent_classifier
                                                    ├─ need_retrieval=True ──► retriever（Hybrid RAG）
                                                    │    is_form_continuation=True 時附帶 retrieval_topic
                                                    │                               ↓
                                                    │                        context_builder
                                                    │                               ↓
                                                    │                        retrieval_grader（GraderOutput）◄──────────┐
                                                    │                         ├─ sufficient ──────────────────────────►│
                                                    │                         │                                        │ (loop ≤ 2)
                                                    │                         └─ insufficient ─► query_rewriter ───────┘
                                                    │                               ↓（sufficient 或超過重試上限）
                                                    └─ need_retrieval=False ─► intent_classifier
                                                                               ├─ form_explicit + matched_forms ─► responder（靜態下載）
                                                                               ├─ is_form_continuation ──────────► form_structurer ─► responder
                                                                               ├─ form_request（有 chunks）────── ─► form_structurer ─► responder
                                                                               ├─ form_request（無 chunks）────── ─► retriever（補做）
                                                                               └─ qa ────────────────────────────► responder
                                                                                                                        ↓
                                                                                                                       END
```

### 節點說明

| 節點 | 類型 | 模型 | 功能 |
|------|------|------|------|
| `compact_check` | 同步 | — | tiktoken 計算 token 數，判斷是否超過 8000 token 閾值 |
| `summarizer` | 非同步 | llm_model | 保留最近 8 則訊息，壓縮舊訊息為 300 字摘要，RemoveMessage 刪除舊訊息 |
| `retrieval_router` | 非同步 | grader_model | LLM structured output（RouterDecision）：一次判斷 need_retrieval + is_form_continuation + retrieval_topic；同時執行靜態表單 form_lookup |
| `retriever` | 非同步 | — | 雙路平行 Hybrid 搜尋，若有 retrieval_query 則兩路 RRF 融合（inter-query RRF）；單路為 intra-query RRF（Vector+BM25） |
| `context_builder` | 同步 | — | 將 chunks 格式化為 LLM 可讀的 context string，注入來源標頭與 Markdown 圖片語法 |
| `retrieval_grader` | 非同步 | grader_model | structured output（GraderOutput）評估 context 品質，回傳 decision / reason / missing_information |
| `query_rewriter` | 非同步 | grader_model | 依 missing_information 將 query 改寫為更貼近文件語言的版本，遞增 retry_count |
| `intent_classifier` | 非同步 | grader_model | 三重 fast-path（form_explicit / is_form_continuation / 關鍵字），模糊時 LLM 語意分類 |
| `form_structurer` | 非同步 | form_model | Function Calling + Pydantic 生成結構化 JSON 表單；注入 prev_form_data 避免多輪重複 |
| `responder` | 非同步 | llm_model | 靜態表單輸出短句確認；動態表單輸出說明文字；QA 串流完整回覆；astream_events 捕捉逐 token 推送 SSE |

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

`retrieval_router` 使用 `grader_model` 搭配 Pydantic structured output（`RouterDecision`），一次 LLM 呼叫同時判斷三個維度：

```python
class RouterDecision(BaseModel):
    need_retrieval: bool          # 是否需要知識庫檢索
    is_form_continuation: bool   # 是否為延續上一輪表單生成
    retrieval_topic: Optional[str] # 延續時的檢索主題詞
    reason: str                  # 判斷依據（LangSmith 可觀測）
```

**need_retrieval=True：** 詢問技術規範、法規、施工流程、請求生成表單、問及新主題

**need_retrieval=False：** 改寫前一輪回答、對前一輪細節追問、致謝確認

**is_form_continuation=True（需同時滿足）：**
- 使用者想繼續/增加表單內容（如「再生成五組」「多出幾題」）
- 前一輪確實生成過表單（`prev_form_data` 不為 None）
- 設定 `retrieval_query = retrieval_topic`，讓 retriever 搜尋正確主題

**安全設計：**
- 首輪對話（無 AI 回應歷史）→ 跳過 LLM 呼叫，直接回傳 `need_retrieval=True`
- 靜態表單比對（form_lookup）優先於 LLM 路由，命中時直接設 `form_explicit=True`
- skip 路徑若遇到 form_request 且無 chunks → `_route_intent` 自動補做 `retriever`

### CRAG 閉環修正

`retrieval_grader` 使用 structured output（`GraderOutput`）評估 context 品質：

```python
class GraderOutput(BaseModel):
    decision: Literal["sufficient", "insufficient"]
    reason: str                  # 判斷依據
    missing_information: str     # 缺少的資訊描述（供 query_rewriter 參考）
```

- **sufficient**：context 足以回答 → 繼續 `intent_classifier`
- **insufficient**：context 不足 → `query_rewriter` 依 `missing_information` 改寫查詢 → 重新 `retriever`
- 最多重試 **2 次**（超過上限強制繼續，避免無限循環）

**Inter-query RRF：** 當 `retrieval_query` 與 `query` 不同時，`retriever` 平行搜尋兩個 query，結果再做一次 RRF 融合，同時出現在兩組結果的 chunk 自動加分。

### CheckPointer（短期記憶持久化）

- 使用 LangGraph 內建 `AsyncSqliteSaver`
- 每個 conversation 對應唯一 `thread_id = conversation_id`
- 狀態持久化於獨立的 `langgraph.db`（與業務資料庫分離）
- 啟動時 `await checkpointer.setup()` 自動建表

---

## RAG 檢索設計

### Hybrid Search 架構（兩層 RRF）

```
                    ┌─ query ─────────────────────────────────────────────┐
                    │                                                     │ （CRAG rewrite 或 form continuation 時）
                    ▼                                                     ▼
  intra-query RRF（每個 query 各自執行）               retrieval_query（改寫版或主題詞）
    ├─ OpenAI Embedding → ChromaDB 向量搜尋（top-20）      同樣執行 intra-query RRF → top-8
    └─ jieba 分詞 → BM25 關鍵字搜尋（top-20）
          ↓
     RRF 融合 → top-8 chunks
                    │                                                     │
                    └──────────────── inter-query RRF ───────────────────┘
                                              ↓
                                        merged top-8 chunks
                         （同時出現在兩組結果的 chunk 自動加分）
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

### 靜態表單 Registry

`data_markdown/form_data/` 存放預建的 `.docx` 表單範本，由 `form_registry.json` 管理：
- **關鍵字比對**：`lookup_forms(query)` 依 tags 匹配，回傳 `matched_forms`
- **明確請求偵測**：`is_explicit_form_request(query)` 檢查動詞（下載、給我）+ 名詞（表單、表格）
- **認證下載端點**：`GET /api/forms/{form_id}/download`，需 Bearer token，回傳 FileResponse

### 動態表單多輪延續

跨對話輪次保持表單一致性：
- `prev_form_data`：chat.py 每輪從 checkpointer 讀取前一輪（或更早）的 form_data，不中斷鏈
- `is_form_continuation`：router LLM 判定延續請求時設為 True，intent_classifier 直接 fast-path 為 form_request
- `form_structurer` prompt 注入 prev_form_data 的標題、欄位與前幾列範例，避免重複生成相同內容

### SSE 表單事件流程

```
（動態表單）
form_loading  ← form_structurer 開始執行，前端顯示骨架動畫 + 輪播文字
    ↓
text tokens   ← responder 輸出確認文字
    ↓
form          ← graph 完成後推送完整 FormData JSON
    ↓
done

（靜態表單）
text tokens   ← responder 輸出「《表單名稱》，請點擊下方下載。」
    ↓
form_files    ← 推送 [{form_id, display_name, download_url}]
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
{"type": "form_loading"}                    # 動態表單生成開始（前端顯示骨架動畫）
{"type": "sources",      "data": [...]}     # 參考來源（一次性）
{"type": "form",         "data": {...}}     # 動態表單完整 JSON（一次性）
{"type": "form_files",   "data": [...]}     # 靜態表單下載卡片 [{form_id, display_name, download_url}]
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
│   ├── retriever.py         # Hybrid BM25 + Vector + intra/inter-query RRF
│   ├── form_registry.json   # 靜態表單 Registry（form_id / keywords / download_url）
│   ├── form_lookup.py       # 靜態表單比對與明確請求偵測
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
