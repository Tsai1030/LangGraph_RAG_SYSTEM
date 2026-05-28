# 鋼筋助手後端系統設計導覽

> 適合閱讀對象：了解 Python 基礎，想搞清楚這個系統「從哪裡拿資料、怎麼處理、最後輸出什麼」的人。

---

## 一、系統全貌

這個後端是一個 **FastAPI** 應用，裡面包含兩個獨立模組：

```
後端 (FastAPI :8000)
│
├── RAG 模組          → 問答機器人（建築法規、合約問答）
│     ├── ChromaDB      向量資料庫（知識庫）
│     ├── LangGraph     11 個節點的問答工作流程
│     └── app.db        對話記錄（SQLite / PostgreSQL）
│
└── SEARCH 模組       → 鋼筋盤價助理（本文重點）
      ├── 資料來源爬蟲  豐興、廢鋼、LME、人民幣...
      ├── LangGraph     5 個節點的資料管道
      └── search.db     價格歷史記錄（SQLite / PostgreSQL）
```

本文聚焦在 **SEARCH 模組**（鋼筋盤價助理）。

---

## 二、SEARCH 模組：整體資料流

```
① 使用者按「產生」
        │
        ▼
② 建立一筆執行記錄 (GenerationRun)，馬上回傳 run_id
        │
        ▼（背景非同步執行）
③ fetch   → 從各網站/API 抓資料
        │
        ▼
④ validate → 檢查每筆資料是否有值、信心度
        │
        ▼
⑤ persist → 寫入 price_history 資料庫表（原始數值）
        │
        ▼
⑥ narrate → 格式化數值、計算週漲跌幅
        │
        ▼
⑦ render  → 把資料填入 Word 模板，輸出 .docx 檔
        │
        ▼
⑧ 前端輪詢 GET /generation/{id} → 拿到結果 / 下載 Word
```

這五個步驟由 `app/modules/search/core/orchestrator.py` 的 **LangGraph** 串起來。

---

## 三、資料從哪裡來？

### 3.1 資料來源一覽

| 來源 | 檔案 | 抓什麼 | 怎麼抓 |
|------|------|--------|--------|
| 豐興鋼鐵 | `sources/fengxing.py` | SD280、SD420 等週開盤價 | 登入 SteelNet 爬文章，用 LLM 解析數字 |
| 廢鋼國際行情 | `sources/weekly_market.py` | 美國大船廢鋼、日本 2H 廢鋼 | SteelNet 爬蟲 + LLM 生成敍述段落 |
| LME 銅 / 人民幣 | `sources/weekly_market.py` | LME 銅價、人民幣匯率 | LLM 使用 web search 工具查詢 |
| 西本新幹線 | `sources/xiben.py` | 人民幣計價鋼材→新台幣換算 | HTTP 爬蟲直接抓 xiben.com 頁面 |
| 中鋼盤價 | `api/csc.py` + DB | 月度/季度中鋼標準盤價 | 管理員手動輸入維護，存在 DB |

### 3.2 每個來源都實作相同介面

`sources/base.py` 定義了一個抽象基類 `SourceAdapter`：

```python
class SourceAdapter:
    name: str           # 穩定識別碼，例如 "fengxing"
    provides: list[str] # 這個來源會填哪些欄位
    
    async def fetch(self, target_date: date) -> list[FetchResult]:
        # 抓資料，回傳結果清單
        ...
```

所有來源（豐興、廢鋼、西本...）都繼承這個類，讓 orchestrator 可以統一呼叫。

### 3.3 豐興資料抓取細節（最複雜的來源）

```
1. fengxing_finder.py
   └─ 呼叫 SteelNet 網站搜尋「豐興週盤」
   └─ 用 LLM 判斷哪篇文章日期正確（避免抓到舊的）

2. steelnet_client.py
   └─ 用帳密登入 steelnet.com.tw（會員制）
   └─ 下載文章 HTML

3. fengxing.py
   └─ 把文章 HTML 餵給 LLM
   └─ LLM 回傳結構化 JSON：{ "sd280": 18900, "sd420": 19500, ... }
```

