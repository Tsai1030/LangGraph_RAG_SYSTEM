# 豐興盤價抓取改用 Gemini + Google Search — 計畫書

> 版本：v0.1（討論稿，**尚未動工**） | 日期：2026-06-01
> 範圍：只動「鋼筋盤價助理」（`backend/app/modules/search/`），**完全不碰主 RAG 系統**
> 起因：豐興原本走 `steelnet.com.tw` 會員爬蟲，訂閱已失效；同時你把 `.env` 的 `LLM_MODEL` 改成 Gemini，連帶讓 search 模組的 OpenAI 呼叫也壞了

---

## 0. 現況診斷（我實際讀過程式碼後的結論）

### 0.1 「鋼筋盤價助理」和「主 RAG」是兩套獨立的 LLM 系統

| | 主 RAG 系統 | 鋼筋盤價助理（SEARCH 模組） |
|---|---|---|
| LLM 入口 | `app/core/llm.py` 的 `get_llm(role)` | `app/modules/search/llm/openai_client.py` 的 `OpenAIClient` |
| 底層 | LangChain `init_chat_model`（吃 `provider:model` 前綴） | 直接用 OpenAI SDK |
| 讀哪個設定 | `LLM_MODEL` / `GRADER_MODEL` / `FORM_MODEL` | **也是讀 `LLM_MODEL`** + `OPENAI_API_KEY` |
| 本次是否更動 | **絕對不動** | ✅ 要改的就是這套 |

> 你說「不清楚鋼筋助理是以哪邊為主」——答案是：它有**自己的 `OpenAIClient`**，但它讀的 model 字串跟 RAG 共用同一個 `LLM_MODEL`。

### 0.2 兩個目前壞掉的點

**(A) 豐興 steelnet 爬蟲失效**
`sources/fengxing.py → fengxing_finder.py（LangGraph agent）→ steelnet_client.py`，後者要登入 `steelnet.com.tw`（`STEELNET_USER/PASSWORD`）。訂閱失效後抓不到文章，豐興盤價會落到 fallback（紅色「—」）。

**(B) OpenAIClient 拿到一個它不認得的 model 字串**
`OpenAIClient` 內部 `self._model = settings.llm_model`，而你 `.env` 現在是：
```
LLM_MODEL=google_genai:gemini-3.5-flash
```
這個字串被原封不動丟給 OpenAI 的 API → **凡是 search 模組用到 LLM 的地方現在全都會報錯**（不只豐興）：
- `xiben.py`（§六.3 大陸西本指數）
- `market_narrator.py`（§九 國內/大陸市場資訊）
- `weekly_market.py`（§六.2 國際廢鋼、§六.4 LME 銅）
- `fengxing_finder.py`（多候選文章時的 LLM 裁決）

> 換句話說：現在整個鋼筋盤價助理其實是半癱的。本次改造會**同時修好 (A) 和 (B)**。

### 0.3 完整資料流（這條鏈的「輸出契約」必須維持不變）

```
API /search/generation/run
   └─ orchestrator (LangGraph): fetch → validate → persist → narrate → render
        fetch:   呼叫各 SourceAdapter
                   ├ fengxing        → fx_sd280/sd280w/sd420/sd420w/scrap/section（數字）
                   ├ weekly_market   → 國際廢鋼段落(文字) + 日本2H/美國貨櫃(數字)
                   ├ xiben           → 西本段落(文字)
                   └ market_narrator → 國內/大陸資訊(文字)
        persist: 數字寫進 price_history（以「開盤週一」為 key）→ 餵 §七 歷史表
        narrate: 把每個 slot 算成字串（價格用千分位、文字直接放、漲跌自動算）
        render:  把 {{slot_key}} 填進 Word 範本 → .docx
```

**關鍵理解**：豐興目前輸出的不是一段文字，而是**結構化數字**。這些數字會：
1. 填 §六.1 豐興盤價表的格子
2. 寫進 `price_history` → 餵 §七 七週歷史表
3. 做級距衍生：`SD280W = SD280+200`、`SD420 = SD280+1000`、`SD420W = SD420`

所以「換掉爬蟲」**不能**簡單換成一段純文字塞進 Word，否則 §六.1 表格、§七 歷史、級距衍生全會壞。

### 0.4 你提供的新爬蟲（`feng_hsin_price_fetcher.py`）

