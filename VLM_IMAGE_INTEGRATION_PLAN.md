# RAG 接入 VLM（圖片輸入）— 計畫書

> 版本：v0.3（Stage 0 已驗證、Stage 1 動工） | 日期：2026-06-01（更新 2026-06-05）
> 範圍：讓使用者「上傳圖片 + 文字」一起提問，且**支援多輪圖片對話**。**主 RAG graph 的既有節點與輸出契約一律不動**；
> 唯一的拓撲變更是在最前面**附加**一個 `vision_intake` 節點（純文字流程會 no-op 跳過）。
> 起因：把現有純文字 RAG 升級成多模態問答；沿用既有 Gemini model，不引入新 model / 新 SDK。

---

## 進度

| Stage | 內容 | 狀態 |
|---|---|---|
| 0 | 開工前驗證（多模態訊息格式、Gemini 收圖 smoke、分支） | ✅ 已驗證（2026-06-05；格式 A、OCR 精準、token 正常） |
| 1 | 後端：`/api/chat/upload` 上傳端點 + 存磁碟 + state/Schema 加欄位（不接線，零風險） | ✅ 已驗證（2026-06-05；commit e154e1e） |
| 2 | 新增 `vision_intake` 節點並接進 graph（Gemini 讀圖 → 解析併入 query） | ✅ 已驗證（2026-06-05；commit 7ab68fc，節點實測 1763 字 OCR + no-op 正確） |
| 3 | responder 用「圖片解析 + 原圖」生成答案（D4） | ✅ 已驗證（2026-06-05；commit c410e76，端到端實測精準讀出工令代號 1CA201/合約金額） |
| 4 | 前端：InputBar 上傳 UI + 把 `image_ids` 串進送出流程 | ⏳ 未開始 |
| 5 | 多輪圖片對話延續（carry-forward，仿 `prev_form_data`，D6） | ⏳ 未開始 |
| 6 | 收尾/體驗：SSE「讀取圖片中」指示、聊天泡泡縮圖、磁碟清理 | ⏳ 未開始 |

---

## 0. 現況診斷（我實際讀過程式碼後的結論）

### 0.1 你的 LLM 入口本來就是 Gemini-ready

| 角色（`get_llm(role)`） | 用在哪些節點 | `.env` 實際 model |
|---|---|---|
| `default` | **responder**、summarizer | **`google_genai:gemini-3.5-flash`** ✅ 原生多模態 |
| `grader` | unified_intent、retrieval_grader、source_filter、form_fill 抽欄位 | `openai:gpt-5.4-mini` |
| `form` | form_structurer | `openai:gpt-5.4` |

- 統一工廠 `app/core/llm.py` 的 `get_llm()` 走 LangChain `init_chat_model`，**provider-agnostic**，切 model 只動 `.env`。
- `app/graph/nodes/generation.py:205` 的 responder 已經是 Gemini 3.5 Flash；該檔 `:210` 的註解甚至已在處理 Gemini 3.x 的 `list[block]` 回傳格式 → 整套早就為 Gemini 準備好了。
- **關鍵推論**：「看圖」這件事可以**完全只發生在 Gemini 節點**（新的 `vision_intake` + responder），完全符合你「影像理解要用 Google 的 model」的要求，**完全不需要把圖片送進那些走 OpenAI 的 intent/grader 節點**。

### 0.2 目前的輸入流（這條鏈要維持不變）

```
前端 InputBar(textarea) ──JSON {conversation_id, message}──▶ POST /api/chat/stream
   └─ chat.py 組 initial_state(query=message, messages=[HumanMessage(text)])
        └─ graph.astream_events(initial_state)        ← 進入 LangGraph
             START → compact_check → [summarizer] → unified_intent(OpenAI) → {router}
                  → retriever(文字向量檢索) → context_builder → retrieval_grader(OpenAI)
                     → query_rewriter ↺ / form_structurer / responder ∥ source_filter → END
        └─ SSE 逐 token 回傳 {type:text/sources/form_files/done}
```

- 入口：`app/api/chat.py:106-130` 組 `initial_state`；`graph.add_edge(START, "compact_check")` 於 `app/graph/builder.py:145`。
- `ChatRequest` 目前只有 `{conversation_id, message}`（`app/schemas/chat.py:4-6`）。
- **檢索用的是 `state["query"]`**（`app/graph/nodes/retrieval.py`，雙路 RRF：原 query + rewritten）→ 這是我們讓「圖片內容影響檢索」的施力點。
- **responder 用的是 `state["messages"]` + `state["context"]`**（`app/graph/nodes/generation.py:_build_messages`），不是 `query` → 所以圖片解析要另外注入 responder 的 context（Stage 3）。
- checkpointer = **PostgreSQL**（`.env` 的 `LANGGRAPH_DB_URL`）→ 所以**絕不能**把圖片 base64 放進會被 checkpoint 的 state/messages（這就是 D3 選「存磁碟、state 只放路徑」的原因）。
- 目前**完全沒有**任何檔案上傳：後端無 `UploadFile`、前端 InputBar 無 file picker / paste / drag-drop。

