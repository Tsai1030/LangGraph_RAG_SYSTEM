# System Design

本文件整理目前系統的實際設計與執行流程，重點描述目前程式碼中已存在的架構，而不是僅描述規劃中的理想版本。內容涵蓋後端、RAG、LangGraph、compact 與記憶、資料庫、SSE 串流，以及圖片與表格資料的處理方式。

## 1. 系統目標

本系統是一個以建築工程管理知識文件為核心的 RAG 問答系統，主要功能包括：

- 使用帳號登入後建立對話
- 對工程管理文件進行語意檢索
- 以 LangGraph 協調 compact、檢索、意圖判斷、回答生成與表單結構化
- 以 SSE 將回答逐 token 串流到前端
- 在特定情境下將回答進一步轉為結構化表單資料，供前端預覽與匯出 Excel/CSV
- 支援文件中的圖片引用，讓回答可直接輸出 `/api/images/...` 路徑給前端渲染

## 2. 技術組成

### 2.1 Backend

- FastAPI 作為 API 與 SSE 服務層
- SQLAlchemy 2.x + SQLite 儲存使用者、對話、訊息與摘要
- LangGraph 作為 Agent orchestration
- OpenAI：
  - `gpt-5.4` 作為主要 LLM
  - `text-embedding-3-small` 作為 embedding model
- ChromaDB 作為向量資料庫

### 2.2 Frontend

- Next.js App Router
- React
- SSE 串流接收 assistant 文字
- `react-markdown + remark-gfm` 呈現 assistant 的 Markdown 回答
- 前端直接以 `<img src="/api/images/...">` 呈現文件圖片

## 3. 系統高階架構

整體架構可拆為五層：

1. 文件預處理與切塊管線
2. ChromaDB 向量檢索層
3. FastAPI 應用層
4. LangGraph 對話協調層
5. 前端聊天與表單呈現層

核心資料流如下：

1. 原始 Markdown 文件放在 `data_markdown/`
2. 經過 preprocess、chunk、metadata、embedding 後寫入 ChromaDB
3. 使用者送出聊天訊息
4. FastAPI 建立 LangGraph 初始 state
5. LangGraph 依序執行 compact、retrieval、context、intent、form、generation
6. 回答透過 SSE 串流回前端
7. assistant 最終回覆與 metadata 寫回 SQLite

## 4. 目錄與職責分工

### 4.1 `backend/scripts/`

用於文件進庫前的資料管線：

- `01_preprocess.py`
  - 清理 Markdown
  - 統一圖片路徑
  - 補缺失的 Markdown 圖片語法
- `02_chunk.py`
  - 依文件型態切 chunk
  - 抽出 metadata
- `03_generate_meta.py`
  - 產生 tags
- `04_review_meta.py`
  - 匯入人工調整後的 tags
- `05_embed_ingest.py`
  - embedding 後寫入 ChromaDB
- `06_verify.py`
  - 驗證向量庫狀態

### 4.2 `backend/app/`

- `api/`
  - 對外 HTTP API
- `graph/`
  - LangGraph state、builder 與各節點
- `rag/`
  - 向量搜尋封裝
- `models/`
  - SQLAlchemy models
- `services/`
  - conversation CRUD、message 儲存、summary upsert 等

## 5. 文件處理與 RAG 建庫

### 5.1 原始資料來源

目前知識來源是 `data_markdown/*.md` 文件，以及 `data_markdown/img/` 下的圖片資產。

系統目前不是多模態向量檢索，圖片不會被獨立做 vision embedding，而是以「圖片引用 + 說明文字 + metadata」形式進入 chunk 與檢索流程。

### 5.2 預處理

`backend/scripts/01_preprocess.py` 主要做四件事：

1. 辨識文件型態 A / B / C
2. Type C 移除 PDF 掃描轉出的 ```` ```text ... ``` ```` 區塊
3. 將 `data_markdown/img/...` 改寫成 `/api/images/...`
4. 若只出現圖片路徑而未出現 `![]()` 語法，則自動補成 Markdown 圖片

這個階段的重點是：讓後續 chunk 與前端渲染都能使用統一的圖片 URL 格式。

### 5.3 文件型態

目前切塊邏輯採 A / B / C 三類規則：

- Type A：作業檢核表
- Type B：一般標準內文
- Type C：掃描 PDF 轉成 Markdown 的內容

這三類在 chunk 層分別套用不同策略。

### 5.4 Chunk 設計

`backend/scripts/02_chunk.py` 中定義：

- `CHUNK_MIN = 80`
- `CHUNK_TARGET = 500`
- `CHUNK_MAX = 1000`

token 使用 `tiktoken` 的 `cl100k_base` 編碼計算。

