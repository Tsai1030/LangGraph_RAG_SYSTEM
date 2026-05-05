# 營造知識助理 — LangGraph RAG + Form Agent

營造業內部知識問答系統，整合 Adaptive RAG、CRAG 閉環修正、結構化意圖分類、靜態 Word 表單填寫 agent，以及對話式長期記憶。

---

## 目錄

1. [系統概覽](#系統概覽)
2. [技術棧](#技術棧)
3. [系統架構](#系統架構)
4. [LangGraph 狀態機設計](#langgraph-狀態機設計)
5. [unified_intent — 統一意圖分類](#unified_intent--統一意圖分類)
6. [表單系統設計](#表單系統設計)
7. [RAG 檢索設計](#rag-檢索設計)
8. [記憶系統設計](#記憶系統設計)
9. [資料庫設計](#資料庫設計)
10. [傳輸層設計](#傳輸層設計)
11. [安全性設計](#安全性設計)
12. [前端設計](#前端設計)
13. [可觀測性與維運](#可觀測性與維運)
14. [專案結構](#專案結構)
15. [環境設定與啟動](#環境設定與啟動)

---

## 系統概覽

```
使用者 → 前端 (Next.js) → FastAPI → LangGraph
                                       ├─ unified_intent（單 LLM call + 5 fast-paths 決定 5 種 intent）
                                       ├─ Hybrid RAG（intra-query Vector+BM25 RRF / inter-query rewrite RRF）
                                       ├─ CRAG 閉環（grader + query rewriter，上限 2 次）
                                       ├─ 靜態表單下載（registry 比對 + 認證下載）
                                       ├─ 靜態表單 AI 代填（schema-driven，多輪欄位收集 + 批次編輯 + 代寫）
                                       ├─ 動態表單生成（Function Calling + Pydantic + 多輪延續）
                                       ├─ 串流回覆（SSE）
                                       └─ Token-based 記憶壓縮（8000 token 閾值）
                                   ↓
                              SQLite (對話 + 摘要)         ChromaDB (向量)
                              langgraph.db (graph state)   data/generated_forms/ (已填寫 .docx)
```

### 主要能力

- **問答**：營造規範、流程、條文檢索與整合回答（Adaptive + CRAG）
- **靜態表單下載**：對 3 份預建檢核表（動員開工 / 工務所辦公室設置 / 工地文件管制）一鍵下載空白檔
- **靜態表單 AI 代填**：使用者用自然語言描述要填的內容，agent 收集後寫入 Word 並回傳；支援批次編輯、AI 代寫長文字、編輯已完成填寫
- **動態表單生成**：對沒有對應靜態表的需求，依 RAG context 即時生成結構化檢核表 / 報告書 / 計畫書 / 一般表格

---

## 技術棧

### 後端

| 類別 | 套件 |
|------|------|
| Web Framework | FastAPI |
| 狀態機 / Agent | LangGraph、LangChain |
| LLM / Embedding | OpenAI（GPT-5.4 系列、text-embedding-3-small） |
| 向量資料庫 | ChromaDB（本地持久化、版本化） |
| BM25 | rank-bm25 |
| 中文分詞 | jieba（含 4,948 個營造業自訂詞典） |
| 文件處理 | python-docx（讀寫 .docx 模板） |
| Token 計算 | tiktoken |
| ORM | SQLAlchemy（Async）+ aiosqlite |
| Migration | Alembic |
| 認證 | python-jose（JWT）、bcrypt |
| 匯出 | openpyxl（Excel） |
| 可觀測性 | LangSmith |

### 前端

| 類別 | 套件 |
|------|------|
| Framework | Next.js（App Router）、TypeScript |
| 樣式 | Tailwind CSS v4 |
| 狀態管理 | Zustand |
| Markdown | react-markdown、remark-gfm |
| UI 元件 | shadcn/ui（base-ui 內核） |
| 圖示 | lucide-react |

---

## 系統架構

```
data/
├── backend/                           # FastAPI 後端
│   ├── app/
│   │   ├── api/                       # REST + SSE 端點
│   │   ├── core/                      # JWT、bcrypt
│   │   ├── graph/
│   │   │   ├── builder.py             # 組裝 StateGraph 與條件邊
│   │   │   ├── state.py               # GraphState TypedDict
│   │   │   └── nodes/                 # 11 個節點
│   │   ├── models/                    # SQLAlchemy ORM
│   │   ├── rag/
│   │   │   ├── form_lookup.py         # 靜態表 registry 召回
│   │   │   ├── form_registry.json     # 表單 metadata（form_id / keywords / 顯示名）
│   │   │   ├── form_schemas/*.json    # 三份表的欄位 schema
│   │   │   ├── retriever.py           # Hybrid RRF 檢索
│   │   │   └── vector_store.py        # ChromaDB 包裝
│   │   ├── services/
│   │   │   ├── conversation_service.py
│   │   │   └── form_fill_writer.py    # 把 collected 寫入 .docx 副本
│   │   └── main.py                    # FastAPI app + lifespan
│   ├── data/generated_forms/          # 已填寫的 .docx（gitignored）
│   ├── scripts/
│   │   ├── build_form_schemas.py      # 從 .docx 離線產生欄位 schema
│   │   ├── cleanup_orphan_forms.py    # 清理已刪對話的殘留 docx 與 langgraph 線程
│   │   └── 01_preprocess.py … 07     # 知識庫向量索引 pipeline
│   └── tests/
│       └── test_unified_intent.py     # 24 個測試（純函式 + mock LLM）
├── frontend/                          # Next.js 前端
│   ├── app/(app)/                     # 主版型（sidebar + 內容）
│   ├── components/
│   │   ├── chat/
│   │   │   ├── InputBar.tsx
│   │   │   ├── FormPickerButton.tsx   # 上拉選單：選表單 + 下載 / AI 代填
│   │   │   ├── FormFileCard.tsx
│   │   │   └── MessageBubble.tsx
│   │   └── layout/Sidebar.tsx
│   ├── lib/                           # API client、SSE
│   └── store/                         # Zustand
├── data_markdown/
│   ├── form_data/*.docx               # 三份原始表單範本
│   └── *.md                           # 知識庫 Markdown 原文
└── README.md
```

---

## LangGraph 狀態機設計

### GraphState

```python
class GraphState(TypedDict):
    conversation_id: str
    user_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    query: str

    # RAG
    retrieved_chunks: list[dict]
    context: str
    sources: list[dict]

    # 意圖（unified_intent 輸出）
    intent: str   # 'qa' | 'static_form_download' | 'static_form_fill'
                  # | 'dynamic_form_generate' | 'form_continuation'
    form_type: Optional[str]

    # 生成結果
    response: str
    form_data: Optional[dict]   # 動態表單

    # 壓縮
    is_compact_needed: bool
    token_count: int
    summary: Optional[str]

    # 路由
    need_retrieval: bool
    retrieval_query: Optional[str]
    retry_count: int
    retrieval_grade: str
    grader_reason: Optional[str]
    grader_missing_information: Optional[str]

    # 靜態表單匹配
    matched_forms: list[dict]
    form_explicit: bool

    # 動態表單延續
    prev_form_data: Optional[dict]
    is_form_continuation: bool

    # 靜態表單填寫 session（checkpointer 跨輪持久化）
    form_fill_session: Optional[dict]
    # {
    #   "target_form_id": "010101",
    #   "collected": {key: value},
    #   "status": "collecting" | "ready" | "completed",
    #   "filled_token": "<filename>",
    #   "filled_field_count": int,
    #   "last_bulk_edit": "...",
    #   "last_ghost_written": [keys],
    # }
```

### 流程圖

```
START
  └─► compact_check（tiktoken 計 token；> 8000 觸發摘要）
        ├─ true ─► summarizer ─┐
        └─ false ──────────────┘
                                ▼
                      unified_intent（單 LLM call，輸出 5 種 intent 之一）
                       │
                       ├─ static_form_download → [responder ∥ source_filter] → END
                       │
                       ├─ static_form_fill → form_template_loader
                       │                      ↓
                       │                  form_fill_collector
                       │                      ├─ status=ready → form_filler → responder → END
                       │                      └─ status=collecting → responder → END
                       │
                       ├─ qa（need_retrieval=false）→ [responder ∥ source_filter] → END
                       │
                       └─ qa / dynamic_form_generate / form_continuation （need_retrieval=true）
                              ↓
                          retriever → context_builder → retrieval_grader
                              ├─ insufficient (retry < 2) → query_rewriter → retriever
                              └─ sufficient / max retries
                                    ├─ form 類 → form_structurer → [responder ∥ source_filter] → END
                                    └─ qa ────────────────────► [responder ∥ source_filter] → END
```

### 節點清單

| 節點 | 模型 | 功能 |
|------|------|------|
| `compact_check` | — | tiktoken 計算 token，> 8000 觸發摘要 |
| `summarizer` | llm_model | 保留最近 8 則訊息，舊訊息壓縮為 ≤300 字摘要寫回 SQLite |
| `unified_intent` | grader_model | 單一 LLM call + 5 fast-paths 決定 intent / target_form_id / need_retrieval；詳見[下節](#unified_intent--統一意圖分類) |
| `retriever` | — | Hybrid RAG：Vector+BM25 intra-query RRF；有 retrieval_query 時兩路 inter-query RRF |
| `context_builder` | — | chunks 格式化為 LLM context，注入來源標頭與 Markdown 圖片語法 |
| `retrieval_grader` | grader_model | structured output GraderOutput，回傳 sufficient/insufficient + missing_information |
| `query_rewriter` | grader_model | 依 missing_information 改寫 query，遞增 retry_count |
| `form_structurer` | form_model | Function Calling + Pydantic 生成動態表單 JSON；注入 prev_form_data 避免重複 |
| `form_template_loader` | — | 確保 form_fill_session 處於可填寫狀態（新建/切表/重啟編輯） |
| `form_fill_collector` | grader_model | LLM 抽欄位意圖 → code 列舉並套用（單欄抽取、批次編輯、代寫、自動填） |
| `form_filler` | — | 用 python-docx 把 collected 寫入模板副本，存到 generated_forms/ |
| `responder` | llm_model | 串流回覆；依 intent + session 狀態切換系統提示（短確認 / 追問欄位 / 完整 RAG） |
| `source_filter` | grader_model | 與 responder 並行；過濾 retrieved_chunks 為實質貢獻來源（前端 SourcesPanel）|

### CheckPointer

- LangGraph `AsyncSqliteSaver` 持久化 GraphState 於獨立的 `langgraph.db`
- 每個對話對應一個 `thread_id = conversation_id`
- 應用啟動時 `await checkpointer.setup()` 自動建表

---

## unified_intent — 統一意圖分類

### 設計理念

舊架構是 `retrieval_router (LLM)` + `intent_classifier (LLM 或 keyword)` 雙層判斷，兩組 keyword 互相誤觸發、判斷不一致。中間版本合併為單一 node + 多條 keyword fast-path，但隨意圖種類增加，keyword 集合膨脹（曾達 51 條）並出現「短訊息誤判」問題（例：使用者深度討論中說『我要 X 的詳細說明』被字面騙成索取靜態檔）。

**現行架構**：純 LLM 判斷 + post-normalization。除「冷啟動 → qa」零成本路徑外，全部交給 LLM，由 prompt 與 few-shot 教規則。

| 層 | 由誰判斷 | 為什麼 |
|---|---|---|
| **冷啟動 fast-path**（程式碼） | 旗標檢查 | 首輪 + 無候選 + 無前輪表單 + 無 session → 必為 qa，不打 LLM 省一次 API |
| **LLM 主判斷** | grader_model（gpt-5.4） + structured output | 看完整對話脈絡，不被單一動詞字面騙 |
| **Post-normalization**（程式碼） | 規則校驗 | 防 LLM 越界輸出（不存在的 form_id、缺 retrieval_topic、active session target 沿用等） |

設計取捨：每輪多一次 LLM call（≈300-800ms），換取**上下文敏感度**與**零 keyword 維護負擔**。在 RAG 系統裡這個延遲與 retriever / responder 比起來微不足道。

### 5 個 Intent

| Intent | 說明 |
|---|---|
| `qa` | 知識問答；matched_forms 仍可帶下載提示 |
| `static_form_download` | 索取既有表單空白檔下載 |
| `static_form_fill` | 把資料填寫進既有表單，agent 寫好回傳 |
| `dynamic_form_generate` | 沒對應靜態表，RAG 後即時生成結構化表單 |
| `form_continuation` | 延續上一輪生成過的動態表單（再來幾組） |

### 流程

```
input 準備
  ├─ candidates = _resolve_candidates(query, recent_messages)   # query 命不中時 fallback 對話歷史
  ├─ has_prior_ai / prev_form_data / fill_session
  └─ recent = 最近 3 輪訊息（給 LLM 看）

冷啟動 fast-path
  if not has_prior_ai and not candidates and not prev_form_data
     and fill_session.status not in ("collecting", "completed"):
     → return qa, need_retrieval=true（不打 LLM）

否則 → _llm_classify (with_structured_output(IntentDecision))
        ├─ prompt 含對話歷史 / 候選表 / prev_form / fill_session 詳情
        ├─ few-shot 11 個範例覆蓋邊界 case（含「我要 X 的詳細說明 = qa」這類舊 fast-path 誤判）
        └─ 輸出 (intent, target_form_id, retrieval_topic, need_retrieval, reason)
        ↓
      _normalize_decision 校驗
        ├─ static_form_* + target 不在候選 ∪ session id  → 退回 qa
        ├─ static_form_* 但 target=null 且有 session → 沿用 session.target
        └─ form_continuation 缺 prev_form_data 或 retrieval_topic → 改 dynamic_form_generate
        ↓
      _build_state_update 組 graph state 變更
```

### IntentDecision schema

```python
class IntentDecision(BaseModel):
    intent: Literal["qa", "static_form_download", "static_form_fill",
                    "dynamic_form_generate", "form_continuation"]
    target_form_id: Optional[str]      # static_form_* 必填
    retrieval_topic: Optional[str]     # form_continuation 必填
    need_retrieval: bool
    reason: str                         # 30 字內判斷依據（LangSmith / log 可追）
```

`reason` 欄位是核心 debug 機制：每次推理都自帶可解釋說明，例如：
- `「明確詢問內容解說，非續填表」` — 判 qa 的依據
- `「已完成表單的編輯指令，沿用session」` — 判 static_form_fill 的依據

### 候選召回（_resolve_candidates）

- 先用 `lookup_forms(query)` 比對 form_registry keywords
- 命不中時 fallback 拼接最近 3 輪對話文字再比對一次

→ 解決使用者第二輪只說「我想要填入資訊」（無表名）時，能繼承上一輪提到的表單。

### 程式碼結構

```
unified_intent.py（≈210 行）
├── Schema:        IntentDecision
├── System prompt: 5 intent 定義 + 決策原則 + 11 個 few-shot
├── Pure helpers:  _resolve_candidates / _resolve_form_meta
│                  _build_history_text / _build_user_prompt
│                  _normalize_decision / _build_state_update
├── LLM wrapper:   _llm_classify
└── Graph node:    unified_intent (主流程約 25 行)
```

純函式分離讓單元測試容易（24 個測試，全 mock LLM，不需 API key 即可在 CI 跑）。

### CRAG 閉環

`retrieval_grader` 用 structured output 評估 context 品質：

```python
class GraderOutput(BaseModel):
    decision: Literal["sufficient", "insufficient"]
    reason: str
    missing_information: str
```

- **sufficient** → 進下一階段（form_structurer 或 responder）
- **insufficient** + retry < 2 → `query_rewriter` 依 `missing_information` 改寫 → 重新檢索
- 達上限強制繼續，不無限循環

---

## 表單系統設計

整個系統有**三條表單路徑**，互不衝突：

| 路徑 | 觸發 | 流程 |
|---|---|---|
| **靜態表單下載** | `intent=static_form_download` | unified_intent 直接給 download_url，responder 短確認，前端 FormFileCard 下載 |
| **靜態表單 AI 代填** | `intent=static_form_fill` | template_loader → fill_collector（多輪）→ filler → 產出新 .docx |
| **動態表單生成** | `intent=dynamic_form_generate` 或 `form_continuation` | retriever → form_structurer (Function Calling) → 結構化 JSON |

### 靜態表單 Registry

`backend/app/rag/form_registry.json` 列出三份表的 metadata：

```json
[
  {
    "form_id": "010101",
    "display_name": "動員開工作業檢核表",
    "file_name": "010101動員開工作業檢核表.docx",
    "keywords": ["動員開工", "開工", "動員", "工程啟動", "進場", ...]
  }
]
```

`lookup_forms(query)` 純粹做候選召回（substring keyword 比對），最終決策由 unified_intent 處理。

### 靜態表單 AI 代填（核心新功能）

**離線階段**：[`scripts/build_form_schemas.py`](backend/scripts/build_form_schemas.py) 解析每份 .docx 生成欄位 schema JSON，存於 `app/rag/form_schemas/{form_id}.json`：

```json
{
  "form_id": "010101",
  "title": "動員開工作業檢核表",
  "file_name": "010101動員開工作業檢核表.docx",
  "fields": [
    { "key": "工程名稱", "label": "工程名稱", "type": "text",
      "required": true,
      "loc": { "kind": "para", "para_idx": 1, "marker": "工程名稱:", "marker_end": "\t" } },
    { "key": "tbl0_r2_status", "label": "編號 2.1「組織提報」 — 完成狀態",
      "type": "checkbox_vx", "required": false,
      "loc": { "kind": "cell", "table_idx": 0, "row": 2, "col": 7 } }
  ]
}
```

支援的欄位 type：`text` / `date` / `checkbox_vx`（自動正規化「完成」→「V」、「未完成」→「X」）。

| 表單 | 欄位數 |
|---|---|
| 010101 動員開工作業檢核表 | 58 |
| 010102 工務所辦公室設置作業檢核表 | 72 |
| 010315 工地文件管制與保存表 | 268 |

**多輪互動 session**：`form_fill_session` 由 LangGraph checkpointer 跨輪持久化，不需前端管理。

**form_fill_collector** 用 LLM structured output 表達**意圖**（不要求 LLM 列舉所有 key），由 code 列舉與套用：

```python
class _Extraction(BaseModel):
    extracted: list[_ExtractedField] = []      # 點對點：使用者明確指定某欄位的值
    ghost_written: list[_ExtractedField] = []  # AI 代寫：使用者請 LLM 自己擬內容（限 type=text）
    bulk_edits: list[_BulkEdit] = []           # 批次編輯：「把備註改成 X」這種一次更新一群欄位
    user_done: bool                            # 結束指令（就這樣 / OK / 改完了）
    auto_fill_test: bool                       # 全部填佔位值（隨便填 / 全部 test）
    reason: str
```

`_BulkEdit` 用 `label_keywords: list[str]`（AND 邏輯）讓 LLM 只描述條件，code 自動枚舉所有 label 含這些關鍵字的 key。例：

| 使用者訊息 | LLM 輸出 | code 套用 |
|---|---|---|
| 「把備註的 test 改成 123」 | `{label_keywords:["備註"], old_value:"test", new_value:"123"}` | 找出 36 個 label 含「備註」且現值 = "test" 的 key，全改 |
| 「2.1 的備註改成 done」 | `{label_keywords:["2.1","備註"], new_value:"done"}` | label 同時含「2.1」與「備註」的 1 個 key |
| 「全部完成狀態打勾」 | `{label_keywords:["完成狀態"], new_value:"V"}` | 36 個狀態欄改 V |

**為什麼這樣設計**：mini 模型對「列舉 36 筆 key/value JSON」常會放棄；改成只輸出 1 筆意圖 spec、code 自己枚舉 → 穩定且乾淨。

### 寫入 .docx（form_filler）

[`form_fill_writer.write_filled_docx`](backend/app/services/form_fill_writer.py)：

- 段落欄位：regex `re.escape(marker) + r"[^\t\n]*"` 取代到行尾的舊值（idempotent，重填不重複追加）
- 表格儲存格：直接 `cell.text = value`
- checkbox：`_coerce_value` 把 `完成 / V / yes / 1` → `V`，`未完成 / X / no / 0` → `X`
- 輸出檔名 `<conversation_id>_<form_id>_<timestamp>.docx`，存於 `data/generated_forms/`

### 完整對話範例

```
U: 我要填動員開工檢核表          → fast-path 2 → 開新 session
A: 收到，請先提供：工程名稱、工令、製表日期...
   也可一次描述多個欄位，或輸入「就這樣」/「全部填 test」立即下載

U: 工程名稱叫和平大樓，工令BES-001  → LLM extracted=[(工程名稱,...), (工令,...)]
A: 已收到工程名稱、工令。請再提供：製表日期、1.19 完成狀態...

U: 全部填test                    → auto_fill_test → 所有欄位佔位填 V/test
A: 已將您的資料填入《動員開工作業檢核表》，請點選下方下載。 [下載按鈕]

U: 把備註的 test 改成 123        → fast-path 4 → resume completed → bulk_edit 36 欄
A: 已將 36 個含「備註」的欄位更新為「123」，輸入「就這樣」下載新版本

U: 就這樣                        → user_done → filler 重跑 → 新下載連結
```

### 動態表單生成

對於沒有對應靜態表的需求（候選為空 / 使用者要新版本），`form_structurer` 用 Function Calling 即時生成：

```python
class FormSchema(BaseModel):
    form_type: Literal["checklist", "report", "plan", "table"]
    title: str
    subtitle: Optional[str] = None
    columns: list[str]
    rows: list[str]      # pipe-separated 字串："欄1值|欄2值|欄3值"
    notes: Optional[str] = None
```

> `rows` 用 `list[str]` 而非 `list[dict]` 是因為 `dict[str, str]` 在 Function Calling JSON Schema 會產生 `additionalProperties` 導致模型略過該欄位。Python 側再轉換為 `list[dict]`。

支援多輪延續：`prev_form_data` 自 checkpointer 載入前輪結果，prompt 注入避免重複內容。

---

## RAG 檢索設計

### Hybrid Search（兩層 RRF）

```
                ┌─ query ─────────────────────────────────────┐
                │                                             │ （CRAG rewrite 或 form continuation）
                ▼                                             ▼
   intra-query RRF                                retrieval_query
     ├─ Vector  → ChromaDB top-20                  同樣執行 intra-query RRF → top-8
     └─ BM25    → rank-bm25 top-20
           ↓
     RRF 融合 → top-8
                │                                             │
                └────────── inter-query RRF ──────────────────┘
                                  ↓
                            merged top-8 chunks
                  （兩組都出現的 chunk 自動加分）
```

### 元件

- **向量搜尋**：`text-embedding-3-small` + ChromaDB PersistentClient（版本化路徑：`chroma_versions/v1/` 等）；同步 API 用 `asyncio.to_thread` 包裝避免阻塞
- **BM25**：rank-bm25 + jieba（含 4,948 個營造業自訂詞典，從 chunks tags 自動產出）；首次 query 時 lazy 建索引、之後 singleton 快取
- **RRF**：`score(d) = Σ 1/(k+rank(d))`，k=60，兩路各 top-20 → 去重融合 → 最終 top-8

---

## 記憶系統設計

### 雙層記憶

| 層 | 機制 | 持久化 |
|---|---|---|
| **短期**（對話狀態） | `add_messages` reducer + LangGraph state | `langgraph.db`（AsyncSqliteSaver） |
| **長期**（前情摘要） | 業務邏輯 `upsert_summary` | `app.db / conversation_summaries` |

### Token-Based Compaction

**觸發**：`COMPACT_THRESHOLD = 8000` tokens。

1. `compact_check`：tiktoken（cl100k_base）計算全部 messages
2. 超閾值 → `summarizer`
3. 保留最近 **8 則**訊息（≈4 輪），其餘為「舊訊息」
4. LLM 生成 ≤300 字繁體中文前情提要
5. `RemoveMessage` 批量刪舊訊息
6. `upsert_summary` 非同步寫 SQLite（失敗不阻斷主流程）

### 摘要注入

每輪對話開始前從 SQLite 讀 summary，注入 system prompt：

```
[前情摘要]
{summary}
```

### 各 node 對歷史的使用

| Node | 讀歷史方式 | 為什麼 |
|---|---|---|
| `unified_intent` | 最近 3 輪（用於 LLM 判斷與 _resolve_candidates fallback） | 要做意圖延續判斷 |
| `retriever` | 不讀 | 向量搜尋只看單一 query |
| `responder`（qa） | 完整 messages | 對話延續性 |
| `responder`（fill） | 主要看 `form_fill_session` 摘要 | 任務型，看欄位狀態 |
| `form_fill_collector` | 不讀 | 只抽取本輪訊息的意圖，避免抓到舊值 |

---

## 資料庫設計

### 業務資料庫（app.db）

**users**
```
id (UUID PK), email (UNIQUE INDEX), password_hash (bcrypt rounds=12),
display_name, is_active, created_at, updated_at
```

**conversations**（CASCADE DELETE 訊息與摘要）
```
id (UUID PK), user_id (FK INDEX), title, is_archived, created_at, updated_at
```

**messages**
```
id, conversation_id (FK), role ('user'|'assistant'|'system'),
content, metadata (JSON), created_at
INDEX: (conversation_id, created_at)
```

**conversation_summaries**（1:1 對應 conversations）
```
id, conversation_id (FK UNIQUE), summary (≤300 字),
summarized_message_count, updated_at
```

### ORM 設定

- WAL 模式（並發讀寫）
- `PRAGMA foreign_keys=ON`（CASCADE 正確生效）
- Alembic `render_as_batch=True`（SQLite ALTER TABLE 限制）
- `expire_on_commit=False`（避免 async lazy loading 問題）

### 狀態機資料庫（langgraph.db）

由 `AsyncSqliteSaver` 管理，與 `app.db` 完全分離。

### 對話刪除的副作用清理

`delete_conversation` 在 SQL CASCADE 後 best-effort 清理：

1. `delete_generated_for_conversation()` — 刪 `data/generated_forms/<conv_id>_*.docx`
2. `checkpointer.adelete_thread(conv_id)` — 清 langgraph.db 該對話的 graph state
3. 任一步失敗只記 log，不回滾 SQL（對話已刪）

---

## 傳輸層設計

### API 端點

```
POST /api/auth/register / login / refresh / logout

GET  /api/conversations
POST /api/conversations
GET  /api/conversations/{id}
DEL  /api/conversations/{id}             # 連動清理 generated_forms 與 langgraph.db

POST /api/chat/stream                    # SSE

GET  /api/forms                          # 列出所有靜態表 metadata（FormPickerButton 用）
GET  /api/forms/{form_id}/download       # 下載空白模板
GET  /api/forms/filled/{token}           # 下載 agent 填好的 .docx（驗證 conv_id 屬於使用者）

GET  /api/images/{path}                  # 知識庫圖片
```

### SSE 事件

```jsonc
{"type": "text",         "content": "..."}      // 逐 token 文字
{"type": "form_loading"}                         // 動態表單生成開始
{"type": "sources",      "data": [...]}          // 參考來源（一次性）
{"type": "form",         "data": {...}}          // 動態表單 JSON（一次性）
{"type": "form_files",   "data": [{form_id, display_name, download_url}]}
                                                 // 靜態表單下載卡（含已填寫版本）
{"type": "error",        "content": "..."}
{"type": "done"}
```

> **填表中**（`status=collecting`）會**抑制** `form_files` 事件，避免使用者誤點下載到還沒填的空白模板。完成填寫後（`status=completed`）發出 `form_files`，display_name 自動加上「（已填寫）」前綴。

---

## 安全性設計

### JWT 雙 Token

- **Access Token**（HS256，120 分鐘）→ 前端 memory（非 localStorage）
- **Refresh Token**（HS256，7 天）→ HttpOnly Cookie（secure / samesite=strict / path=/api/auth）
- 每次 `/auth/refresh` 同時輪換 Refresh Token

### 密碼

bcrypt rounds=12，`bcrypt.checkpw()` 時間安全比對。

### API 保護

- 所有對話端點需 Bearer Token，`Depends(get_current_user)` 統一注入
- 查詢時強制帶 user_id 過濾，防越權
- **填寫檔下載**：`/api/forms/filled/{token}` 從 token 解析出 conv_id，驗證對話屬於當前使用者；不通過回 404（不洩露存在性）

---

## 前端設計

### 主要頁面

```
app/
├── (auth)/login/                       # 登入
└── (app)/
    ├── layout.tsx                      # Sidebar + 主內容
    ├── new/                            # 歡迎頁 + 首次輸入
    └── chat/[conversationId]/          # 對話頁
```

### 狀態管理

```typescript
useChatStore {
  conversations: ConversationOut[]      // sidebar 列表
  currentMessages: MessageOut[]         // 當前對話
  pendingMessage: string | null         // /new → /chat/[id] 跨頁傳遞
}
```

### InputBar + FormPickerButton

```
┌────────────────────────────────────────┐
│ [📁]  輸入問題...                [⬆️]  │
└──┬─────────────────────────────────────┘
   ↑
   點擊 → 上拉 popover：
   ┌─────────────────────────────────┐
   │ 選擇表單                         │
   │ ┌───────────────────────────┐   │
   │ │ 動員開工作業檢核表         │   │
   │ │ [⬇下載空白檔] [✨AI 代填]  │   │
   │ └───────────────────────────┘   │
   │ ... (其他兩份)                   │
   └─────────────────────────────────┘

   點 AI 代填 → 內嵌確認檢視（不彈系統 confirm）
   點「開始填寫」→ onSendMessage(`我要填《X》`) → fast-path 2 觸發
```

特色：
- 點擊外面 / Esc 關閉
- 第一次開啟才 fetch `/api/forms`，之後快取
- popover 視覺沿用既有 design system（rounded-xl / border-zinc-200 / shadow-lg）

### 訊息氣泡（MessageBubble）

```
AI 訊息排列：
1. FormLoadingCard       ← form_loading 事件後（動態表單生成中骨架）
2. FormPreview + Export   ← form 事件後（動態表單預覽 + Excel 匯出）
3. 回覆文字（串流 cursor）
4. SourcesPanel           ← 串流結束後
5. FormFileCard 列         ← form_files 事件（靜態表下載 / 已填寫下載）
```

### CSS 細節

- Tailwind v4 preflight 移除了 button 預設 `cursor: pointer`，全域加回：
  ```css
  button:not(:disabled):not([aria-disabled="true"]),
  [role="button"]:not([aria-disabled="true"]) {
    cursor: pointer !important;
  }
  ```
- RWD：電腦版固定 sidebar、聊天區 max-w-3xl 置中；手機版 overlay sidebar + 漢堡按鈕

---

## 可觀測性與維運

### LangSmith Tracing

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=LangGraph-RAG
```

可觀察：每節點時間 / token、unified_intent fast-path 命中、CRAG 重試與 query 改寫、form_structurer Function Calling 輸出、form_fill_collector 抽取結果。

### Orphan 清理腳本

[`backend/scripts/cleanup_orphan_forms.py`](backend/scripts/cleanup_orphan_forms.py)：對照 app.db 的 conversations，清掉：
- generated_forms 內 prefix 對不到任何 conversation 的 .docx
- langgraph.db 內 thread_id 對不到 conversation 的 checkpoints/writes

```bash
# 預設 dry-run 列出 orphan
python scripts/cleanup_orphan_forms.py

# 確認後實際刪除
python scripts/cleanup_orphan_forms.py --apply
```

> 一般情況下不需要跑此腳本：`delete_conversation` 已自動清理。此腳本用於：(a) 升級前留下的 orphan，(b) 直接 SQL 刪 conversation 沒走 service 層的場景。

### 表單 schema 重建

新增表時：

1. 把 .docx 放進 `data_markdown/form_data/`
2. 在 `app/rag/form_registry.json` 加一筆（form_id / display_name / file_name / keywords）
3. 跑 `python scripts/build_form_schemas.py` 自動產 schema JSON
4. 必要時手動校對（複雜表單 generator parser 可能漏 fields）
5. 重啟後端

前端 `FormPickerButton` 自動列出新表，無需改前端。

---

## 專案結構

```
backend/app/
├── api/
│   ├── auth.py                # 註冊 / 登入 / refresh / logout
│   ├── chat.py                # SSE 串流
│   ├── conversations.py       # CRUD（DEL 連動清理）
│   └── export.py              # Excel 匯出
├── core/
│   ├── security.py            # JWT 簽發/驗證、bcrypt
│   └── dependencies.py        # get_current_user
├── graph/
│   ├── builder.py             # StateGraph 組裝、條件邊
│   ├── state.py               # GraphState TypedDict
│   └── nodes/
│       ├── compact.py         # compact_check, summarizer
│       ├── unified_intent.py  # 5 fast-paths + LLM 意圖分類
│       ├── retrieval.py       # Hybrid RAG retriever
│       ├── context.py         # context_builder
│       ├── grader.py          # CRAG retrieval_grader / query_rewriter
│       ├── form.py            # 動態表單 form_structurer
│       ├── form_fill.py       # 靜態表填寫三節點 + 純函式 helpers
│       ├── source_filter.py   # 並行來源評估
│       └── generation.py      # responder（5 種 system prompt 切換）
├── models/                    # User / Conversation / Message / Summary
├── rag/
│   ├── vector_store.py        # ChromaDB（async 包裝）
│   ├── retriever.py           # Hybrid + intra/inter-query RRF
│   ├── form_registry.json     # 靜態表 registry
│   ├── form_lookup.py         # 候選召回 + list_all_forms / get_form_meta
│   ├── form_schemas/
│   │   ├── 010101.json
│   │   ├── 010102.json
│   │   └── 010315.json
│   └── jieba_dict.txt         # 4,948 個營造業自訂詞典
├── services/
│   ├── conversation_service.py  # CRUD + summary + cleanup hooks
│   └── form_fill_writer.py    # write_filled_docx / load_schema /
│                              # delete_generated_for_conversation
├── config.py
├── database.py
└── main.py                    # 含 /api/forms* 端點 + token 所屬權驗證

backend/scripts/
├── 01_preprocess.py … 07      # 知識庫向量索引 pipeline
├── build_form_schemas.py      # 離線產生表單欄位 schema
└── cleanup_orphan_forms.py    # orphan 清理（dry-run / --apply）

frontend/
├── app/(app)/
│   ├── layout.tsx
│   ├── new/page.tsx
│   └── chat/[conversationId]/page.tsx
├── components/
│   ├── chat/
│   │   ├── InputBar.tsx
│   │   ├── FormPickerButton.tsx       # 上拉選單 + 內嵌確認
│   │   ├── FormFileCard.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── MessageList.tsx
│   │   └── SourcesPanel.tsx
│   ├── form/
│   │   ├── FormPreview.tsx
│   │   └── ExportButton.tsx
│   ├── layout/Sidebar.tsx
│   └── ui/                            # shadcn/base-ui
├── lib/
│   ├── api.ts                         # axios + interceptor refresh
│   ├── sse.ts                         # SSE 解析
│   └── auth.ts
└── store/
    ├── authStore.ts
    └── chatStore.ts
```

---

## 環境設定與啟動

### 環境變數（`.env`）

```env
# OpenAI
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-5.4
GRADER_MODEL=gpt-5.4              # unified_intent / retrieval_grader / query_rewriter / form_fill_collector / source_filter
FORM_MODEL=gpt-5.4                # form_structurer
EMBEDDING_MODEL=text-embedding-3-small

# Database
DATABASE_URL=sqlite+aiosqlite:///./app.db
SYNC_DATABASE_URL=sqlite:///./app.db
LANGGRAPH_DB_PATH=./langgraph.db

# JWT
SECRET_KEY=your-secret-here
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=7

# ChromaDB
CHROMA_PERSIST_PATH=./chroma_db
CHROMA_VERSIONS_PATH=./chroma_versions
CHROMA_ACTIVE_VERSION=v1          # 留空 = 用 CHROMA_PERSIST_PATH

# App
APP_ENV=development
CORS_ORIGINS=http://localhost:3000

# LangSmith（可選）
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=LangGraph-RAG
```

### 模型分工

| 設定 | 用途 |
|---|---|
| `LLM_MODEL` | 回覆生成、對話摘要、responder 完整 RAG 回應 |
| `GRADER_MODEL` | unified_intent、CRAG grader/rewriter、form_fill_collector、source_filter |
| `FORM_MODEL` | form_structurer（動態表單） |

### 啟動

```bash
# 後端
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```

### 知識庫建置

```bash
cd backend
# 1. Markdown → 預處理
uv run python scripts/01_preprocess.py
# 2. chunking
uv run python scripts/02_chunk.py
# 3-4. 產生 / 校對 metadata
uv run python scripts/03_generate_meta.py
# 5. 向量化並寫入 ChromaDB
uv run python scripts/05_embed_ingest.py
# 6. 驗證
uv run python scripts/06_verify.py
```

### 表單 schema 建置

```bash
cd backend
uv run python scripts/build_form_schemas.py
```

產出：
- `app/rag/form_schemas/{form_id}.json`（每張表的欄位 schema）
- `scripts/output/form_schemas_summary.txt`（人類可讀清單）