### 0.3 搜尋模組（鋼筋盤價助理）不在本次範圍

`app/modules/search/llm/gemini_client.py` 是 search 模組**自己**的 google-genai 用法（為了 GoogleSearch grounding），與主 RAG 的 `get_llm()` 是兩套。**本次完全不碰 search 模組。**

---

## 1. 設計總則

### 1.1 核心策略：在 graph 最前面附加一個「視覺理解」節點，把圖片「翻成文字」再進既有流程

這正是你描述的流程：

```
使用者上傳圖片 + 文字
   └─ vision_intake（新節點，Gemini 3.5 Flash）
        讀圖 → 產出「圖片內容解析」(OCR/描述/表格數值)
        → 解析文字併入 state["query"]、另存 state["image_understanding"]
   └─ 之後完全照現有 graph 跑：
        unified_intent / retriever / grader 都吃「文字（含圖片解析）」→ 邏輯零改動
   └─ responder（Gemini）：拿「image_understanding 文字解析 + 原圖」一起生成答案（D4）
```

**為什麼這個設計最不動架構**：

| 既有節點 | 看到的東西 | 需要改嗎 |
|---|---|---|
| unified_intent（OpenAI） | 讀 `query`（已含圖片解析文字） | **不改**：照常分類，且因為解析併入而能正確判斷「在問圖片」 |
| retriever | 讀 `query`（已含圖片解析文字） | **不改**：解析文字直接讓向量檢索找到相關文件 |
| retrieval_grader / query_rewriter（OpenAI） | 讀 `query` / `context` | **不改** |
| responder（Gemini） | `context` + `messages`，**新增**讀 `image_understanding` + 原圖 | **小改**：`_build_messages` 多注入「圖片內容」與原圖 block |

> 一句話：**圖片在進入既有 graph 之前就被 Gemini 翻成文字了**，所以 graph 內部所有節點繼續處理「文字」，邏輯一行都不用改。唯一真正的新東西是「最前面那個翻譯節點」和「responder 多讀一段 context + 原圖」。

### 1.2 傳輸與保存（D2 + D3）

- **上傳**（D2）：新增 `POST /api/chat/upload`（multipart）。前端先上傳圖片 → 後端存磁碟 → 回 `image_id`；送訊息時 `ChatRequest` 帶 `image_ids: [...]`。
- **保存**（D3）：圖片 bytes 存磁碟（`UPLOAD_DIR`，預設 `./data/uploads/{user_id}/{uuid}.{ext}`）。graph state 只放 `image_refs=[{id, path, mime}]`（極小）+ `image_understanding`（文字解析，數百 token，可接受）。**base64 永遠不進 state / messages / checkpoint。** responder 要用原圖時，**從磁碟現讀**（D4），用完即丟，不寫回 state。
- **安全**：上傳端點要 auth；驗證 mime（png/jpeg/webp）、大小上限（預設 10MB）；檔名用 server 端 uuid（不信任 client 檔名）；`image_id → path` 解析時鎖在「當前使用者」的目錄下（防止 A 引用 B 的圖、防 path traversal）。

### 1.3 沿用同一個 model（你的 Q1）

`vision_intake` 與 responder 都用 `get_llm("default")` = `google_genai:gemini-3.5-flash`。**不新增 model、不新增 SDK、不新增金鑰**（`GOOGLE_API_KEY` 已存在）。若日後 OCR 精度不足，可加一個 `VISION_MODEL` 環境變數獨立指定（例如 `gemini-3.1-pro`），但 v1 先用 default。

---

## 2. 決策（D1–D7 全部於 2026-06-01 確認）