#### Type A

- 以 H2 為主切點
- 若偵測到大型 Markdown table，依每 20 列切成子 chunk
- 每個子 chunk 會保留表頭兩行，避免欄位語意完全消失

#### Type B

- 以 H3 為主切點
- H2 作為上層章節資訊，存入 metadata
- 若單段內容過長，則用空行切 paragraph 再重新組 batch

#### Type C

- 先清理殘留頁碼 header
- 再沿用接近 Type B 的切法
- 同樣在必要時以 paragraph 再次分割

### 5.5 Chunk Metadata

每個 chunk 目前包含：

- `chunk_id`
- `source_file`
- `section_code`
- `chapter`
- `phase`
- `document_type`
- `file_type`
- `tags`
- `parent_h1`
- `parent_h2`
- `parent_h3`
- `chunk_index`
- `has_images`
- `image_paths`
- `image_tags`
- `token_count`
- `text`

這些欄位除了供檢索結果組裝外，也會進入 ChromaDB metadata。

### 5.6 圖片資料處理

目前圖片策略是「文字代理圖片語意」：

- chunk 內若有 `![...](...)` 或 backtick 路徑，會抽出 `image_paths`
- 若文件中有「圖片說明 / 圖片標記」等文字，會抽出 `image_tags`
- `has_images` 代表此 chunk 含有圖片引用

因此圖片在 RAG 中的作用主要來自：

- 圖片 alt text
- 圖片說明文字
- chunk 內部的圖片相關描述
- metadata 中的 `image_paths` 與 `image_tags`

### 5.7 向量庫

目前向量庫固定為 ChromaDB，並不是可插拔式設計。

- collection name：`construction_knowledge`
- distance metric：cosine
- embedding model：`text-embedding-3-small`

`backend/scripts/05_embed_ingest.py` 會：

1. 讀取 `chunks_final.jsonl` 或 `chunks.jsonl`
2. 比對 `file_hashes.json`
3. 只重做變動檔案的 embedding
4. 先刪除該 `source_file` 舊資料
5. 再寫入新 chunk 到 ChromaDB

這是一套增量 ingest 設計，不是每次全量重建。

## 6. 後端應用層

### 6.1 FastAPI 啟動流程

`backend/app/main.py` 在 lifespan 中：

1. 開啟 `langgraph.db`
2. 建立 `AsyncSqliteSaver`
3. 呼叫 `checkpointer.setup()`
4. 將編譯後的 LangGraph 放進 `app.state.graph`

這代表 LangGraph 的 thread state 會透過 SQLite checkpointer 持久化。

### 6.2 圖片服務

目前圖片服務不是單純 `StaticFiles` 掛載，而是自訂 `/api/images/{image_path:path}` 路由。

其設計目的是同時支援：

- 直接命中 `img/<folder>/<file>`
- 某些圖片實際位於 `img/<folder_with_date>/<folder>/<file>`

也就是說，圖片查詢邏輯目前已包含路徑 fallback 與資料夾前綴比對，用來容忍原始圖片資料夾命名不完全一致的情況。

## 7. SQLite 業務資料庫設計

目前主要業務資料儲存在 `app.db`，使用 SQLAlchemy ORM。

### 7.1 `users`

儲存登入帳號資訊：

- `id`
- `email`
- `password_hash`
- `display_name`
- `is_active`
- `created_at`
- `updated_at`

### 7.2 `conversations`

儲存每個聊天對話：

- `id`
- `user_id`
- `title`
- `is_archived`
- `created_at`
- `updated_at`

### 7.3 `messages`

儲存對話訊息：

- `id`
- `conversation_id`
- `role`
- `content`
- `metadata` JSON 欄位
- `created_at`

assistant 訊息的 metadata 目前可能包含：

- `sources`
- `form_data`

### 7.4 `conversation_summaries`

用於 compact 後的摘要：

- `id`
- `conversation_id`
- `summary`
- `summarized_up_to_message_id`
- `summarized_message_count`
- `updated_at`

目前這張表是 compact 記憶的持久化層。

## 8. LangGraph 整體設計

LangGraph 是系統的對話協調核心。

### 8.1 GraphState

`backend/app/graph/state.py` 中的 `GraphState` 包含：

- 對話識別
  - `conversation_id`
  - `user_id`
- 訊息狀態
  - `messages`
  - `summary`
  - `token_count`
  - `is_compact_needed`
- RAG 狀態
  - `query`
  - `retrieved_chunks`
  - `context`
- 意圖與結構化輸出
  - `intent`
  - `form_type`
  - `form_data`
- 回覆輸出
  - `response`
  - `sources`