帳密在 `config.py` 的 `STEELNET_USER` / `STEELNET_PASSWORD` 環境變數。

---

## 四、插槽（Slot）是什麼？

「插槽」是 Word 模板裡每個 `{{佔位符}}` 的設定檔，定義在 `core/slot_schema.py`。

```python
SlotDef(
    key="fx_sd280_price",       # Word 模板裡的 {{fx_sd280_price}}
    label="豐興 SD280",          # 前端顯示名稱
    type=SlotType.PRICE,         # 數值型（自動加千位分隔符）
    unit="元/噸",
    source="fengxing",           # 由哪個適配器填這個欄位
    auto_fillable=True,          # 可自動填 vs. 需手動輸入
    section="六.1",              # 對應 Word 的章節
)
```

**插槽型態：**

| 型態 | 說明 | 範例 |
|------|------|------|
| `PRICE` | 數值，自動加千位逗號 | `18900` → `"18,900"` |
| `DELTA` | 週漲跌，自動加 +/- | `300` → `"+300"` |
| `TEXT` | LLM 生成的敍述文字 | 市場分析段落 |
| `DATE` | 日期 | `2026-05-19` |
| `INTERNAL` | 員工手動輸入 | 會議時間、備註 |

系統啟動時會掃描所有 `SlotDef`，決定需要呼叫哪些 source adapter。

---

## 五、LangGraph 編排器：5 個節點

```
orchestrator.py

  [fetch]
    ↓ 並行呼叫所有需要的 source adapter
    ↓ 回傳 FetchResult[]

  [validate]
    ↓ 每筆結果有值 → confidence="high"
    ↓ 無值或異常 → confidence="low"，標記警告

  [persist]
    ↓ 把數值寫進 price_history 表
    ↓ (即使後面 render 壞掉，原始數據已存起來)

  [narrate]
    ↓ PRICE 型 → 格式化為 "18,900"
    ↓ DELTA 型 → 與上週資料比對，算出 "+300"
    ↓ TEXT 型  → 直接用 LLM 生成的敍述
    ↓ 把中鋼覆蓋值、員工手動輸入值合併進去
    ↓ 輸出：slot_values = {"fx_sd280_price": "18,900", ...}

  [render]
    ↓ 用 python-docx 打開 meeting_template.docx
    ↓ 把 {{fx_sd280_price}} 替換為 "18,900"
    ↓ confidence="low" 的欄位 → 標紅色
    ↓ 存到 output/ 目錄
    ↓ 更新 GenerationRun.output_path
```

---

## 六、資料庫結構（search.db）

```
price_history          ← 所有歷史價格（每週一筆）
  ├── slot_key         "fx_sd280_price"
  ├── value_date       開放的週一日期（週一鎖定）
  ├── value            18900.0
  ├── confidence       "high" / "low"
  └── source           "fengxing"

csc_price_state        ← 中鋼盤價（管理員手動維護）
  ├── group            "monthly" / "quarterly"
  ├── slot_index       0, 1, 2...（對應不同規格）
  ├── prev_price       上期盤價
  ├── change_amount    本期漲跌
  └── updated_by       誰更新的

generation_runs        ← 每次「產生 Word」的執行記錄
  ├── id               唯一識別碼
  ├── meeting_date     這份文件是哪個日期的會議
  ├── started_by       使用者 ID
  ├── status           "running" / "success" / "partial" / "failed"
  ├── output_path      Word 檔案路徑
  └── result_json      所有 slot_values 的 JSON 快照
```

---

## 七、API 端點流程

### 產生 Word 文件

```
POST /api/search/generation/run
  body: { meeting_date: "2026-05-19" }

  → 建立 GenerationRun（status="running"）
  → 馬上回傳 { run_id: "abc123" }     ← ~100ms，不等結果
  → 背景 asyncio 任務跑 LangGraph
```

