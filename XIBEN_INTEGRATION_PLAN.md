# 鋼筋盤價助理 — 大陸方面（西本新幹線指數）整合計畫書

> 撰寫日期：2026-05-22
> 對應 slot：`china_xiben_paragraph`（會議記錄 §六.3「大陸方面」）
> 目標：以真實爬蟲取代現有 LLM 自由生成，輸出與 [1150504會議記錄_整理版.md](./1150504會議記錄_整理版.md) 第 99 行範例段落字面一致。

---

## 1. 背景與目標

### 1.1 現況

- `china_xiben_paragraph` slot 已存在於 [slot_schema.py:238-243](./backend/app/modules/search/core/slot_schema.py#L238-L243)。
- 目前由 [weekly_market.py](./backend/app/modules/search/sources/weekly_market.py) 用 OpenAI `web_search` + `chat()` 自由生成，`confidence="medium"` 需人工複核。
- Word 模板已有 `{{china_xiben_paragraph}}` placeholder，渲染管線（[docx_renderer.py](./backend/app/modules/search/output/docx_renderer.py) → [orchestrator.py:_node_render](./backend/app/modules/search/core/orchestrator.py#L287)）會把整段純文字塞入。

### 1.2 範例目標段落（必須一字不差比照句型）

> 西本新幹線本週鋼材指數下跌 10 元至 **3,500 元人民幣/噸**(約 NT$15,894 元)，鐵礦砂本週持平指數為 **980 元人民幣/噸**(約 NT$4,450 元)，焦炭本週持平指數為 **1,330 元人民幣/噸**(約 NT$6,040 元)，廢鋼下跌 10 元至 **2,040 元人民幣/噸**(約 NT$9,264 元)，鋼胚上漲 20 元至 **3,040 元人民幣/噸**(約 NT$13,805 元)。

### 1.3 目標

- 接 5 個 steelx2.com 指定網址作為唯一資料來源。
- 使用 LLM + `web_search`，**與豐興鋼筋同樣的處理哲學**（獨立 adapter、LLM-in-the-loop、可單獨測試、trace 寫進 raw_text）。
- 數字、日期、漲跌方向必須由真實網站決定；NT$ 換算由 Python 算好再給 LLM 拼句。
- 不改 Word 模板、不新增 slot、不動 frontend UI。

---

## 2. 資料來源（已驗證）

| 編號 | 指數名稱 | URL | 模板對應字眼 |
|---|---|---|---|
| 65 | 鋼材指數 | https://www.steelx2.com/indices/65/index.html | 鋼材指數 |
| 61 | 鐵礦石指數 | https://www.steelx2.com/indices/61/index.html | 鐵礦砂 |
| 64 | 焦炭指數 | https://www.steelx2.com/indices/64/index.html | 焦炭 |
| 78 | 廢鋼指數 | https://www.steelx2.com/indices/78/index.html | 廢鋼 |
| 79 | 鋼胚（鋼坯）指數 | https://www.steelx2.com/indices/79/index.html | 鋼胚 |

- 全部為**公開頁面**（無需登入），每頁含日線資料表，欄位：日期 / 值 / 漲跌額 / 漲跌幅。
- 表格單位：鋼材／鐵礦／焦炭 為「點」；廢鋼／鋼胚為「元/噸」。**模板統一寫作「元人民幣/噸」**，不還原各自原始單位。
- 使用者原訊息將 78 列了兩次，第 5 個應為 **79**，已在 steelx2 首頁連結列驗證。

---

## 3. 關鍵設計決策（已拍板）

| # | 決策 | 理由 |
|---|---|---|
| D1 | **時間錨點鎖週一**，與豐興一致 | 避免會議記錄裡「豐興用週一、西本用週五」錯位。`this_monday = opening_monday(target_date)`、`last_monday = this_monday - 7 days` |
| D2 | 週一為國定假日／無資料 → **往前取最近一個有資料的交易日**，不外推、不平均 | 與範例 PDF 處理 5/1 連假改用 4/30 的方式一致 |
| D3 | 採用 **LLM + web_search** 路線，prompt 內**明列 5 個 URL** 作為 site whitelist | 使用者要求「與豐興依樣處理方式」=獨立 adapter + LLM-in-the-loop；web_search 比起寫死的 BeautifulSoup 更耐 HTML 改版 |
| D4 | 數字抽取與段落生成**分兩段**（extract_json → chat） | 算術交給 Python、句型交給 LLM，最大化準確度 |
| D5 | **delta 由 Python 算**（不讓 LLM 算數字差） | LLM 常見錯誤是漲跌幅與絕對值搞混 |
| D6 | NT$ 換算用 **config 設定的 fixed rate**（預設 4.541，可改） | 5 個品項在範例中 ratio 完全一致；動態取匯率屬未來再加，當前不在範圍 |
| D7 | 任一指數抽不到 → **整段走 fallback 句** 「西本新幹線本週尚未有公開報價資料。」 | 與既有 `weekly_market` fallback 哲學一致；不混搭部分真實／部分缺漏 |
| D8 | 與 `weekly_market.py` 其他兩段（國際廢鋼、LME 銅）**完全切割**，只剝離 `china_xiben` 分支 | CLAUDE.md「Surgical Changes」原則，不重構未要求的部份 |

---

## 4. 動工步驟（逐步可驗證）

### 步驟 1 — 設定 FX rate

**改 [app/config.py](./backend/app/config.py)：**
- 在 `Settings` class 加：
  ```python
  cny_to_twd_rate: float = 4.541  # 人民幣 → 新台幣換算比率（西本指數 NT$ 換算用）
  ```

**驗證**：
```bash
python -c "from app.config import settings; print(settings.cny_to_twd_rate)"
# 預期輸出：4.541
```

---

### 步驟 2 — 新增 `xiben.py` adapter

**位置**：`backend/app/modules/search/sources/xiben.py`

**結構**（兩段 LLM 呼叫）：

```python
@register
class XibenAdapter(SourceAdapter):
    name = "xiben"
    provides = ["china_xiben_paragraph"]

    async def fetch(self, target_date: date) -> list[FetchResult]:
        this_monday = opening_monday(target_date)
        last_monday = this_monday - timedelta(days=7)
        try:
            # Phase 1: 抽取 5 個指數的本週/上週數值（結構化）
            snapshot = await self._extract_snapshot(this_monday, last_monday)
            # Phase 2: Python 算 delta + NT$ 換算 → LLM 拼句子
            paragraph = await self._compose_paragraph(snapshot, this_monday, last_monday)
            return [FetchResult(
                slot_key="china_xiben_paragraph",
                value=None, unit="text",
                raw_text=paragraph,
                source_url="https://www.steelx2.com/indices/65/index.html",
                confidence="high",
            )]
        except Exception as e:
            return [self._fallback(reason=str(e))]
```

**Phase 1 — `_extract_snapshot`**：
1. 用 `client.web_search(query)` 跑一個包含 5 個 URL 的 query（內容如下方範例 prompt）。
2. 用 `client.extract_json(schema=XibenSnapshot)` 把搜尋結果轉成結構化 dict。

**Phase 1 query 範本**：
```
我要查西本新幹線（西本指數）5 個指數在以下兩個日期的歷史數值：
- 本週基準日：{this_monday.isoformat()}（民國 {roc_y}/{m}/{d}，週一）
- 上週基準日：{last_monday.isoformat()}（民國 {roc_y}/{m}/{d}，週一）

請從這 5 個指定網址的歷史資料表抓對應日期那一列：
- 鋼材：https://www.steelx2.com/indices/65/index.html
- 鐵礦砂：https://www.steelx2.com/indices/61/index.html
- 焦炭：https://www.steelx2.com/indices/64/index.html
- 廢鋼：https://www.steelx2.com/indices/78/index.html
- 鋼胚：https://www.steelx2.com/indices/79/index.html

【日期取值規則】
1. 優先：取表格中該日期那一列的「值」欄位（不是漲跌額）。
2. 若該日期是國定假日／週末／無交易（表格沒有該列），取**該日期之前最近一個有資料的交易日**的值。
3. 不要外推、不要插值、不要用相鄰日期平均。
```

**Phase 1 schema**：
```python
class XibenItem(BaseModel):
    this_week_value: float | None     # 對應 this_monday（或往前最近交易日）
    this_week_date: str | None        # 實際取到資料的日期（YYYY-MM-DD），trace 用
    last_week_value: float | None
    last_week_date: str | None

class XibenSnapshot(BaseModel):
    steel:    XibenItem  # 鋼材
    iron_ore: XibenItem  # 鐵礦砂
    coke:     XibenItem  # 焦炭
    scrap:    XibenItem  # 廢鋼
    billet:   XibenItem  # 鋼胚
```

**Phase 2 — `_compose_paragraph`**：

預先在 Python 算好：
```python
delta = this_week_value - last_week_value     # 由符號決定動詞
ntd_amount = int(round(this_week_value * settings.cny_to_twd_rate))
```

把算好的數字以 markdown 表格塞進 prompt 給 LLM 拼句：
```
請用以下已備妥的數據寫一段「### 3. 大陸方面」段落（單一純文字、無 markdown、無項目符號、句末加句點）：

| 品項 | 本週值 | 上週值 | 漲跌 | 句型 | NT$ 換算 |
|---|---|---|---|---|---|
| 鋼材指數 | 3,500 | 3,510 | -10 | 下跌 10 元至 | 約 NT$15,894 元 |
| 鐵礦砂   | 980  | 980  | 0   | 本週持平指數為 | 約 NT$4,450 元 |
| ... 共 5 列 ...

【寫作風格範例（必須完全比照）】
{_CHINA_XIBEN_EXAMPLE}

【嚴格規則】
- 五個品項依「鋼材→鐵礦砂→焦炭→廢鋼→鋼胚」順序串成單一段落，逗號分隔，句末句點。
- 句型只能用 whitelist：「下跌 D 元至 N 元人民幣/噸」「上漲 D 元至 N 元人民幣/噸」「本週持平指數為 N 元人民幣/噸」。
- 數字一字不漏照表格；不要自己重算。
- 禁止 0、—、null、X、markdown、超連結。
```

**回傳**：
- 成功：`raw_text=<段落>`、`confidence="high"`、`source_url` 用鋼材 URL（或主站），trace 寫進 `raw_text` 前綴用註解形式 / 或寫進 log。
- 失敗：`_fallback(reason)` 回單一句 fallback + `confidence="low"`。

**驗證**：
```bash
cd backend && python -c "
import asyncio
from datetime import date
from app.modules.search.sources.xiben import XibenAdapter
print(asyncio.run(XibenAdapter().fetch(date(2026, 5, 18))))
"
```
預期：印出 1 個 `FetchResult`，`raw_text` 是 200~300 字的段落，5 個品項都有數字。

---

### 步驟 3 — 將 slot 改路由給新 adapter

**改 [slot_schema.py:241](./backend/app/modules/search/core/slot_schema.py#L241)：**
```python
# before
source="weekly_market",
# after
source="xiben",
```

**改 [weekly_market.py](./backend/app/modules/search/sources/weekly_market.py)：**
1. `provides` list 移除 `"china_xiben_paragraph"`（line 124-130）。
2. 刪除 `_CHINA_XIBEN_EXAMPLE` 常數（line 32-38）— 搬到 `xiben.py` 內部。
3. 刪除 `fetch()` 內 `plan` list 中 `china_xiben_paragraph` 整個 entry（line 206-219）。

**改 [sources/__init__.py](./backend/app/modules/search/sources/__init__.py)：**
- 確認 import 鏈會載入 `xiben.py`（檢查目前是否有類似 `from . import fengxing` 的明確 import；如沒有，且 adapter 是用 `@register` 自註冊，要加 `from . import xiben  # noqa: F401`）。

**驗證**：
```bash
python -c "from app.modules.search.sources.base import get_adapter; print(get_adapter('xiben'))"
# 預期：印出 <class 'XibenAdapter'>，不丟 KeyError
```

---

### 步驟 4 — 端對端驗證

1. 啟動 backend + frontend（或直接走 LangGraph API）。
2. 觸發「產生會議記錄」流程，下載輸出 docx。
3. 用 Word 開啟，肉眼比對「### 3. 大陸方面」段落：

**驗收標準**：
- ✅ 5 個指數都有真實數字（不是 0、—、null）。
- ✅ 漲跌字眼符合 whitelist（持平／上漲／下跌）。
- ✅ NT$ 換算 ≈ 人民幣 × 4.541。
- ✅ 段落是單一純文字、無 markdown、無項目符號。
- ✅ 五個品項順序：鋼材 → 鐵礦砂 → 焦炭 → 廢鋼 → 鋼胚。
- ✅ 句末是句點。
- ✅ `confidence="high"`（在 UI Step 3 看得到綠燈，不是黃／紅）。

**Trace 觀察**：
- 在 LangSmith / log 看到 `_extract_snapshot` 與 `_compose_paragraph` 兩個 LLM 呼叫。
- `FetchResult.raw_text` 應包含 trace 提示，e.g.「本週採 2026-05-18、上週採 2026-05-11」。

---

### 步驟 5 — 清理 orphan

CLAUDE.md「Surgical Changes — Remove orphans」：

- 移除 `weekly_market.py` 因步驟 3 而變死碼的：
  - `_CHINA_XIBEN_EXAMPLE` 常數
  - 註解中所有提到 `china_xiben_paragraph` 的部份
- **不動** `intl_scrap_paragraph` / `lme_copper_paragraph` 相關常數與 plan entry。
- **不動** `market_narrator.py`。
- **不動** 任何 frontend 程式。

---

## 5. 風險與限制

| 風險 | 影響 | 處理 |
|---|---|---|
| steelx2.com HTML 改版 | LLM 抽不到數字 | 走 fallback 句 + `confidence="low"`，使用者 UI 看得到紅旗 |
| LLM 沒辦法準確讀到指定日期那一列 | 數字日期錯位 | Phase 1 schema 強制 LLM 回 `this_week_date` 實際取到的日期；renderer 把它寫進 trace 給人複核 |
| 連假整週都沒資料 | 整段走 fallback | 與既有設計一致；使用者可手動編輯 |
| 5 個 URL 之一 timeout / 4xx | 整段走 fallback | OpenAI web_search 內建 retry；exception 統一走 `_fallback` |
| FX rate 4.541 與實際匯率偏離 | NT$ 數字略偏 | 影響不大；管理員可改 `.env CNY_TO_TWD_RATE` 覆蓋；未來可改成動態 |
| LLM 算錯漲跌（誤把漲幅當絕對值） | 句子錯誤 | delta 已由 Python 算好，prompt 表格給數字＋句型，LLM 只負責拼字串 |

---

## 6. 不會做的事（明確排除）

- ❌ 新增任何 slot / 改 Word 模板 / 改 frontend UI。
- ❌ 重構 `weekly_market.py` 其他段落（intl_scrap、lme_copper）。
- ❌ 加自動匯率刷新 / 歷史快取 / 自訂重試策略。
- ❌ 刪 `_INTL_SCRAP_EXAMPLE` 或 `_LME_COPPER_EXAMPLE`。
- ❌ 動 `market_narrator.py`（§九.1、九.2 仍走原 LLM 路線）。
- ❌ 寫單元測試（沒有要求；既有 sources 也沒有單獨測試檔案）。

---

## 7. 預期觸碰的檔案清單

| 檔案 | 動作 |
|---|---|
| `backend/app/config.py` | 新增一行 `cny_to_twd_rate` |
| `backend/app/modules/search/sources/xiben.py` | **新建** |
| `backend/app/modules/search/sources/__init__.py` | 加 `from . import xiben`（如必要） |
| `backend/app/modules/search/core/slot_schema.py` | 改 1 處：`source="weekly_market"` → `"xiben"` |
| `backend/app/modules/search/sources/weekly_market.py` | 刪：`_CHINA_XIBEN_EXAMPLE`、`provides` 一項、plan 一個 entry |

預估**淨增 ~150 行**（xiben.py 含 docstring、schema、兩個 LLM 呼叫、fallback），其他檔案合計刪/改 ~25 行。

---

## 8. 範例輸出（套用 2026-05-18 那週實測數據；FX rate=4.541）

假設 web_search 拿到：
- 鋼材 5/18=3,510 ／ 5/11=3,520 → 下跌 10
- 鐵礦砂 5/18=990 ／ 5/11=990 → 持平
- 焦炭 5/18=1,380 ／ 5/11=1,380 → 持平
- 廢鋼 5/18=2,080 ／ 5/11=2,080 → 持平
- 鋼胚 5/18=3,060 ／ 5/11=3,090 → 下跌 30

預期生成段落：

> 西本新幹線本週鋼材指數下跌 10 元至 **3,510 元人民幣/噸**(約 NT$15,939 元)，鐵礦砂本週持平指數為 **990 元人民幣/噸**(約 NT$4,496 元)，焦炭本週持平指數為 **1,380 元人民幣/噸**(約 NT$6,267 元)，廢鋼本週持平指數為 **2,080 元人民幣/噸**(約 NT$9,445 元)，鋼胚下跌 30 元至 **3,060 元人民幣/噸**(約 NT$13,895 元)。

---

## 9. 動工前最後確認清單

- [x] D1 時間錨點鎖週一
- [x] D2 假日往前取最近交易日
- [x] D3 LLM + web_search 路線，URL whitelist
- [x] D4 抽取與拼句兩段分離
- [x] D5 delta 由 Python 算
- [x] D6 FX rate 4.541（config）
- [x] D7 任一缺漏整段 fallback
- [x] D8 不動 weekly_market 其他段落

全部勾選後即可動工。