- 用 `google-genai` SDK（`.venv` 已裝 v1.75.0 ✓）+ `types.GoogleSearch()` grounding
- 模型 `gemini-3.5-flash`
- 產出是一段**自由格式報告**（牌價 / 基價 / 國際原物料），不是結構化數字
- ⚠️ 它讀 `os.getenv("GEMINI_API_KEY")`，但你 `.env` **只有 `GOOGLE_API_KEY`**（沒有 `GEMINI_API_KEY`）→ 直接搬進來會拿到 None。新版要改讀 `settings.google_api_key`。

---

## 1. 設計總則

### 1.1 核心策略：換「資料來源層」，不換「輸出契約」

把豐興的取數邏輯從「steelnet 爬文章 + regex」換成「Gemini + Google Search」，但讓它**回傳同樣的結構化結果**（SD280、廢鋼、型鋼、開盤日、國際廢鋼段落）。下游（級距衍生、slot 填值、歷史、Word 渲染）**完全不用改**。

新豐興抓取走**兩段式**（這就是你說的「LLM 潤飾」要做的事）：

```
Step 1  Gemini + GoogleSearch（grounding 搜尋）
          → 拿到原始報告文字 + 實際搜尋關鍵字 + 來源清單（供 trace 稽核）
Step 2  Gemini extract_json（無工具、結構化輸出）
          → 把報告解析成 {sd280, 廢鋼, 型鋼, 開盤日, 國際廢鋼數字+段落}
          → 查不到的欄位填 null，絕不編造
```

數字「鎖定」後，文字段落再用 Gemini 做**潤飾**（只調用語、比照舊版範例句型，數字當事實餵進去不准改）——這跟現有 `xiben.py` 的「事實表 → LLM 只組句」是同一個套路，風格一致。

### 1.2 LLM provider 切換：新增 `GeminiClient`，沿用現有 `LLMClient` 介面

`llm/base.py` 已經定義好抽象介面（`chat` / `web_search` / `extract_json`），當初就是為了換 provider。我們只要：
- 新增 `llm/gemini_client.py`（實作這三個方法，底層用 `google-genai` 的 GoogleSearch grounding）
- 新增 `get_search_llm()` 工廠（看 `LLM_MODEL` 前綴決定回 Gemini 還是 OpenAI；預設 Gemini）
- 把 4 個來源的 `OpenAIClient()` 換成 `get_search_llm()`

> 這跟主 RAG 的 `get_llm()` 是同一個設計哲學，只是 search 模組這套要自己做（因為它需要 GoogleSearch grounding，LangChain 介面拿不到那個 grounding metadata）。`OpenAIClient` 保留不刪，之後改 `.env` 前綴就能切回去。

### 1.3 豐興「尚未公布」處理：沿用上週 + 標註

豐興週一開盤、**通常傍晚才公布**。本週還沒出（或查不到）時：
- **不**顯示紅「—」，改從 `price_history` 撈「最近一個有真實資料的較早週」的 SD280/廢鋼/型鋼來顯示（級距衍生照算）。若連上週都查無，才退回紅「—」。
- 這些「沿用上週」的值標記 `is_stale=True` + 低信心 → Word 既有機制會自動顯示成**紅字**（視覺警示）；同時在前端顯示提示句：「本週尚未公布（通常傍晚），以下沿用上週 (M/D) 報價，請稍後重新產生」。
- **關鍵守則（雷）**：沿用上週的值**絕不寫進** `price_history` 的本週 key，否則 §七 歷史表會多一筆假資料、週對比變成 0。→ persist 階段必須跳過 `is_stale` 列（只顯示、不存檔）。
- 這需要對 orchestrator 的 `_node_persist` / `_node_validate` 做**極小**改動，但**不動** slot_schema、Word 範本、docx renderer。

---

## 2. 決策（D1/D2 已於 2026-06-01 確認）

| # | 決策 | 結論 |
|---|---|---|
| D1 | LLM 切換範圍 | ✅ **整個 search 模組都改 Gemini**（豐興+西本+§九+§六.4 全用 gemini-3.5-flash；`OpenAIClient` 保留可切回） |
| D2 | 豐興輸出形式 | ✅ **維持結構化數字 + 潤飾文字**（§六.1 表/§七 歷史/級距衍生完全不變；Gemini 負責抓數+潤飾國際段落） |
| D3 | 廢鋼數字對應 | ⏳ 待動工後比對你**舊版 Word**，確認 `fx_scrap_base_price` 取「廢鋼牌價(收購價)」還是「廢鋼基價」（見 §5 風險） |
| D4 | Git 工作方式 | ⏳ 待定：(a) 現有 `feat/postgres-migration` 分支　(b) 開新分支　(c) worktree。後端 Python 在你手動重啟前不會生效，風險比前端低 |
| D5 | 「尚未公布」標註位置 | ⏳ 預設：數字以**紅字**顯示在 Word（既有低信心機制）+ 文字提示走前端 `notes`，**不動範本**。若要把提示句**直接印進 Word 內文**，需另加一個範本 slot（另議） |