| # | 決策 | 結論 |
|---|---|---|
| D1 | 視覺理解放在 graph 哪一層 | ✅ **前置 `vision_intake` 節點**：Gemini 先讀懂圖 → 解析+文字一起進 workflow → 既有 intent/檢索/grader 處理文字 → 檢索出解答 |
| D2 | 圖片傳輸方式 | ✅ **新增 `POST /api/chat/upload`（multipart）**，回 `image_id`；chat 帶 `image_ids` |
| D3 | 圖片保存 | ✅ **存磁碟**，state 只放 `path/id`；base64 不進 checkpoint |
| D4 | responder 是否「也看原圖」 | ✅ **要**：responder 同時拿「文字解析 + 原圖」，精度優先（**併入 Stage 3**，不另開可選 stage） |
| D5 | 視覺用哪個 model | ✅ **沿用 default = `gemini-3.5-flash`**；保留日後加 `VISION_MODEL` 的彈性（不在 v1） |
| D6 | 多輪圖片對話 | ✅ **要支援**：carry-forward `image_refs`/`image_understanding`（仿 `prev_form_data`），本輪無新圖時沿用上一張、**不重跑 Gemini**（Stage 5） |
| D7 | git 工作方式 | ✅ 已開新分支 `feat/vlm-image-input`，**從 `feat/fengxing-gemini` 開**（該分支才是最新 code，非 master）。`feng_hsin_price_fetcher.py` 已 commit（07f2149）；`chroma.sqlite3` 是 gitignore 的執行期 DB，依使用者指示不 commit（2026-06-05 建立分支） |

---

## 3. 分階段執行（每階段都可獨立測試，驗證 OK 再進下一階段）

> 原則：每階段結束系統都處於「可運作或更好」的狀態；每階段一個 commit，出事就 revert 該 commit + 重啟。
> 全部新行為都用 `if image_refs:` 包住 → **純文字提問的行為逐位元不變**。

### Stage 0 — 開工前驗證（無程式碼變更）
- [ ] 確認 `langchain-google-genai` 接受的多模態訊息格式（`image_url` data-URL vs 新版 typed image block）；寫一支 ~10 行 smoke：`get_llm("default")` 餵一張本地圖 + 一句問題，確認 Gemini 3.5 Flash 能回描述。
- [ ] 確認 `GOOGLE_API_KEY` 可用（已存在）、`google-genai`/`langchain-google-genai` 已裝。
- [ ] 決定 D7（建分支時機），處理未 commit 檔案。
- **驗證**：smoke 腳本印出對一張測試圖的文字描述。**此階段不改任何線上程式碼。**
- **✅ 驗證結果（2026-06-05，用 repo 內 `data_markdown/.../page-05.png` 掃描頁實測）**：
  - `get_llm("default")` = `gemini-3.5-flash` 讀圖 OCR **極精準**：完整讀出「工程命令通知單」所有欄位/數值（工令代號 CA201、合約金額 1,932,402,143、工期 1275 日曆天…）、流程圖節點、紅框註記、手寫簽名、印章日期。
  - **可用格式 = A**：`{"type":"image_url","image_url":{"url":"data:<mime>;base64,<b64>"}}`（驗於 langchain-google-genai 4.2.3 / langchain-core 1.x；格式 B/C 未測，A 已足夠）。
  - 回傳 `content` 為 `list[block]`（Gemini 3.x）→ 既有 `.text` accessor / content-block 解析可取乾淨字串。
  - `usage_metadata` 正常（input 1150 / output 1922，其中 reasoning≈921 → **thinking 預設開著**；vision_intake 視需要可關 thinking 省 token/延遲，OCR 品質已足夠）。
  - 環境注意：Windows 主控台 cp950 印不出 emoji；正式 code 不影響（不會 print emoji 到 console）。

### Stage 1 — 後端上傳端點 + 存磁碟 + 加欄位（不接線，零風險）
- [ ] `app/config.py` 加 `upload_dir: str = "./data/uploads"`（附加設定，向後相容）。
- [ ] 新增 `POST /api/chat/upload`（multipart，`UploadFile`，auth）：驗證 mime/大小 → 存 `{upload_dir}/{user_id}/{uuid}.{ext}` → 回 `{image_id, mime_type}`。加一個 `resolve_image(user_id, image_id) -> path` helper（鎖目錄、防 traversal）。
- [ ] `app/schemas/chat.py`：`ChatRequest` 加 `image_ids: list[str] = []`（optional，預設空 → **既有前端不受影響**）。
- [ ] `app/graph/state.py`：`GraphState` 加 `image_refs: list[dict]` 與 `image_understanding: Optional[str]`（附加欄位）。
- [ ] `app/api/chat.py`：讀 `body.image_ids` → `resolve_image` → 塞 `initial_state["image_refs"]`；`image_understanding=None`。（此時**還沒有節點消費它們** → 行為不變。）
- **驗證**：(a) 用 curl/Postman 上傳一張圖 → 拿到 `image_id`、磁碟有檔；(b) 帶 `image_ids` 打 `/stream` → 回覆與現在**完全一樣**（圖片暫時被忽略）；(c) 不帶 `image_ids` 的舊請求照常運作。

