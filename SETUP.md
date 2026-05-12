# Setup — 從 clone 到跑起來

完整的本地啟動指南。第一次走完約 15-20 分鐘（多數時間是依賴安裝）。

## 前置需求

| 工具 | 版本 | 用途 | 安裝 |
|---|---|---|---|
| **Python** | 3.12+ | backend runtime | [python.org](https://www.python.org/downloads/) |
| **uv** | latest | Python 套件管理（取代 pip/venv） | `pip install uv` 或 [astral.sh/uv](https://docs.astral.sh/uv/) |
| **Node.js** | 20+ | frontend runtime | [nodejs.org](https://nodejs.org/) |
| **Yarn** | 1.22+ | 前端套件管理 | `npm i -g yarn` |
| **Git** | any | 取得程式碼 | — |

## 1. Clone

```bash
git clone https://github.com/Tsai1030/LangGraph_RAG_SYSTEM.git
cd LangGraph_RAG_SYSTEM
```

## 2. 設定環境變數

```bash
# Linux/Mac
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

編輯 `.env`，**至少填以下三個**：

1. **`OPENAI_API_KEY`** — 取自 https://platform.openai.com/api-keys
2. **`SECRET_KEY`** — 產生方式：
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **`INITIAL_ADMIN_EMAIL`** — 你之後要註冊的 admin 帳號 email

其他變數預設值就能跑（SMTP / LangSmith 可選）。

## 3. Backend 啟動

```bash
cd backend

# 安裝 Python 依賴（首次約 5 分鐘）
uv sync

# 初始化 app.db schema
uv run alembic upgrade head

# 啟動 backend（會自動建立 langgraph.db）
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

確認 backend 健康：

```bash
curl http://localhost:8000/api/health
# 應該回 {"status":"ok"}
```

## 4. Frontend 啟動（另開 terminal）

```bash
cd frontend

# 安裝依賴
yarn install

# 開發模式（HMR、熱重載，適合開發）
yarn dev

# 或 production 模式
yarn build && yarn start
```

打開 http://localhost:3000

## 5. 註冊 admin 帳號

1. 在前端註冊頁面用 `INITIAL_ADMIN_EMAIL` 設定過的 email 註冊
2. **登出後重啟 backend**（讓 bootstrap 自動把該帳號升 admin）
3. 重新登入即可看到 `/admin` 後台

## 6. 確認 RAG 可用

進到 `/new` 開新對話，問一個營造業相關問題，例如「動員開工檢核表是什麼」。

正常會：
- 串流回應一段帶圖片的回答
- 右側 sources 出現參考文件
- 下方可能出現可下載的靜態表卡片

如果回答「目前知識庫未涵蓋此資訊」**且 LangSmith trace 顯示 `retrieval_grader=insufficient`** → 向量庫沒讀到，檢查：
- `.env` 的 `CHROMA_ACTIVE_VERSION=v5` 是否正確
- `backend/chroma_versions/v5/` 目錄是否存在（git clone 後應該自動有）
- backend 啟動 log 應印 `[Startup] RESOLVED_CHROMA_PATH=.../chroma_versions/v5`

---

## 進階：production 部署

repo 內含 `ecosystem.config.js`（PM2 配置）與 `start-system.bat`（Windows 一鍵啟動腳本，含 Caddy + Tailscale Funnel）。詳見 `DEPLOY.md`。

## 進階：重建向量庫

`backend/chroma_versions/v5/` 是針對 `data_markdown/` 內容預先 embed 好的快照。若你修改了 `data_markdown/` 的 markdown 內容、想重建：

1. 詳細 build script 待補充（目前 v5 是手動產出）
2. 建立後設 `CHROMA_ACTIVE_VERSION=v6`（或你新版本號）
3. 舊版本可保留在 `chroma_versions/v5/` 做 rollback

## 常見問題

**Q: 啟動 backend 時 `OPENAI_API_KEY` validation error**
A: `.env` 缺這個變數或值為空。檢查 `.env` 並重啟。

**Q: `pip` / `uv` 報 jieba / sharp 安裝失敗**
A: 確認 Python 3.12+；Windows 可能要裝 C++ Build Tools。

**Q: 前端可看頁面但發訊息顯示 "Something went wrong"**
A: 通常是 CORS 或 BACKEND_URL 不對。確認 backend `.env` 的 `CORS_ORIGINS` 包含前端 URL，且 frontend 的 proxy（`next.config.ts` 預設 `http://localhost:8000`）能連到 backend。

**Q: ChromaDB 路徑找不到**
A: 確認 `git lfs pull` 不必跑（v5 是純 git，未用 LFS）；確認 `backend/chroma_versions/v5/` 內含 `chroma.sqlite3`。