---

## 3. 分階段執行（每階段都可獨立測試，你重啟後驗證 OK 再進下一階段）

> 原則：每階段結束系統都處於「可運作或更好」的狀態；每階段一個 commit，出事就 revert 該 commit + 重啟。

### Stage 0 — 開工前準備（無程式碼變更）
- [ ] 確認 backend 啟動指令**沒有 `--reload`**（這樣 in-place 編輯在你手動重啟前不會生效，不會干擾線上）
- [ ] 確認金鑰策略：用既有 `GOOGLE_API_KEY`（已存在），不需要新增 `GEMINI_API_KEY`
- [ ] 確認 `google-genai` 已裝（✓ v1.75.0）
- [ ] 處理 `git status` 未 commit 的 `backend/chroma_versions/v5/chroma.sqlite3`（commit 或 stash），並決定 D4
- **驗證**：`uv run python -c "from google import genai; print('ok')"`；印出 `settings.llm_model` 確認 = `google_genai:gemini-3.5-flash`

### Stage 1 — 新增 `GeminiClient`（先不接線，零風險）
- [ ] 新檔 `llm/gemini_client.py`：實作 `chat` / `web_search`（GoogleSearch grounding）/ `extract_json`
  - 用 `client.aio.models.generate_content`（真 async，對齊現有 AsyncOpenAI）
  - model 去掉 `google_genai:` 前綴 → `gemini-3.5-flash`
  - api_key 用 `settings.google_api_key`
  - `web_search` 的 citations 從 `grounding_metadata.grounding_chunks[].web`（title/uri）取
- [ ] `llm/__init__.py` 新增 `get_search_llm()` 工廠
- **驗證**：寫一支獨立 smoke 腳本（不經 FastAPI）：`chat` 回一句、`web_search` 回 text+citations、`extract_json` 回 pydantic 物件。**此階段不改任何現有呼叫，線上行為不變。**

### Stage 2 — 三個敘述來源切到 Gemini（修好目前壞掉的 LLM 呼叫）
- [ ] `xiben.py` / `market_narrator.py` / `weekly_market.py` 把 `OpenAIClient()` → `get_search_llm()`
- [ ] 邏輯、prompt、風格範例**全部不動**，只換底層 client
- **驗證**：跑一次 `/run`，§六.3（西本）、§九（國內/大陸）、§六.4（LME 銅）能產生文字而不是 error/fallback

### Stage 3 — 新豐興抓取（Gemini + GoogleSearch → 結構化）
- [ ] 新檔 `sources/fengxing_gemini.py`，提供 `find_article(target_date)`，**簽名與回傳型別跟舊的一致** `(FengxingArticleData|None, picked_meta, trace)`
  - 兩段式（§1.1）：grounding 搜尋 → extract_json 結構化
  - trace 帶上「實際搜尋關鍵字 + 來源 + 抽到的數字」，沿用 §step-3 UI 稽核
- [ ] `sources/fengxing.py` 把 `from .fengxing_finder import find_article` 換成新模組
- [ ] 保留級距衍生、`15,000–25,000` 合理區間驗證、fallback
- **驗證**：挑一個你**有舊 Word 可比對**的週次跑，核對 SD280 / 廢鋼 / 型鋼 / 開盤日是否正確

### Stage 4 —「尚未公布 → 沿用上週 + 標註」fallback
> 豐興週一開盤、通常傍晚才公布。本週查不到時不顯示紅「—」，改沿用上週實際報價並標註（見 §1.3）。
- [ ] 新豐興抓取偵測「本週查無」→ 從 `price_history` 撈最近一個有真實資料的較早週的 SD280/廢鋼/型鋼
- [ ] 這些值標記 `is_stale=True`、confidence=`low`（Word 自動紅字）
- [ ] `sources/base.py` 的 `FetchResult` 加一個 `is_stale: bool = False`（最小、向後相容）
- [ ] `_node_persist` **跳過** `is_stale` 列（**絕不可**把上週數字寫進本週歷史 → §七 假資料、週對比變 0）
- [ ] `_node_validate` 對 `is_stale` 發一則 issue（會進 run 的 `notes`，前端顯示）：「豐興本週尚未公布（通常傍晚），以下沿用上週 M/D 報價，請稍後重新產生」
- [ ] 若連上週也查無 → 維持原本紅「—」+ note「查無豐興報價」
- **驗證**：對一個「本週還沒開盤」的日期跑 → §六.1 顯示上週數字（紅字）+ 前端出現提示；並確認 `price_history` **沒有**被寫入本週假資料