### Stage 2 — `vision_intake` 節點 + 接進 graph（核心）
- [ ] 新檔 `app/graph/nodes/vision.py`：`async def vision_intake(state)`：
  - `image_refs` 為空 → `return {}`（**no-op，純文字流程跳過，零影響**）。
  - 有圖 → 讀檔 bytes → 組多模態 `HumanMessage([text: state["query"] + 指示, image(s)])`（用 Stage 0 已驗證的**格式 A**：`{"type":"image_url","image_url":{"url":"data:<mime>;base64,..."}}`）→ `get_llm("default")`（Gemini）→ 得 `understanding`。
  - system prompt：「你是影像理解助手，只『描述/OCR』圖片內容（表格逐列列出數值與標題、文件做 OCR），**不要回答問題**。」
  - `return {"image_understanding": understanding, "query": state["query"] + "\n\n[使用者上傳圖片的內容解析]\n" + understanding}`。
- [ ] `app/graph/builder.py`：`add_node("vision_intake", vision_intake)`；把 `START → compact_check` 改成 `START → vision_intake → compact_check`（移 1 條、加 2 條 edge）。**其餘拓撲全不動。**
- **驗證**：(a) 純文字提問 → 行為與 Stage 1 完全相同（節點 no-op）；(b) 圖+文字提問 → 在 LangSmith/log 看到 `vision_intake` 產出解析、`query` 被 enrich、retriever 用 enriched query 檢索到相關文件。

### Stage 3 — responder 用「圖片解析 + 原圖」生成答案（核心，含 D4）
- [ ] `app/graph/nodes/generation.py` 的 `_build_messages`（全部用 `if image_understanding / image_refs` 包住，純文字流程不變）：
  - 若 `image_understanding` 存在 → 在 `system_content` 注入「[圖片內容]\n{understanding}」（與既有 `summary_section`/`form_section` 同手法）。
  - 若 `image_refs` 存在（D4=是）→ 把**本輪的 `HumanMessage` 改組成多模態**（text + 從磁碟現讀的原圖 block），讓 Gemini 生成前能再核對原圖像素。**僅供本次 LLM call，不寫回 `state["messages"]`**（base64 不進 checkpoint）。
- **驗證**：對盤價表截圖提問 → 答案精準引用圖中數字；可先暫時關掉原圖只測文字 grounding、再開原圖比較精度差異；純文字提問的 system prompt/訊息**完全不變**。

### Stage 4 — 前端上傳 UI（端到端打通）
- [ ] `frontend/lib/api.ts`：加 `uploadImage(file)` → multipart POST `/api/chat/upload`（帶 auth）→ 回 `{image_id, mime_type}`。
- [ ] chat store（Zustand）：加「待送附件」狀態 `pendingImages: [{image_id, previewUrl, mime}]`。
- [ ] `frontend/components/chat/InputBar.tsx`：加「附加圖片」鈕 + 隱藏 `<input type=file>`（可選 onPaste / onDrop）→ 選圖即 `uploadImage` → 顯示縮圖 chip（可移除）。送出時把 `image_ids` 一起帶上。
- [ ] `frontend/app/(app)/chat/[conversationId]/page.tsx` + `frontend/lib/sse.ts`：`streamChat` 多帶 `imageIds`，放進 POST body。
- **驗證**：瀏覽器實測 —— 附圖、提問、看到串流答案；不附圖時行為與現在一致。

### Stage 5 — 多輪圖片對話延續（核心，D6）
- [ ] `app/graph/state.py`：`GraphState` 再加 `prev_image_refs` / `prev_image_understanding`（附加欄位）。
- [ ] `app/api/chat.py`：仿 `prev_form_data`，從 `graph.aget_state` 撈上輪 `image_refs` / `image_understanding` → 放進 `initial_state` 的 `prev_image_*`。
- [ ] `vision_intake`：本輪**有**新圖 → 照常處理（取代上一張）；本輪**無**新圖但有 `prev_image_*` → 直接沿用上一張的 `image_understanding`（**不重跑 Gemini**，零額外成本），並把 `image_refs` 設為舊圖路徑 → responder（D4=是）會**從磁碟重讀舊圖**回答細節。
- [ ] 策略：保留「最近一組」圖片，使用者上傳新圖即取代。
- **驗證**：上傳盤價表問一輪 → 下一輪不附圖追問「那張圖的 SD420 比上週漲多少」仍精準答得出。

