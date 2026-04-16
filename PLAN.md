# 營造業內部知識 RAG 系統 — 完整開發計畫書

> 版本：v1.1 | 日期：2026-04-16 | 已確認所有討論事項

---

## 目錄

1. [專案概述](#1-專案概述)
2. [技術選型總覽](#2-技術選型總覽)
3. [系統架構設計](#3-系統架構設計)
4. [資料庫設計](#4-資料庫設計)
5. [RAG 資料管線設計](#5-rag-資料管線設計)
6. [後端架構設計](#6-後端架構設計)
7. [LangGraph Agent 設計](#7-langgraph-agent-設計)
8. [前端架構設計](#8-前端架構設計)
9. [分階段開發計畫](#9-分階段開發計畫)
10. [目錄結構總覽](#10-目錄結構總覽)
11. [Docker 打包規劃](#11-docker-打包規劃)
12. [待討論事項](#12-待討論事項)

---

## 1. 專案概述

### 1.1 目標

建立一套**內部員工知識查詢系統**，以 51 份營造業 Markdown 文件作為知識庫，讓新進員工可透過自然語言查詢：

- 查詢工地作業程序、管理規範
- 生成結構化**可下載的 Excel/CSV 表單**（非純文字轉換，先呈現結構化預覽再輸出）
- 保存多輪對話紀錄（關閉頁面後仍保留）

### 1.2 核心需求

| 需求 | 規格 |
|---|---|
| 使用者身分 | 帳號制（Email + 密碼） |
| 知識庫來源 | 51 份 Markdown（含圖片） |
| 向量資料庫 | ChromaDB（持久化，增量更新） |
| Embedding | text-embedding-3-small |
| 輸出模型 | gpt-5.4 |
| 串流方式 | SSE（Server-Sent Events） |
| Agent 框架 | LangGraph |
| 表單輸出 | Excel / CSV（結構化預覽後下載） |
| 對話持久化 | 使用者關閉頁面後保留 |
| 圖片顯示 | 後端靜態圖片 API，前端 Markdown 渲染 |
| Token 認證 | JWT，Refresh Token 使用 HttpOnly Cookie |
| 對話標題 | 自動生成 + 使用者可手動重新命名 |
| 使用者角色 | 單一角色（無管理員） |
| 未來部署 | Docker Compose |

---

## 2. 技術選型總覽

### 2.1 後端

| 項目 | 選擇 | 理由 |
|---|---|---|
| 語言 | Python 3.12 | 生態系最完整 |
| 套件管理 | uv | 快速、獨立虛擬環境 |
| Web 框架 | FastAPI | 原生支援 async、SSE |
| ORM | SQLAlchemy 2.x + Alembic | 物件導向、migration 管理 |
| 關聯式 DB | **SQLite（aiosqlite）** | 無需安裝伺服器，零配置，WAL 模式支援並發讀取；未來可切換 PostgreSQL |
| 向量 DB | ChromaDB（persistent） | 本地持久化、輕量 |
| Agent 框架 | LangGraph | 狀態圖、支援 SQLite checkpointer |
| 認證 | JWT（python-jose） | Access Token 存記憶體，Refresh Token 存 HttpOnly Cookie |
| 密碼 | bcrypt | 業界標準 |
| 靜態圖片 | FastAPI StaticFiles | 提供 `/api/images/` 路徑給前端取用 |
| 表單生成 | openpyxl | Excel 生成 |

### 2.2 前端

| 項目 | 選擇 |
|---|---|
| 框架 | Next.js 15（App Router） |
| 樣式 | TailwindCSS |
| 套件管理 | Yarn |
| 狀態管理 | Zustand（Access Token 存 store，不存 localStorage） |
| HTTP | Axios（自動附帶 Authorization header，攔截 401 自動 refresh） |
| SSE | 原生 Fetch API（ReadableStream，非 EventSource，因需帶自訂 header） |
| Markdown 渲染 | react-markdown + remark-gfm（支援表格、圖片） |
| 表單預覽 | 自訂 TablePreview 元件 |

---

## 3. 系統架構設計

```
┌─────────────────────────────────────────────────────────┐
│                    使用者瀏覽器                           │
│          Next.js (React) + TailwindCSS                   │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ 登入/註冊 │  │  對話介面    │  │  表單預覽/下載   │   │
│  └──────────┘  └──────┬───────┘  └──────────────────┘   │
└─────────────────────── │ ───────────────────────────────┘
                         │ HTTP / SSE
┌─────────────────────── │ ───────────────────────────────┐
│                  FastAPI Backend                          │
│  ┌────────────┐  ┌─────┴──────┐  ┌────────────────────┐ │
│  │  Auth API  │  │  Chat API  │  │   Export API       │ │
│  │  (JWT)     │  │  (SSE流)   │  │   (Excel/CSV)      │ │
│  └──────┬─────┘  └─────┬──────┘  └────────────────────┘ │
│         │              │                                  │
│  ┌──────▼──────────────▼──────────────────────────────┐  │
│  │               LangGraph Agent                       │  │
│  │  intent→retrieval→context→generate→form_structure  │  │
│  └──────────────────────────────────────────────────── │  │
│         │              │                                  │
│  ┌──────▼──────┐  ┌────▼──────────────────────────────┐  │
│  │ PostgreSQL  │  │           ChromaDB                  │  │
│  │ users       │  │  (向量儲存 + 持久化)                │  │
│  │ conversations│  └───────────────────────────────────┘  │
│  │ messages    │                                           │
│  │ summaries   │  ┌────────────────────────────────────┐  │
│  └─────────────┘  │         OpenAI API                  │  │
│                   │  text-embedding-3-small / gpt-5.4   │  │
│                   └────────────────────────────────────┘  │
└────────────────────────────────────────────────────────── ┘
```

### 3.1 Token 認證流程

```
登入成功後：
  → Access Token（JWT，2小時有效）存於前端記憶體（Zustand store，不存 localStorage）
  → Refresh Token（7天有效）設定於 HttpOnly Cookie（無法被 JS 讀取，防 XSS）

請求 API 時：
  → Authorization: Bearer {access_token}

Access Token 過期時：
  → 前端自動 POST /api/auth/refresh（帶 Cookie）
  → 後端驗證 Refresh Token → 回傳新 Access Token

登出時：
  → 清除記憶體中的 Access Token
  → POST /api/auth/logout → 後端清除 HttpOnly Cookie
```

### 3.2 圖片提供架構

```
data_markdown/img/               ← 圖片實體路徑
  010101動員開工檢核.../
    page-05.png
  010102工務所辦公室設置/
    001.png

FastAPI 掛載靜態目錄：
  app.mount("/api/images", StaticFiles(directory="data_markdown/img"))

前端請求：
  GET /api/images/010101動員開工檢核.../page-05.png
  → 直接回傳圖片 bytes

Chunk 中的圖片引用格式（統一後）：
  ![圖片說明](/api/images/{folder}/{filename})

前端 Markdown 渲染器（react-markdown）自動顯示圖片。
```

### 3.3 資料流說明

**查詢流程**（更新）：
```
使用者輸入 → FastAPI → LangGraph
  → [compact_check] 是否需壓縮歷史
  → [retriever] ChromaDB 向量搜尋 (Top-K chunks)
  → [context_builder] 組裝 context
  → [intent_classifier] 判斷意圖 (QA / 表單請求)
  → [responder] gpt-5.4 生成回覆 (SSE 串流)
  → [form_structurer] 若為表單請求，結構化輸出
  → 儲存至 PostgreSQL → 回傳前端
```

**表單生成流程**：
```
使用者請求表單 → 結構化 JSON 輸出 → 前端 TablePreview 呈現
  → 使用者確認 → POST /api/export → openpyxl 生成 Excel → 下載
```

---

## 4. 資料庫設計

### 4.0 資料庫替代方案決策

> **PostgreSQL 安裝失敗，改採 SQLite（aiosqlite）作為替代方案。**

| 項目 | PostgreSQL（原計畫） | SQLite（現行） |
|---|---|---|
| 安裝方式 | 需安裝伺服器 | 零安裝，檔案型 |
| 非同步驅動 | asyncpg | aiosqlite |
| Alembic 同步驅動 | psycopg2 | 內建 sqlite3 |
| LangGraph checkpointer | `AsyncPostgresSaver` | `AsyncSqliteSaver` |
| UUID 欄位型別 | PostgreSQL UUID | String(36) |
| JSON 欄位型別 | JSONB | JSON |
| ALTER TABLE | 原生支援 | 需 `render_as_batch=True` |
| 未來切換 | — | 只需換 DATABASE_URL 和驅動 |

**SQLite 特殊設定（已套用）**：
- WAL 模式（`PRAGMA journal_mode=WAL`）：提升並發讀取效能
- Foreign Keys（`PRAGMA foreign_keys=ON`）：確保關聯完整性
- Alembic `render_as_batch=True`：支援 SQLite 的 ALTER TABLE 限制
- 兩個資料庫檔案：`app.db`（ORM 資料）、`langgraph.db`（Agent 對話狀態）

### 4.1 SQLite Schema（SQLAlchemy ORM）

#### 4.1.1 users

```python
class User(Base):
    __tablename__ = "users"

    id: str (PK, String(36), default=str(uuid4()))
    email: str (UNIQUE, NOT NULL, indexed)
    password_hash: str (NOT NULL)
    display_name: str (nullable)
    is_active: bool (default True)
    created_at: datetime (default=datetime.now(utc))
    updated_at: datetime (auto-update)

    # Relations
    conversations: List[Conversation]
```

#### 4.1.2 conversations

```python
class Conversation(Base):
    __tablename__ = "conversations"

    id: UUID (PK)
    user_id: str (FK → users.id, CASCADE DELETE, String(36))
    title: str (nullable, 預設取第一則訊息前 30 字)
    is_archived: bool (default False)
    created_at: datetime
    updated_at: datetime

    # Relations
    messages: List[Message]
    summary: Optional[ConversationSummary]
```

#### 4.1.3 messages

```python
class Message(Base):
    __tablename__ = "messages"

    id: str (PK, String(36))
    conversation_id: str (FK → conversations.id, CASCADE DELETE)
    role: str  # 'user' | 'assistant' | 'system'
    content: str (TEXT)
    metadata: dict (JSON, nullable)   # SQLite 用 JSON 取代 JSONB
    # metadata 範例：
    # {
    #   "sources": [{"file": "010101...", "section": "4.5"}],
    #   "form_data": {"type": "checklist", "rows": [...]},
    #   "token_count": 1234
    # }
    created_at: datetime

    # Index: (conversation_id, created_at)
```

#### 4.1.4 conversation_summaries（對話壓縮記錄）

```python
class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: str (PK, String(36))
    conversation_id: UUID (FK → conversations.id, CASCADE DELETE, UNIQUE)
    summary: str (TEXT)                # 摘要內容
    summarized_up_to_message_id: UUID  # 摘要涵蓋到哪則訊息
    summarized_message_count: int      # 被壓縮的訊息數量
    updated_at: datetime
```

### 4.2 ER Diagram

```
users ──< conversations ──< messages
             │
             └──── conversation_summaries (1:1)
```

### 4.3 索引設計

```sql
-- 已由 SQLAlchemy mapped_column(index=True) 自動建立
CREATE INDEX ix_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_messages_conversation_id_created ON messages(conversation_id, created_at);
CREATE INDEX ix_users_email ON users(email);
```

> **SQLite 資料庫檔案**：
> - `backend/app.db` — ORM 資料（users / conversations / messages / summaries）
> - `backend/langgraph.db` — LangGraph Agent 對話狀態（checkpointer）

---

## 5. RAG 資料管線設計

### 5.1 文件結構分析（51 份 MD）

閱讀所有檔案後確認 3 種格式：

| 類型 | 特徵 | 數量 | 圖片格式 | 是否有 RAG 標籤 |
|---|---|---|---|---|
| **Type A：作業檢核表** | 純 Markdown 表格，無圖片 | ~13 份 | 無 | 無 |
| **Type B：標準內文** | H1-H4 階層 + 圖片描述 + 文末 RAG 標籤 | ~26 份 | `![alt](路徑)` + 說明區塊 | 有 |
| **Type C：掃描PDF轉換** | 逐頁 code block + 圖片純路徑 | ~12 份 | `` `路徑` `` 純路徑 | 部分有 |

### 5.2 前處理流程（Method B）

#### Step 5.2.1 — 正規化圖片引用

將所有圖片引用統一為**可直接在前端顯示**的 Markdown 格式：

```python
# 原始寫法（Type B）：
# ![對業主授權文件範例](data_markdown/img/010101.../page-08.png)
# - 圖片說明：...
# - 圖片標記：授權文件, 授權範圍

# 原始寫法（Type C）：
# `data_markdown/img/010102.../001.png`
# 圖片說明：...

# 統一輸出格式（寫入清理後的 .md）：
# ![對業主授權文件範例 | 圖片說明文字 | 標籤1, 標籤2](/api/images/010101.../page-08.png)
#
# 說明：
# - 路徑改為 /api/images/ 前綴（前端直接可用）
# - alt text 融合標題 + 說明（供 Markdown 渲染的 tooltip）
# - 說明區塊保留為純文字段落（供 Embedding 索引）
```

**正規化規則**：
- Type B：從 `![alt](data_markdown/img/...)` + 下方說明區塊萃取，重寫為 `/api/images/...` 路徑
- Type C：從 `` `data_markdown/img/...` `` + 旁邊說明文字萃取，重寫為標準 Markdown 圖片語法
- 圖片說明文字保留在 chunk 文字中（不移除，確保語意可被 Embedding 捕捉）
- 移除 Type C 文末重複的「圖片索引」區塊（已在各頁重複過）
- 同時在 metadata 中儲存 `image_paths`（原始路徑列表）供除錯用

#### Step 5.2.2 — Type C 格式清理

Type C 的逐頁 code block 會干擾語意切割，需要：

```python
# 移除 code block 包裹，還原為純 Markdown 文字
# 移除頁碼 header（如 `## 第2頁`），改為語意標題
# 合併 code block 內文 + 當頁圖片描述
```

#### Step 5.2.3 — 切割策略

#### 核心切割原則：圖片不得跨 chunk 切斷

> **規則**：圖片引用（`![...](...)`）與其緊接的說明文字段落，必須與「引用該圖片的上文段落」保留在同一個 chunk 中。
>
> 切割邊界偵測時，若預定切割點落在：
> - 圖片語法 `![` 開頭的行 **之前**（圖片會被切到下一個 chunk）
> - 圖片說明段落（`- 圖片說明：`、`- 圖片標記：`）中間
>
> 則該切割點**向後移動**至圖片說明段落結束後的第一個空行。

```
✗ 錯誤切法（圖片與上文段落分離）：
  --- chunk A ---
  依契約規定提送業主。
  ← 切割點在這裡 ×

  --- chunk B ---
  ![對業主授權文件範例](/api/images/.../page-08.png)
  圖片說明：範例顯示專案負責人...
  圖片標記：授權文件, 授權範圍

✓ 正確切法（圖片與引用它的段落同一 chunk）：
  --- chunk A ---
  依契約規定提送業主。

  ![對業主授權文件範例](/api/images/.../page-08.png)
  圖片說明：範例顯示專案負責人...
  圖片標記：授權文件, 授權範圍
  ← 切割點在這裡 ✓
```

**Type A（作業檢核表）**：
- 以 `## H2` 為邊界切割（如「## 1. 辦公室設置評估」）
- 每個大項目（及其子表格）為一個 chunk
- 最小 chunk 若 < 100 tokens，向下合併至下一個 H2
- Type A 無圖片，不需圖片保護規則

**Type B（標準內文）**：
- 以 `### H3` 為主要切割邊界
- **套用圖片保護規則**：偵測切割點是否緊接圖片，若是則延後切割點
- 父層 `## H2` 標題作為 chunk 的 `context_header`（存 metadata，並加入 LLM prompt context 但不加入 Embedding 文字）
- 若單一 H3 section > 800 tokens（排除圖片描述），進一步以語意段落切割（同樣套用圖片保護規則）

**Type C（掃描PDF轉換）**：
- 清理 code block 後，每「頁」（原始 `## 第N頁`）的文字 + 圖片描述合為一個 chunk（不跨頁切割）
- 若單頁內容 > 1000 tokens，以語意段落切割，同樣套用圖片保護規則
- 每頁圖片描述融入同頁文字 chunk

**Chunk 大小目標**：
- 目標：400–700 tokens
- 上限：1000 tokens（超過強制切割，但不從圖片中間切）
- 下限：80 tokens（向後合併）

#### Step 5.2.4 — Metadata 設計

每個 chunk 儲存以下 metadata 至 ChromaDB：

```python
{
  # 來源識別
  "chunk_id": "uuid-v4",
  "source_file": "010101動員開工檢核",
  "section_code": "010101",          # 節次編號
  "chapter": "01",                    # 大章別：01/02/03
  "phase": "工務所設置管理",          # 中文階段名稱

  # 文件類型
  "document_type": "procedure",       # procedure|checklist|reference
  "file_type": "B",                   # A|B|C

  # 語意標籤（RAG 使用）
  "tags": ["動員開工", "工令", "工務所"],

  # 章節結構
  "parent_h2": "4. 流程及作業說明",
  "parent_h3": "4.5 對業主應辦事項",
  "chunk_index": 3,                   # 該文件第幾個 chunk

  # 圖片資訊
  "has_images": True,
  "image_paths": ["data_markdown/img/.../page-08.png"],
  "image_tags": ["專案負責人提報", "授權文件"],
}
```

#### Step 5.2.5 — 無 RAG 標籤文件的 Metadata 生成

對沒有 RAG 標籤的 ~26 份文件，使用 GPT 批量生成 metadata：

```python
# 輸入：chunk 文字 + 節次代碼 + 文件類型
# 輸出：tags list（5-10 個關鍵字）
# 批量處理後需人工審查確認（輸出 review CSV）
```

**批量生成腳本輸出**：`scripts/output/metadata_review.csv`
- 欄位：`source_file, chunk_id, generated_tags, confidence`
- 人工確認後執行 ingest

### 5.3 Embedding 與向量儲存

```python
# Embedding
model = "text-embedding-3-small"
embedding_dim = 1536

# ChromaDB Collection 設計
collection_name = "construction_knowledge"
distance_metric = "cosine"

# 持久化路徑
chroma_persist_path = "./chroma_db"
```

**搜尋策略**：
- Top-K = 5（預設，可調整）
- 搜尋時附帶 metadata filter（如 `chapter`, `document_type`）
- 後續可擴展 Hybrid Search（BM25 + Vector）

### 5.4 增量更新機制

> 不做純一次性 ingest，而是設計 hash 比對的增量更新，避免文件更新時重新 embed 所有 51 份。

```
scripts/output/file_hashes.json    ← 紀錄每份 MD 的 SHA256 hash + 最後 ingest 時間

增量更新流程：
  1. 掃描 data_markdown/*.md
  2. 比對 SHA256 hash 與 file_hashes.json
  3. 有差異（新增 or 修改）的檔案 → 刪除舊 chunks（依 source_file metadata 刪除）→ 重新 chunk + embed
  4. 已刪除的檔案 → 刪除對應 chunks
  5. 更新 file_hashes.json
```

### 5.5 管線腳本對應關係

```
scripts/
  01_preprocess.py    # 清理 Type C、正規化圖片引用（路徑改為 /api/images/）
  02_chunk.py         # 切割（含圖片保護規則），輸出 chunks.jsonl
  03_generate_meta.py # GPT 批量生成無標籤文件 metadata
  04_review_meta.py   # 輸出 metadata_review.csv 供人工確認
  05_embed_ingest.py  # Embedding + 寫入 ChromaDB（支援增量更新 + hash 記錄）
  06_verify.py        # 驗證 collection 完整性、查詢測試、輸出報告
```

---

## 6. 後端架構設計

### 6.1 目錄結構

```
backend/
├── pyproject.toml              # uv 管理，dependencies 宣告
├── .env                        # 環境變數（gitignore）
├── alembic.ini
├── alembic/
│   └── versions/               # DB migration 檔案
├── chroma_db/                  # ChromaDB 持久化目錄（gitignore）
├── scripts/                    # 資料管線腳本（獨立執行）
│   ├── 01_preprocess.py
│   ├── 02_chunk.py
│   ├── 03_generate_meta.py
│   ├── 04_review_meta.py
│   ├── 05_embed_ingest.py
│   └── 06_verify.py
└── app/
    ├── main.py                 # FastAPI 入口、lifespan
    ├── config.py               # Settings（pydantic-settings）
    ├── database.py             # AsyncEngine, AsyncSession, Base
    │
    ├── models/                 # SQLAlchemy ORM Models
    │   ├── __init__.py
    │   ├── user.py
    │   ├── conversation.py
    │   ├── message.py
    │   └── summary.py
    │
    ├── schemas/                # Pydantic Request/Response Schemas
    │   ├── __init__.py
    │   ├── auth.py             # LoginRequest, TokenResponse, RegisterRequest
    │   ├── conversation.py     # ConversationOut, CreateConversation
    │   ├── message.py          # MessageOut, ChatRequest
    │   └── export.py           # ExportRequest
    │
    ├── api/                    # FastAPI Routers
    │   ├── __init__.py
    │   ├── auth.py             # POST /auth/register, /auth/login, /auth/refresh, /auth/logout
    │   ├── chat.py             # POST /chat/stream (SSE)
    │   ├── conversations.py    # GET/POST/PATCH/DELETE /conversations
    │   └── export.py           # POST /export/excel, /export/csv
    │   # 圖片：FastAPI StaticFiles 掛載於 main.py（非 router）
    │
    ├── services/               # 業務邏輯層（不直接接觸 HTTP）
    │   ├── __init__.py
    │   ├── auth_service.py     # 帳號建立、JWT 發放、密碼驗證
    │   ├── conversation_service.py  # 對話 CRUD、歷史讀取
    │   └── export_service.py   # Excel/CSV 生成（openpyxl）
    │
    ├── rag/                    # RAG 元件
    │   ├── __init__.py
    │   ├── vector_store.py     # ChromaDB 連線、搜尋介面
    │   └── retriever.py        # 搜尋邏輯、Rerank、結果組裝
    │
    ├── graph/                  # LangGraph Agent
    │   ├── __init__.py
    │   ├── state.py            # GraphState TypedDict
    │   ├── builder.py          # 組裝 StateGraph
    │   └── nodes/
    │       ├── __init__.py
    │       ├── compact.py      # compact_check + summarizer 節點
    │       ├── retrieval.py    # retriever 節點
    │       ├── context.py      # context_builder 節點
    │       ├── intent.py       # intent_classifier 節點
    │       ├── generation.py   # responder 節點（SSE 串流）
    │       └── form.py         # form_structurer 節點
    │
    └── core/
        ├── __init__.py
        ├── security.py         # JWT encode/decode、bcrypt
        └── dependencies.py     # get_current_user、get_db
```

### 6.2 API 端點設計

#### 認證

```
POST /api/auth/register
  Body:    { email, password }
  Returns: { access_token }  +  Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Strict

POST /api/auth/login
  Body:    { email, password }
  Returns: { access_token }  +  Set-Cookie: refresh_token=...

POST /api/auth/refresh
  Cookie:  refresh_token
  Returns: { access_token }       # 自動刷新，前端無感

POST /api/auth/logout
  Cookie:  refresh_token
  Returns: 200 OK  +  清除 Cookie
```

#### 對話管理

```
GET    /api/conversations
  Returns: [ { id, title, updated_at, last_message_preview } ]

POST   /api/conversations
  Body:    { title? }             # 不帶 title 則自動生成
  Returns: { id, title, created_at }

GET    /api/conversations/{id}
  Returns: { id, title, messages, summary? }

PATCH  /api/conversations/{id}
  Body:    { title }              # 使用者手動重新命名
  Returns: { id, title }

DELETE /api/conversations/{id}
  Returns: 204 No Content
```

#### 聊天（SSE）

```
POST /api/chat/stream
  Body: {
    "conversation_id": "uuid",
    "message": "我需要動員開工的作業流程..."
  }
  Response: text/event-stream

  SSE Events:
    data: {"type": "text",    "content": "..."}           # 串流逐字文字
    data: {"type": "form",    "data": { FormData }}        # 表單結構（一次性）
    data: {"type": "sources", "data": [ SourceItem ]}      # 參考來源文件
    data: {"type": "done"}                                  # 串流結束

  SourceItem: {
    "source_file": "010101動員開工檢核",
    "section": "4.5 對業主應辦事項",
    "section_code": "010101",
    "tags": ["動員開工", "授權文件"]
  }
```

#### 圖片（靜態服務）

```
GET /api/images/{folder}/{filename}
  # FastAPI StaticFiles 掛載 data_markdown/img/
  # 例：GET /api/images/010101動員開工檢核(104.09.24編修內文)/page-08.png
  Returns: image/png
```

#### 匯出

```
POST /api/export/excel
  Body:    { "form_data": { FormData }, "filename": "動員開工作業檢核表" }
  Returns: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet

POST /api/export/csv
  Body:    { "form_data": { FormData } }
  Returns: text/csv; charset=utf-8-sig   # BOM 確保 Excel 開啟中文正常
```

### 6.3 圖片靜態服務掛載（main.py）

```python
from fastapi.staticfiles import StaticFiles
import os

# 掛載圖片目錄（路徑從 backend/ 計算，實際圖片在 data_markdown/img/）
IMG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data_markdown", "img")
app.mount("/api/images", StaticFiles(directory=IMG_DIR), name="images")
```

> 注意：StaticFiles 掛載需在所有 router include 之後，避免路由衝突。

### 6.4 SSE 實作重點

```python
# chat.py router
@router.post("/stream")
async def chat_stream(request: ChatRequest, current_user: User = Depends(get_current_user)):
    async def event_generator():
        async for event in graph.astream_events(state, config):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"].content
                yield f"data: {json.dumps({'type':'text','content':chunk})}\n\n"
            elif event["event"] == "on_form_structured":
                yield f"data: {json.dumps({'type':'form','data':event['data']})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

## 7. LangGraph Agent 設計

### 7.1 GraphState

```python
from typing import TypedDict, Optional, List, Annotated
from langchain_core.messages import BaseMessage

class GraphState(TypedDict):
    # 對話識別
    conversation_id: str
    user_id: str

    # 訊息歷史（LangGraph 管理）
    messages: Annotated[List[BaseMessage], add_messages]

    # 當前查詢
    query: str

    # RAG 結果
    retrieved_chunks: List[dict]
    context: str

    # 意圖
    intent: str           # 'qa' | 'form_request'
    form_type: Optional[str]  # 表單類型（checklist/report/plan）

    # 生成結果
    response: str
    form_data: Optional[dict]  # 結構化表單 JSON
    sources: List[dict]         # 參考來源

    # Compact 控制
    is_compact_needed: bool
    token_count: int
    summary: Optional[str]
```

### 7.2 節點設計

#### 節點 1：compact_check

```python
# 入口節點：判斷是否需要壓縮歷史對話
def compact_check(state: GraphState) -> GraphState:
    token_count = count_tokens(state["messages"])
    state["token_count"] = token_count
    state["is_compact_needed"] = token_count > 8000
    return state
```

#### 節點 2：summarizer（僅在 compact 需要時執行）

```python
# 將舊訊息摘要，保留最近 4 輪完整訊息
async def summarizer(state: GraphState) -> GraphState:
    old_messages = state["messages"][:-8]   # 保留最近 4 輪（8條）
    summary = await llm.ainvoke(SUMMARIZE_PROMPT + old_messages)
    # 更新 state：移除舊訊息，加入摘要作為 system message
    # 同步儲存摘要至 PostgreSQL conversation_summaries
    return state
```

#### 節點 3：retriever

```python
# 從 ChromaDB 搜尋相關 chunks
async def retriever(state: GraphState) -> GraphState:
    results = await vector_store.asearch(
        query=state["query"],
        n_results=5,
        # 可選 filter：metadata 過濾
    )
    state["retrieved_chunks"] = results
    return state
```

#### 節點 4：context_builder

```python
# 組裝 context，處理圖片描述融入
def context_builder(state: GraphState) -> GraphState:
    context_parts = []
    for chunk in state["retrieved_chunks"]:
        text = chunk["document"]
        # 附加圖片描述（若有）
        if chunk["metadata"].get("has_images"):
            text += f"\n[相關圖示：{', '.join(chunk['metadata']['image_tags'])}]"
        context_parts.append(text)
    state["context"] = "\n\n---\n\n".join(context_parts)
    state["sources"] = extract_sources(state["retrieved_chunks"])
    return state
```

#### 節點 5：intent_classifier

```python
# 判斷使用者意圖：一般 QA 或表單請求
async def intent_classifier(state: GraphState) -> GraphState:
    # 輕量判斷：先用 keyword 規則，再用 LLM
    form_keywords = ["表單", "檢核表", "清單", "生成", "下載", "填寫"]
    if any(kw in state["query"] for kw in form_keywords):
        state["intent"] = "form_request"
    else:
        # 用 LLM 判斷
        ...
    return state
```

#### 節點 6：responder（串流）

```python
# 生成回覆，支援 SSE 串流
async def responder(state: GraphState) -> GraphState:
    prompt = build_prompt(
        context=state["context"],
        messages=state["messages"],
        intent=state["intent"],
        summary=state["summary"]
    )
    response = await llm.ainvoke(prompt)  # 串流由 astream_events 處理
    state["response"] = response.content
    return state
```

#### 節點 7：form_structurer（僅 form_request 時執行）

```python
# 將 LLM 輸出結構化成 JSON，不使用純文字轉換
# 先讓 LLM 輸出結構化 JSON schema，前端再渲染預覽
async def form_structurer(state: GraphState) -> GraphState:
    form_prompt = FORM_STRUCTURE_PROMPT.format(
        context=state["context"],
        query=state["query"],
        response=state["response"]
    )
    form_json = await llm.ainvoke(form_prompt)
    # 輸出格式：
    # {
    #   "form_type": "checklist",
    #   "title": "動員開工作業檢核表",
    #   "columns": ["項次", "作業內容", "辦理期限", "主辦單位", "完成狀態"],
    #   "rows": [...]
    # }
    state["form_data"] = parse_form_json(form_json.content)
    return state
```

### 7.3 Graph 邊設計

```python
def build_graph() -> CompiledGraph:
    graph = StateGraph(GraphState)

    # 加入節點
    graph.add_node("compact_check", compact_check)
    graph.add_node("summarizer", summarizer)
    graph.add_node("retriever", retriever)
    graph.add_node("context_builder", context_builder)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("responder", responder)
    graph.add_node("form_structurer", form_structurer)

    # 邊：入口
    graph.add_edge(START, "compact_check")

    # 條件邊：是否需要 compact
    graph.add_conditional_edges(
        "compact_check",
        lambda s: "summarizer" if s["is_compact_needed"] else "retriever"
    )

    # summarizer 完成後進入 retriever
    graph.add_edge("summarizer", "retriever")

    # RAG 流程
    graph.add_edge("retriever", "context_builder")
    graph.add_edge("context_builder", "intent_classifier")

    # 條件邊：意圖分流
    graph.add_conditional_edges(
        "intent_classifier",
        lambda s: "form_structurer" if s["intent"] == "form_request" else "responder"
    )

    # form_structurer → responder（讓 responder 加上說明文字）
    graph.add_edge("form_structurer", "responder")
    graph.add_edge("responder", END)

    # SQLite Checkpointer（對話持久化，取代 PostgreSQL）
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    checkpointer = AsyncSqliteSaver.from_conn_string(settings.langgraph_db_path)
    return graph.compile(checkpointer=checkpointer)
```

### 7.4 Prompt 設計

#### System Prompt（RAG QA）

```
你是一位專業的營造業內部知識助理，服務對象是公司內部員工。
根據以下參考文件，精確回答使用者的問題。

規則：
1. 優先使用參考文件中的資訊回答
2. 若文件中有相關表格或流程，直接呈現
3. 若使用者需要表單，先回覆說明，再觸發表單生成
4. 不確定的內容請明確說明「文件中未記載」

[對話摘要]
{summary}

[參考文件]
{context}
```

#### Form Structure Prompt

```
根據以下參考文件與使用者需求，輸出一個結構化 JSON 表單。

需求：{query}
文件內容：{context}

輸出格式（嚴格遵守）：
{
  "form_type": "checklist|report|plan|table",
  "title": "表單標題",
  "subtitle": "副標題（選填）",
  "columns": ["欄位1", "欄位2", ...],
  "rows": [
    {"欄位1": "值", "欄位2": "值", ...},
    ...
  ],
  "notes": "備註（選填）"
}
```

---

## 8. 前端架構設計

### 8.1 目錄結構

```
frontend/
├── package.json
├── yarn.lock
├── tailwind.config.ts
├── tsconfig.json
├── next.config.ts
│
├── app/
│   ├── layout.tsx                  # 根 Layout（字體、全域樣式）
│   ├── page.tsx                    # 根頁面（導向登入或對話）
│   │
│   ├── (auth)/                     # 認證頁面群組（不含 Sidebar）
│   │   ├── layout.tsx
│   │   ├── login/
│   │   │   └── page.tsx
│   │   └── register/
│   │       └── page.tsx
│   │
│   └── (app)/                      # 主應用頁面群組（含 Sidebar）
│       ├── layout.tsx              # 含 Sidebar、Header
│       ├── chat/
│       │   └── [conversationId]/
│       │       └── page.tsx        # 對話頁面
│       └── new/
│           └── page.tsx            # 新對話（自動建立後跳轉）
│
├── components/
│   ├── ui/                         # 基礎 UI 元件
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Modal.tsx
│   │   └── Spinner.tsx
│   │
│   ├── layout/
│   │   ├── Sidebar.tsx             # 左側對話歷史列表
│   │   └── Header.tsx
│   │
│   ├── chat/
│   │   ├── ChatWindow.tsx          # 對話視窗容器
│   │   ├── MessageBubble.tsx       # 單則訊息（user/assistant）
│   │   ├── MessageList.tsx         # 訊息列表（含自動捲動）
│   │   ├── InputBar.tsx            # 輸入列（含送出按鈕）
│   │   ├── SourcesPanel.tsx        # 參考來源展開面板
│   │   └── StreamingText.tsx       # SSE 串流文字元件
│   │
│   └── form/
│       ├── FormPreview.tsx         # 表單結構預覽（TablePreview）
│       ├── FormTable.tsx           # 表格渲染元件
│       └── ExportButton.tsx        # 下載 Excel/CSV 按鈕
│
├── lib/
│   ├── api.ts                      # Axios 封裝（帶 JWT header，401 → 自動 refresh）
│   ├── auth.ts                     # 登入/登出/refresh token 管理
│   └── sse.ts                      # SSE Fetch ReadableStream 封裝（需帶 Authorization header）
│
├── store/
│   ├── authStore.ts                # Zustand：使用者狀態、Access Token（記憶體存放）
│   └── chatStore.ts                # Zustand：對話列表、當前對話訊息暫存
│
└── types/
    └── index.ts                    # 全域 TypeScript 型別定義
```

### 8.2 SSE 接收設計

> **為何使用 Fetch ReadableStream 而非 EventSource**：
> `EventSource` 不支援自訂請求 header（無法帶 `Authorization: Bearer ...`），
> 因此改用 `fetch()` + `ReadableStream` 手動解析 SSE 格式。

```typescript
// lib/sse.ts
export async function streamChat(
  conversationId: string,
  message: string,
  onText: (text: string) => void,
  onForm: (formData: FormData) => void,
  onSources: (sources: Source[]) => void,
  onDone: () => void,
  signal?: AbortSignal   // 支援中止（使用者切換對話）
) {
  const { getAccessToken } = useAuthStore.getState();

  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${getAccessToken()}`
    },
    body: JSON.stringify({ conversation_id: conversationId, message }),
    signal  // AbortController.signal
  });

  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';   // 保留未完整的最後一行

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;
      const event = JSON.parse(raw);

      switch (event.type) {
        case 'text':    onText(event.content); break;
        case 'form':    onForm(event.data);    break;
        case 'sources': onSources(event.data); break;
        case 'done':    onDone();              return;
      }
    }
  }
}
```

### 8.3 Markdown 圖片渲染設計

```typescript
// components/chat/MessageBubble.tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// 自訂 img 渲染元件：加入錯誤處理、點擊放大
const MarkdownComponents = {
  img: ({ src, alt }: { src?: string; alt?: string }) => (
    <figure className="my-3">
      <img
        src={src}                       // 已是 /api/images/... 格式
        alt={alt ?? ''}
        className="max-w-full rounded border border-gray-200 cursor-zoom-in"
        onClick={() => openLightbox(src)}
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />
      {alt && <figcaption className="text-xs text-gray-500 mt-1">{alt}</figcaption>}
    </figure>
  )
};

// 使用方式
<ReactMarkdown remarkPlugins={[remarkGfm]} components={MarkdownComponents}>
  {message.content}
</ReactMarkdown>
```

> **圖片放大**：點擊圖片後在 Modal 中顯示原圖（Lightbox 效果），便於查看細節。

### 8.4 Axios 自動 Token 刷新（Interceptor）

```typescript
// lib/api.ts
const api = axios.create({ baseURL: '/api', withCredentials: true });

// Request interceptor：附上 Access Token
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor：401 → 自動 refresh
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status !== 401) return Promise.reject(error);
    // 嘗試 refresh（HttpOnly Cookie 自動帶上）
    const { data } = await axios.post('/api/auth/refresh', {}, { withCredentials: true });
    useAuthStore.getState().setAccessToken(data.access_token);
    // 重送原始請求
    error.config.headers.Authorization = `Bearer ${data.access_token}`;
    return api(error.config);
  }
);
```

### 8.5 表單預覽 → 下載流程

```
1. 後端 SSE 送出 {"type":"form","data":{...}}
2. FormPreview 元件渲染結構化表格（含欄位標題、資料列、備註）
3. 使用者確認後點擊「下載 Excel」或「下載 CSV」
4. POST /api/export/excel → 後端用 openpyxl 生成
5. 前端接收 Blob → URL.createObjectURL → 觸發瀏覽器下載
```

---

## 9. 分階段開發計畫

### Phase 0：環境設定與基礎建設

**目標**：建立可運行的開發環境、資料庫、基礎專案結構

**後端任務**：

- [ ] 初始化 uv 環境（`uv init`）
- [ ] 安裝核心依賴（fastapi, uvicorn, sqlalchemy, asyncpg, alembic, pydantic-settings, python-jose, bcrypt, chromadb, openai, langgraph, openpyxl）
- [ ] 建立 `app/config.py`（Settings class，讀取 .env）
- [ ] 建立 `app/database.py`（AsyncEngine、AsyncSession 工廠、Base）
- [ ] 建立所有 SQLAlchemy Model（user, conversation, message, summary）
- [ ] 設定 Alembic（`alembic init alembic`）
- [ ] 建立初始 migration 並執行（`alembic upgrade head`）
- [ ] 建立 `app/main.py`（FastAPI 初始化、lifespan、CORS）
- [ ] 確認 FastAPI 可啟動（`uvicorn app.main:app --reload`）
- [ ] 建立 `.gitignore`（含 chroma_db/, .env, __pycache__）

**前端任務**：

- [ ] 初始化 Next.js 15 App Router（`yarn create next-app`）
- [ ] 安裝 TailwindCSS、Zustand、Axios
- [ ] 建立基礎目錄結構
- [ ] 設定 `tailwind.config.ts`
- [ ] 設定 `next.config.ts`（API proxy → backend）
- [ ] 建立全域 `types/index.ts`

**驗收標準**：
- PostgreSQL 三張 table 存在
- FastAPI 啟動無錯誤
- Next.js 啟動顯示預設畫面

---

### Phase 1：RAG 資料管線

**目標**：完成 51 份文件的清理、切割、Embedding、寫入 ChromaDB

**任務清單**：

- [ ] 撰寫 `scripts/01_preprocess.py`
  - [ ] 掃描 `data_markdown/` 下所有 .md 檔
  - [ ] 識別 Type A / B / C（依檔名規則 + 內容特徵）
  - [ ] Type C：移除逐頁 code block 包裹、提取內文
  - [ ] 統一圖片引用格式（三種寫法 → 統一結構）
  - [ ] 移除 Type C 文末重複的圖片索引區塊
  - [ ] 輸出清理後的 `.md` 至 `scripts/output/cleaned/`

- [ ] 撰寫 `scripts/02_chunk.py`
  - [ ] Type A：以 H2 為邊界切割
  - [ ] Type B：以 H3 為邊界切割（含 H2 context_header）
  - [ ] Type C：語意段落切割（清理後）
  - [ ] Chunk 大小控制（80 ~ 1000 tokens）
  - [ ] 提取並結構化每個 chunk 的 metadata
  - [ ] 輸出 `scripts/output/chunks.jsonl`

- [ ] 撰寫 `scripts/03_generate_meta.py`
  - [ ] 讀取無 RAG 標籤的 chunks
  - [ ] 批量呼叫 GPT 生成 tags（每次 batch 10 個 chunk）
  - [ ] 輸出 `scripts/output/metadata_review.csv`

- [ ] **人工審查** `metadata_review.csv`（確認 tags 品質）

- [ ] 撰寫 `scripts/04_embed_ingest.py`
  - [ ] 初始化 ChromaDB persistent client
  - [ ] 批量呼叫 text-embedding-3-small
  - [ ] 寫入 ChromaDB（含 metadata）
  - [ ] 進度顯示（tqdm）

- [ ] 撰寫 `scripts/05_verify.py`
  - [ ] 驗證 ChromaDB 中 chunk 數量
  - [ ] 執行 5 筆測試查詢，確認結果合理
  - [ ] 輸出測試報告

**驗收標準**：
- ChromaDB collection 存在 chunks（數量合理，預計 300-600 個）
- 測試查詢「動員開工需要哪些初期計畫」能返回正確 chunks
- 所有 metadata 欄位完整

---

### Phase 2：後端核心 API

**目標**：完成認證、對話 CRUD、SSE 骨架

**認證（`app/api/auth.py`，`app/services/auth_service.py`）**：

- [ ] `POST /api/auth/register`：建立帳號、bcrypt 密碼、回傳 token
- [ ] `POST /api/auth/login`：驗證密碼、發放 JWT（access token 2h + refresh token 7d）
- [ ] `POST /api/auth/refresh`：refresh token → 新 access token
- [ ] `app/core/security.py`：JWT encode/decode、bcrypt hash/verify
- [ ] `app/core/dependencies.py`：`get_current_user` dependency

**對話管理（`app/api/conversations.py`，`app/services/conversation_service.py`）**：

- [ ] `GET /api/conversations`：返回使用者對話列表（含最後訊息預覽）
- [ ] `POST /api/conversations`：建立新對話
- [ ] `GET /api/conversations/{id}`：取得對話（含所有訊息、摘要）
- [ ] `DELETE /api/conversations/{id}`：刪除對話
- [ ] 訊息存取：讀取時合併摘要 + 最近訊息（compact 後的正確組裝）

**驗收標準**：
- 可成功註冊、登入、取得 JWT
- 可建立、列出、刪除對話
- Alembic migration 正常

---

### Phase 3：LangGraph Agent 整合

**目標**：完成 Agent 邏輯、RAG 搜尋、SSE 串流

**任務清單**：

- [ ] `app/rag/vector_store.py`：ChromaDB 連線、async search 封裝
- [ ] `app/rag/retriever.py`：搜尋邏輯（query → chunks → 格式化）
- [ ] `app/graph/state.py`：GraphState 定義
- [ ] `app/graph/nodes/compact.py`：compact_check + summarizer
- [ ] `app/graph/nodes/retrieval.py`：retriever 節點
- [ ] `app/graph/nodes/context.py`：context_builder 節點
- [ ] `app/graph/nodes/intent.py`：intent_classifier 節點
- [ ] `app/graph/nodes/generation.py`：responder 節點（串流）
- [ ] `app/graph/nodes/form.py`：form_structurer 節點
- [ ] `app/graph/builder.py`：組裝完整 Graph + PostgreSQL checkpointer
- [ ] `app/api/chat.py`：SSE endpoint，接收 Graph stream events
- [ ] 訊息存入 PostgreSQL（每次對話後）
- [ ] Compact 觸發後更新 `conversation_summaries` 表

**驗收標準**：
- 呼叫 `/api/chat/stream` 能收到 SSE 串流
- 回覆內容基於文件（非憑空捏造）
- 表單請求能輸出結構化 JSON
- 超過 8000 token 後 compact 正常觸發

---

### Phase 4：匯出功能

**目標**：Excel/CSV 生成與下載

**任務清單**：

- [ ] `app/services/export_service.py`：
  - [ ] `generate_excel(form_data) -> BytesIO`（openpyxl）
    - [ ] 支援 checklist 型表格（帶樣式：header 背景色、邊框）
    - [ ] 支援 report 型表格
    - [ ] 標題行、副標題、備註區
  - [ ] `generate_csv(form_data) -> str`
- [ ] `app/api/export.py`：
  - [ ] `POST /api/export/excel`：回傳 `application/vnd.openxmlformats...`
  - [ ] `POST /api/export/csv`：回傳 `text/csv; charset=utf-8-sig`（BOM，確保 Excel 開啟中文正常）

**驗收標準**：
- Excel 下載後可正常開啟，中文無亂碼
- 表格樣式正確，含標題與備註

---

### Phase 5：前端開發

**目標**：完整可用的聊天 UI

**認證頁面**：

- [ ] 登入頁（Email + 密碼，驗證錯誤提示）
- [ ] 註冊頁（Email + 密碼 + 確認密碼）
- [ ] Access Token 存 Zustand store（記憶體），Refresh Token 由後端 Set-Cookie 管理
- [ ] Axios interceptor：自動附帶 Token，401 自動 refresh
- [ ] 頁面重整時：自動呼叫 `/api/auth/refresh`（Cookie 自動帶上），恢復登入狀態
- [ ] 未登入自動跳轉登入頁

**對話介面**：

- [ ] `Sidebar.tsx`：對話歷史列表、新增對話按鈕、刪除對話
  - [ ] 對話標題可點擊進入編輯模式（inline rename）
  - [ ] 重新命名呼叫 `PATCH /api/conversations/{id}`
- [ ] `ChatWindow.tsx`：訊息列表容器
- [ ] `MessageBubble.tsx`：user（右側）/ assistant（左側）樣式
  - [ ] assistant 訊息使用 `react-markdown + remark-gfm` 渲染
  - [ ] 自訂 `img` 渲染元件（點擊放大 Lightbox）
- [ ] `StreamingText.tsx`：SSE 串流文字逐字顯示（含 cursor 動畫）
- [ ] `InputBar.tsx`：多行輸入、Enter 送出（Shift+Enter 換行）、送出時 disable、支援 AbortController 中止
- [ ] `SourcesPanel.tsx`：可折疊的參考來源面板（顯示 section_code + section_name + tags）
- [ ] 自動捲動到最新訊息（含串流中持續捲動）

**表單功能**：

- [ ] `FormPreview.tsx`：接收 form_data，渲染結構化表格預覽（含標題、欄位、備註）
- [ ] `ExportButton.tsx`：Excel / CSV 下載按鈕（帶 loading 狀態）
- [ ] 下載觸發（Blob + URL.createObjectURL）

**驗收標準**：
- 完整對話流程可用（輸入 → 串流回覆 → 顯示來源 → 圖片顯示）
- 頁面重整後自動恢復登入狀態（Refresh Token Cookie 有效）
- 對話可手動重新命名
- 表單預覽正確渲染，可下載 Excel / CSV
- 對話歷史在重整頁面後仍存在

---

### Phase 6：整合測試與調優

**目標**：確保系統穩定性與準確性

**任務清單**：

- [ ] 測試 10 個真實場景問題（新員工角度）
  - [ ] 「開工前需要辦理哪些對業主的事項？」
  - [ ] 「採購發包的金額分級是如何規定的？」
  - [ ] 「請幫我生成動員開工作業檢核表」
  - [ ] 「工務所辦公室要符合哪些 5S 標準？」
  - [ ] ...等
- [ ] 驗證 compact 機制（超長對話）
- [ ] 驗證對話歷史持久化（關閉重開）
- [ ] 調整 Top-K（預設 5，測試 3-8 效果）
- [ ] 調整 chunk 大小（若回覆品質不佳）
- [ ] 錯誤處理：OpenAI API 錯誤、ChromaDB 錯誤、DB 連線錯誤
- [ ] API Rate Limit 處理（exponential backoff）

---

## 10. 目錄結構總覽

```
data/                               # 專案根目錄
├── .env                            # 環境變數（gitignore）
├── .gitignore
├── PLAN.md                         # 本計畫書
├── data_markdown/                  # 原始 MD 文件
│   ├── img/                        # 圖片資源
│   └── *.md                        # 51 份文件
│
├── backend/
│   ├── pyproject.toml
│   ├── .python-version
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── chroma_db/                  # ChromaDB 持久化（gitignore）
│   ├── scripts/
│   │   ├── 01_preprocess.py
│   │   ├── 02_chunk.py
│   │   ├── 03_generate_meta.py
│   │   ├── 04_embed_ingest.py
│   │   ├── 05_verify.py
│   │   └── output/                 # 腳本輸出（gitignore）
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── models/
│       ├── schemas/
│       ├── api/
│       ├── services/
│       ├── rag/
│       ├── graph/
│       └── core/
│
└── frontend/
    ├── package.json
    ├── yarn.lock
    ├── tailwind.config.ts
    ├── next.config.ts
    ├── app/
    ├── components/
    ├── lib/
    ├── store/
    └── types/
```

---

## 11. Docker 打包規劃

> 後期實作，初期先以本地開發為主

### 11.1 服務組成

```yaml
# docker-compose.yml（規劃）
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data

  backend:
    build: ./backend
    depends_on: [postgres]
    volumes:
      - chroma_data:/app/chroma_db  # ChromaDB 持久化掛載
    environment:
      - DATABASE_URL=postgresql+asyncpg://...

  frontend:
    build: ./frontend
    depends_on: [backend]

volumes:
  postgres_data:
  chroma_data:
```

### 11.2 後端 Dockerfile（規劃）

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv sync
COPY app/ ./app/
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

---

## 12. 架構決策記錄（已確認）

所有設計決策已確認，紀錄如下：

| # | 決策項目 | 確認結果 | 實作位置 |
|---|---|---|---|
| 1 | ChromaDB Ingest 策略 | **增量更新**（hash 比對，只重新 embed 有變動的檔案） | `scripts/05_embed_ingest.py` |
| 2 | 使用者角色 | **單一角色**，無管理員 | `app/models/user.py` |
| 3 | Refresh Token 儲存 | **HttpOnly Cookie**（防 XSS） | `app/api/auth.py` |
| 4 | 對話標題 | **自動生成 + 使用者可手動重新命名** | `PATCH /api/conversations/{id}` |
| 5 | 圖片顯示 | **需顯示**，FastAPI StaticFiles 提供 `/api/images/`，切割時圖片不跨 chunk | `app/main.py` + `scripts/02_chunk.py` |
| 6 | 關聯式資料庫 | **SQLite（aiosqlite）取代 PostgreSQL**（PostgreSQL 安裝失敗） | `app/database.py`、`langgraph.db` |

---

## 13. 開發注意事項摘要

### 安全

- Access Token 僅存於 JavaScript 記憶體（Zustand），不寫入 localStorage / sessionStorage
- Refresh Token 使用 `HttpOnly; Secure; SameSite=Strict` Cookie
- 後端所有 API 均需 JWT 驗證（圖片靜態服務除外，可視需求加入認證）
- 密碼使用 bcrypt（work factor ≥ 12）

### 圖片切割

- 切割腳本在決定切割點前，必須偵測接下來是否有 `![` 或圖片說明區塊
- 若有，切割點延後至整個圖片區塊結束後
- 圖片路徑在 preprocess 階段統一改寫為 `/api/images/{folder}/{filename}` 格式

### ChromaDB 增量更新

- 每次執行 `05_embed_ingest.py` 前自動讀取 `scripts/output/file_hashes.json`
- 使用 `SHA256(file_content)` 作為比對依據
- 刪除舊 chunks 使用 `collection.delete(where={"source_file": "xxx"})`

### 前端 SSE

- 使用 `fetch()` + `ReadableStream`，**不使用** `EventSource`（因後者不支援自訂 header）
- 切換對話時需 `AbortController.abort()` 中止進行中的串流

### SQLite 注意事項

- `app.db` 和 `langgraph.db` 均加入 `.gitignore`
- SQLite 不支援原生 UUID 型別，所有 ID 欄位使用 `String(36)` 儲存 UUID 字串
- Alembic migration 須加 `render_as_batch=True`（SQLite ALTER TABLE 限制）
- 若未來需要切換 PostgreSQL，只需：
  1. 更換 `.env` 中的 `DATABASE_URL`（`postgresql+asyncpg://...`）
  2. 安裝 `asyncpg` + `psycopg2-binary`
  3. 重新產生 migration（UUID 型別需調整）
  4. 將 LangGraph checkpointer 改回 `AsyncPostgresSaver`

---

*計畫書版本 v1.2 — 2026-04-16 更新：資料庫改採 SQLite（PostgreSQL 安裝失敗）*