### Stage 5 — 國際廢鋼段落改接新抓取（§六.2 / §七.4 / §七.5）
- [ ] `weekly_market._fetch_intl_scrap_from_steelnet` 改成吃新豐興 Gemini 結果的「國際段落 + 日本2H/美國貨櫃數字」（不再走 steelnet）
- **驗證**：§六.2 段落有值、§七 日本2H / 美國貨櫃歷史欄位有數字

### Stage 6 — 潤飾，讓輸出用語與舊版一致
- [ ] 對國際段落（必要時含豐興摘要句）加一個 Gemini 潤飾步驟：數字鎖定，只比照 `_INTL_SCRAP_EXAMPLE` 等既有範例調整句型/用語
- **驗證**：產出的 Word §六.1 / §六.2 讀起來跟你舊版一致

### Stage 7 — 收尾與退役 steelnet 連線
- [ ] `steelnet_client.py` 的 login / search / fetch（網路部分）標記停用；**保留**仍被引用的純解析 helper（如 `parse_intl_scrap_prices`）
- [ ] 移除我改動造成的孤兒 import（不刪既有無關 dead code）
- **驗證**：端到端跑一次完整 `/run`，逐節檢視整份 Word

---

## 4. 會更動 / 不會更動的檔案

**會新增**
- `backend/app/modules/search/llm/gemini_client.py`
- `backend/app/modules/search/sources/fengxing_gemini.py`

**會修改（小範圍）**
- `llm/__init__.py`（加工廠）
- `sources/xiben.py`、`sources/market_narrator.py`、`sources/weekly_market.py`（換 client）
- `sources/fengxing.py`（換 import 來源）
- `sources/base.py`（`FetchResult` 加 `is_stale` 欄位，向後相容）— Stage 4
- `core/orchestrator.py` 的 `_node_persist` / `_node_validate`（**僅**為 stale fallback，極小範圍）— Stage 4

**絕對不動**
- `app/core/llm.py`、主 RAG 任何檔案
- `core/slot_schema.py`、`output/docx_renderer.py`、Word 範本（輸出契約）
- DB schema、`price_history` 結構（只新增列、不改 schema）

---

## 5. 風險與對策

| 風險 | 說明 | 對策 |
|---|---|---|
| **數字準確度** | Google grounding 可能拿到過期/錯誤數字，不像 steelnet 直接讀原文 regex 那麼精準 | 保留 `15,000–25,000` 合理區間驗證；extract 強制「查不到填 null 不編造」；數字來源（grounding sources）寫進 trace 供人工稽核；豐興數字 confidence 可標 `medium` |
| **廢鋼數字對應（D3）** | 舊 steelnet 用「本週牌價」那行的廢鋼數字當 `fx_scrap_base_price`；新報告把牌價/基價分開了 | 動工前先比對你一份舊 Word，確認該格用的是哪個數字 |
| **GoogleSearch + 結構化不能同時** | Gemini 不能在同一個呼叫裡同時開 grounding 工具又要 JSON schema | 本來就拆兩段（搜尋 / 抽取），天然避開 |
| **LangSmith 觀測性** | OpenAIClient 用 `wrap_openai` 自動記 token；Gemini 沒有等價 wrapper | 仍用 `@traceable` 保留 span；token 欄位可能空白（可接受，之後再補） |
| **開盤日判斷** | 舊 agent 會挑「最接近目標週一」的文章；Gemini 直接查可能拿到鄰近週 | prompt 明確鎖定「包含目標週一那一週」；extract 回報實際開盤日；驗證階段人工核對 |
| **沿用上週污染歷史** | 若把上週數字當本週寫進 `price_history` → §七 假資料、週對比變 0 | persist 跳過 `is_stale` 列；只顯示不存檔（Stage 4） |
| **標註位置** | 不動 Word 範本前提下提示要放哪 | 數字用既有低信心**紅字**呈現；文字提示走 run `notes`（前端已顯示）；要印進 Word 內文則需加範本 slot（D5 另議） |

---

## 6. 執行節奏

D1 / D2 已確認 → 從 **Stage 1** 開始（新增 `GeminiClient`，零風險、不接線）。
每做完一階段就停下來，讓你手動重啟 + 驗證 OK 再進下一階段。
D3 在 Stage 3 比對舊 Word 時定；D4（git 方式）開工前你給個方向即可。