其中 `messages` 使用 `add_messages` reducer，這使得 LangGraph 在執行過程中可以 append 新訊息，也可透過 `RemoveMessage` 刪除舊訊息。

### 8.2 Graph 節點

目前節點如下：

- `compact_check`
- `summarizer`
- `retriever`
- `context_builder`
- `intent_classifier`
- `form_structurer`
- `responder`

### 8.3 Graph 流程

目前流程固定為：

`START -> compact_check`

如果不需 compact：

`compact_check -> retriever -> context_builder -> intent_classifier`

如果需要 compact：

`compact_check -> summarizer -> retriever -> context_builder -> intent_classifier`

接著依意圖分支：

- `qa -> responder -> END`
- `form_request -> form_structurer -> responder -> END`

### 8.4 Checkpointer 設計

LangGraph 編譯時會注入 `AsyncSqliteSaver`。

在 chat API 中使用：

- `config = {"configurable": {"thread_id": conversation_id}}`

這代表每個 conversation 會成為獨立 thread，LangGraph 的 state 會和該 conversation 綁定。

## 9. Compact 與記憶設計

目前 compact 與記憶是本系統非常重要的一層。

### 9.1 Compact 觸發條件

`backend/app/graph/nodes/compact.py` 中：

- `COMPACT_THRESHOLD = 8000`

`compact_check` 會對目前 state 中的 `messages` 計算 token 數，如果超過 8000，則回傳：

- `is_compact_needed = True`

### 9.2 Token 計算方式

目前 token 計數只看 `state["messages"]`，使用 `tiktoken` 對每則 message content 做估算。

這表示 compact 的依據是：

- LangGraph thread 中目前保留的 human / ai messages

而不是：

- SQLite `messages` 表中的所有歷史
- `summary`
- RAG `context`

### 9.3 Summarizer 行為

當 compact 觸發時：

1. 保留最近 `KEEP_RECENT = 8` 則訊息
2. 把更早的訊息整理成純文字歷史
3. 呼叫 LLM 產出摘要
4. 使用 `RemoveMessage` 刪除舊訊息
5. 將摘要寫入 `conversation_summaries`
6. 把 `summary` 回寫到 graph state

這個設計可視為「短期記憶 + 長期摘要記憶」雙層結構：

- 短期記憶：最近 8 則訊息保留在 `messages`
- 長期記憶：更早對話濃縮成 `summary`

### 9.4 記憶如何進入生成

在 `backend/app/graph/nodes/generation.py` 中，`_build_messages()` 會：

1. 先組出一個 SystemMessage
2. 若 state 中有 `summary`，則插入 `[對話摘要]`
3. 再把 `context` 放進 system prompt
4. 最後把 thread 中保留的 human / ai messages 接到後面

因此生成模型看到的記憶結構是：

- System prompt
- 摘要記憶
- RAG context
- 最近對話訊息

這是你目前對話記憶的核心設計。

### 9.5 目前 compact 設計的特性

優點：

- 不需保留整段長歷史到 prompt
- 可減少 token 消耗
- 摘要可持久化到 SQLite
- thread state 又可透過 LangGraph checkpointer 保存

目前限制：

- `summarized_up_to_message_id` 目前寫入空字串，尚未真的對齊 DB message id
- compact 只看 LangGraph state messages，不直接讀完整 DB 歷史
- 摘要品質完全依賴 LLM，尚未做多層摘要或摘要驗證

## 10. RAG 查詢與上下文組裝

### 10.1 Retriever

`backend/app/graph/nodes/retrieval.py` 會直接呼叫 `app.rag.retriever.retrieve()`，預設：

- top-k = 5

### 10.2 Vector Search

`backend/app/rag/vector_store.py` 的流程是：

1. 用 OpenAI Async client 對 query 做 embedding
2. 使用 ChromaDB `collection.query()`
3. 回傳：
   - `document`
   - `metadata`
   - `distance`

ChromaDB 是同步 API，所以用 `asyncio.to_thread` 包裝，避免阻塞 FastAPI event loop。

### 10.3 Source 組裝

`backend/app/rag/retriever.py` 的 `format_sources()` 會：

- 以 `(source_file, section_code)` 去重
- 從 `parent_h3` 或 `parent_h2` 推出 section 名稱
- 盡量把 metadata 中的 tags 轉回 list

這個結果最後會送到前端 `SourcesPanel`。

### 10.4 Context Builder

`backend/app/graph/nodes/context.py` 會把 retrieved chunks 組成 prompt context。

目前做法：

- 在每個 chunk 前附加來源與章節
- 若 chunk 含圖片，理論上附加圖片 tags
- 用 `---` 分隔各 chunk

這一層是 RAG 對 LLM 的最後輸入整理點。

## 11. 意圖判斷與結構化輸出