```
GET /api/search/generation/{run_id}     ← 前端每 2.5 秒輪詢

  → status="running"  → 繼續等
  → status="success"  → 回傳 slot_values + confidence
  → status="failed"   → 回傳錯誤訊息
```

```
GET /api/search/generation/{run_id}/docx  ← 下載 Word 檔

  → 驗證是本人或管理員
  → 回傳 .docx 二進位
```

### 填入員工手動資料

```
POST /api/search/generation/{run_id}/internal-data
  body: { meeting_time: "09:00", notes: "..." }

  → 把手動資料存進 GenerationRun
  → 重設 status="running"
  → 重跑 narrate + render（不重抓資料，用快取的 FetchResult）
  → 輸出更新後的 Word
```

### 中鋼盤價管理（管理員）

```
GET  /api/search/csc/state           → 讀取目前中鋼盤價
POST /api/search/csc/state           → 更新中鋼盤價
GET  /api/search/csc/announcements   → 公告標頭列表
```

---

## 八、關鍵設定（config.py）

| 環境變數 | 作用 |
|---------|------|
| `OPENAI_API_KEY` | OpenAI API 金鑰（LLM 解析、生成敍述用） |
| `LLM_MODEL` | 主模型（預設 `gpt-5.4`） |
| `STEELNET_USER` / `STEELNET_PASSWORD` | 豐興資料來源的登入帳密 |
| `SEARCH_DATABASE_URL` | search.db 連線字串（支援 SQLite / PostgreSQL） |
| `CNY_TO_TWD_RATE` | 人民幣→新台幣匯率（西本資料換算用） |
| `SEARCH_ENABLED` | 是否啟用 SEARCH 模組 |

---

## 九、啟動方式

```
run_server.py
  └─ Windows 專用：強制 SelectorEventLoop（解決 asyncio 相容問題）
  └─ 啟動 uvicorn → FastAPI app (0.0.0.0:8000)

app/main.py (lifespan)
  └─ 初始化資料庫表格
  └─ 清理異常中斷的 running 狀態
  └─ 初始管理員帳號
  └─ 掛載所有路由
```

PM2 以 `uv run python run_server.py` 啟動後端，Caddy 反向代理到 `:9000`。

---

## 十、模組間關係圖

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI (:8000)                      │
│                                                         │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │     RAG 模組         │  │      SEARCH 模組          │  │
│  │                     │  │                          │  │
│  │  LangGraph (11節點)  │  │  LangGraph (5節點)        │  │
│  │  ├─ 意圖判斷         │  │  ├─ fetch (爬蟲)          │  │
│  │  ├─ 向量檢索         │  │  ├─ validate             │  │
│  │  ├─ BM25 檢索        │  │  ├─ persist              │  │
│  │  └─ 串流回答         │  │  ├─ narrate              │  │
│  │                     │  │  └─ render (Word)        │  │
│  │  ChromaDB           │  │                          │  │
│  │  (知識庫向量)        │  │  price_history DB        │  │
│  │  app.db             │  │  search.db               │  │
│  │  (對話記錄)          │  │  (價格歷史)              │  │
│  └─────────────────────┘  └──────────────────────────┘  │
│                                                         │
│           共用：認證 (JWT) / 使用者 (app.db)             │
└─────────────────────────────────────────────────────────┘
```

---

## 十一、如果你要追一個 Bug

**「為什麼豐興價格抓錯了？」**
→ 看 `sources/fengxing.py` 的 `fetch()`，加 print 看 LLM 解析的 JSON

**「為什麼週漲跌算錯？」**
→ 看 `core/orchestrator.py` 的 `narrate` 節點，再看 `storage/history_repo.py` 的 `get_previous_week_value()`

**「為什麼 Word 某個欄位是紅色？」**
→ 看 `output/docx_renderer.py`，紅色 = `confidence != "high"`
→ 往回追 validate 節點為什麼給 low confidence

**「為什麼一直顯示 running 不完成？」**
→ 看 `generation_runs` 資料表的 `status` 欄位，再看 `api/generation.py` 的背景任務有無 exception

---

*最後更新：2026-05-22*