### Stage 6 — 收尾與體驗
- [ ] SSE：`vision_intake` 的 `on_chain_start` → 推 `{type:"image_reading"}`，前端顯示「正在讀取圖片…」（仿 `form_loading`，見 `app/api/chat.py:152`）。
- [ ] 聊天泡泡顯示使用者上傳的縮圖（本次用 previewUrl；若要重整後仍顯示歷史圖，需加 `GET /api/chat/image/{id}` serve 端點）。
- [ ] 磁碟清理策略（定期清過期上傳檔；單機 PM2 部署下本地磁碟即可）。

---

## 4. 會更動 / 不會更動的檔案

**會新增**
- `backend/app/graph/nodes/vision.py`（`vision_intake` 節點）
- `POST /api/chat/upload` 端點（放在 `app/api/chat.py` 或新 `app/api/uploads.py`）+ `resolve_image` helper

**會修改（小範圍、全部 `if image_refs:` 包住）**
- `app/config.py`（加 `upload_dir`）
- `app/schemas/chat.py`（`ChatRequest` 加 `image_ids`）
- `app/graph/state.py`（`GraphState` 加 `image_refs` / `image_understanding`；Stage 5 再加 `prev_image_*`）
- `app/api/chat.py`（resolve image_ids → `initial_state`；Stage 5 carry-forward；可選 SSE 指示）
- `app/graph/builder.py`（**僅** `START → vision_intake → compact_check`，加 1 節點）
- `app/graph/nodes/generation.py`（`_build_messages` 注入 image_understanding + 原圖多模態，Stage 3）
- 前端：`lib/api.ts`、`lib/sse.ts`、`components/chat/InputBar.tsx`、`chat/[conversationId]/page.tsx`、chat store

**絕對不動**
- `app/core/llm.py`（provider-agnostic 工廠，照用）
- `unified_intent` / `retriever` / `context_builder` / `grader` / `query_rewriter` / `form_*` / `source_filter` / `compact` 等**所有既有節點邏輯**
- graph 既有拓撲（除了最前面加一個會 no-op 的節點）、SSE 協定、ChromaDB 檢索、embeddings
- 所有走 OpenAI 的節點維持 OpenAI
- search 模組（鋼筋盤價助理）整套
- DB schema（只新增 state 欄位，不改 checkpointer schema）

---

## 5. 風險與對策

| 風險 | 說明 | 對策 |
|---|---|---|
| **多模態訊息格式** | `langchain-google-genai` 版本對 image block 格式要求可能不同 | Stage 0 先 smoke 驗證確切格式（`image_url` data-URL / typed block），再開工 |
| **enriched query 稀釋檢索** | 把長解析併進 `query` 可能讓向量檢索失焦 | 解析輸出控制長度；必要時「給檢索的精簡版」與「給答案的詳細版」分開（v1 先單一、觀察 LangSmith 召回） |
| **intent 對 enriched query 誤判** | unified_intent 讀到很長的圖片解析可能影響分類 | 驗證階段用幾種圖測 intent；必要時在 intent prompt 加一句極小提示（盡量不動） |
| **checkpoint 膨脹** | Postgres checkpoint 被圖片撐大 | D3 已避免（state 只放路徑，原圖從磁碟現讀）；`image_understanding` 是文字（可接受） |
| **圖片安全** | 惡意檔 / 過大 / path traversal / 跨使用者引用 | 上傳端 auth + mime/大小驗證 + server uuid 檔名；`resolve_image` 鎖當前使用者目錄 |
| **首 token 延遲** | D4=是 → 圖片會送 Gemini 兩次（vision_intake + responder），答案前會多卡一下 | Stage 6 加「讀取圖片中…」指示；Flash 本身快、成本低；必要時評估 vision_intake 用更輕設定 |
| **image-only（沒打字）** | `body.message` 為空 → `save_message`/`auto_set_title`/intent 邊界 | 空訊息時存 `[圖片]` placeholder；vision 解析併入 query 後 intent 仍可分類 |
| **多機部署** | 上傳檔在本地磁碟，未來水平擴展不共享 | 目前單機 PM2（backend:8000）OK；日後可換物件儲存（S3 等），`image_refs` 抽象已預留 |

---

## 6. 執行節奏

D1–D7 全部確認 → 從 **Stage 0**（smoke 驗證多模態格式）開始，再進 **Stage 1**（上傳端點，零風險不接線），逐階段推進。
每做完一階段就停下來，你手動重啟 + 驗證 OK 再進下一階段。
**D7：已從 `feat/fengxing-gemini` 開新分支 `feat/vlm-image-input`（2026-06-05）。**