### 11.1 Intent Classifier

`backend/app/graph/nodes/intent.py` 採兩段式判斷：

1. 先用關鍵字快速判斷
2. 若關鍵字沒命中，再交給 LLM 判斷

目前只有兩類意圖：

- `qa`
- `form_request`

### 11.2 Form Structurer

若 intent 是 `form_request`，則進入 `form_structurer`：

1. 把 `query + context` 交給 LLM
2. 要求輸出純 JSON
3. 解析為 `form_data`

目前支援的 form type 概念包括：

- `checklist`
- `report`
- `plan`
- `table`

### 11.3 Responder

`responder` 是最終回答生成節點。

其 system prompt 會同時包含：

- 回答規則
- compact 摘要
- RAG context
- 若已產生 `form_data`，則額外加入結構化輸出的提示

生成模型使用：

- `ChatOpenAI`
- `streaming=True`

因此 LangGraph 可以把模型串流事件暴露給 chat API。

## 12. Chat API 與 SSE 設計

`backend/app/api/chat.py` 是聊天主入口。

### 12.1 請求處理流程

1. 驗證 conversation 是否存在且屬於目前使用者
2. 先把 user message 寫入 `app.db`
3. 若 conversation 尚無 title，截前 30 字自動設標題
4. 從 `conversation_summaries` 讀出既有摘要
5. 建立 LangGraph `initial_state`
6. 執行 `graph.astream_events(...)`
7. 將 responder 的 token 逐步轉為 SSE text event
8. graph 結束後再補送 `sources` 與 `form`
9. 最後送 `done`
10. 把最終 assistant 回答與 metadata 寫回 `app.db`

### 12.2 SSE Event 類型

目前對前端輸出的 event 包括：

- `text`
- `sources`
- `form`
- `error`
- `done`

### 12.3 Assistant 訊息落庫

assistant 回覆不是每個 token 都存，而是在串流結束後把整段合併成一則訊息落庫。

若 graph 有成功產出：

- `sources`
- `form_data`

則會寫進 assistant message metadata。

## 13. 前端呈現邏輯

前端 assistant 訊息以 Markdown 呈現，因此模型可以輸出：

- 一般文字
- 清單
- 表格
- 圖片 `![](/api/images/...)`

圖片直接透過 `/api/images/...` 取得，因此回答內嵌圖片成為可行設計的一部分。

若後端另外回傳 `form_data`，前端可同時顯示：

- assistant 文字回答
- 結構化表單預覽
- 匯出按鈕

## 14. 已實作設計與目前限制

### 14.1 已實作

- FastAPI + SQLite + LangGraph 主體已成形
- 對話、訊息、摘要資料表已存在
- compact 機制已存在
- LangGraph checkpointer 已存在
- ChromaDB 向量檢索已存在
- SSE 串流已存在
- 圖片 URL 服務已存在
- form_request 分支已存在

### 14.2 目前限制與實況

1. 向量庫目前固定為 ChromaDB，不是可切換架構
2. 圖片是文字代理式處理，不是多模態檢索
3. 表格只有部分型態在 chunk 時有特殊處理
4. compact 目前尚未精準對齊 `summarized_up_to_message_id`
5. `context_builder` 對 `image_tags` 的使用，會受到 metadata 在 Chroma 中被序列化成字串的影響
6. Type C 文件辨識仍帶有資料集導向的 hard-coded 成分
7. 圖片路徑目前有額外 fallback 邏輯，代表原始圖片目錄結構尚未完全標準化

## 15. 目前系統的核心設計判讀

如果用一句話概括，你目前的系統設計是：

> 一個以 Markdown 工程管理文件為知識底座、以 ChromaDB 做語意檢索、以 LangGraph 管理記憶與生成流程、以 SSE 串流對話結果、並可在特定意圖下輸出結構化表單資料的工程知識助理系統。

其中特別值得注意的設計特色有三個：

1. 對話記憶不是單純靠 DB 重讀，而是同時結合 LangGraph thread state、SQLite checkpointer、與 conversation summary
2. RAG 與生成是分離節點，使未來可替換 rerank、filter、form routing 等策略
3. 圖片不是外掛功能，而是整個知識文件系統的一部分，從 preprocess、chunk、metadata 到回答輸出都已進入主流程

## 16. 建議後續文件維護方式

若未來要持續維護本文件，建議每次系統調整時同步更新以下段落：

- 第 5 章：若 chunk、圖片、表格、metadata 規則改變
- 第 8 章與第 9 章：若 LangGraph 節點、compact、memory 改變
- 第 10 章與第 12 章：若檢索、SSE、sources、form 輸出改變
- 第 14 章：用來標註目前實作與理想設計的差距
