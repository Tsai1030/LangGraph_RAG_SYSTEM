# 換機器搬遷清單

> 適用情境：將此專案從一台 Windows 機器移到另一台新機器。

---

## 1. 安裝軟體與工具

| 工具 | 版本 | 安裝方式 |
|---|---|---|
| **Python** | 3.12+ | [python.org](https://www.python.org/downloads/) |
| **uv** | latest | `pip install uv` 或 [astral.sh/uv](https://docs.astral.sh/uv/) |
| **Node.js** | 20+ | [nodejs.org](https://nodejs.org/) |
| **Yarn** | 1.22+ | `npm i -g yarn` |
| **PM2** | latest | `npm install -g pm2` |
| **PostgreSQL** | 13+ | [EnterpriseDB 安裝包](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads)（Windows 建議用此） |
| **Tailscale** | latest | [tailscale.com/download](https://tailscale.com/download) |
| **Git** | any | [git-scm.com](https://git-scm.com/) |
| Windows C++ Build Tools | — | 若 `uv sync` 時 jieba / sharp 編譯失敗才需要安裝 |

> ⚠️ **Caddy 不需要重裝。** 現在的路由架構已改成 Tailscale Funnel 直連 `:3000` 和 `:8000`，Caddy 已從路由鏈中移除。

---

## 2. Clone 專案

```bash
git clone https://github.com/Tsai1030/LangGraph_RAG_SYSTEM.git
cd LangGraph_RAG_SYSTEM
```

`chroma_versions/v5/` 已 commit 進 git，clone 完即可直接使用，不需要重新 embed。

---

## 3. 複製 `.env`（不在 git 裡）

`.env` 被 `.gitignore` 排除，**git clone 不會帶過來**，必須手動複製舊機器的 `.env` 到新機器的專案根目錄。

裡面包含：
- `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY`
- `SECRET_KEY`（JWT 簽名金鑰）
- PostgreSQL 連線字串（含密碼）
- `GOOGLE_CLIENT_ID`
- `SMTP_USER` / `SMTP_PASSWORD`
- `LANGCHAIN_API_KEY`
- `CORS_ORIGINS` / `FRONTEND_URL`（含 Tailscale hostname，見第 6 點）

---

## 4. PostgreSQL 資料庫搬遷

> ⚠️ **這是最容易漏掉的一項。** 現在跑的是 PostgreSQL（不是 `.env.example` 預設的 SQLite），三個資料庫的使用者帳號、對話紀錄、搜尋 index 都在這裡。

### 4-1. 在舊機器 dump

```bash
pg_dump -U kb_user kb_app       > kb_app.sql
pg_dump -U kb_user kb_search    > kb_search.sql
pg_dump -U kb_user kb_langgraph > kb_langgraph.sql
```

### 4-2. 在新機器安裝 PostgreSQL 後建立帳號與資料庫

以 superuser 身分執行：

```sql
CREATE USER kb_user WITH PASSWORD '你的密碼';
CREATE DATABASE kb_app       OWNER kb_user;
CREATE DATABASE kb_search    OWNER kb_user;
CREATE DATABASE kb_langgraph OWNER kb_user;
```

### 4-3. 還原資料

```bash
psql -U kb_user -d kb_app       < kb_app.sql
psql -U kb_user -d kb_search    < kb_search.sql
psql -U kb_user -d kb_langgraph < kb_langgraph.sql
```

### 4-4. 安裝 Python 的 PostgreSQL 驅動

```bash
cd backend
uv add asyncpg psycopg2-binary langgraph-checkpoint-postgres
```

---

## 5. 修改寫死路徑的設定檔

以下檔案含有舊機器的使用者路徑（`C:/Users/226376/Desktop/data`），若新機器的使用者名稱或目錄不同，**必須對應修改**：

### `ecosystem.config.js`（最重要）

```js
// 改成新機器上的實際路徑
cwd: "C:/Users/【新使用者名稱】/Desktop/data/backend",
cwd: "C:/Users/【新使用者名稱】/Desktop/data/frontend",
```

### `start-system.bat`

裡面的 echo 提示訊息含有舊路徑，建議一起更新（不影響實際執行，但會造成混淆）。

### `fix-caddy-blocked.ps1`

含有舊路徑的說明，非必要執行，但建議更新。

---

## 6. Tailscale 設定

### 6-1. 登入

在新機器安裝 Tailscale 後，登入**同一個** Tailscale 帳號（`Tsai1030@`）。

### 6-2. 決定 hostname 策略

目前公開網址 `https://kccc3798.tail138ec9.ts.net` 綁定的是舊機器的裝置名稱 `kccc3798`。有兩個選擇：

**方案 A（建議）：把新機器改名成 `kccc3798`**
- 到 Tailscale 後台 → Machines → 新裝置 → 改名為 `kccc3798`
- 舊裝置記得移除或改名以避免衝突
- 網址不變，不需要改其他檔案

**方案 B：接受新的 hostname**
- 要把以下所有地方換成新 hostname：
  - `.env` 裡的 `CORS_ORIGINS` 和 `FRONTEND_URL`
  - `start-system.bat`
  - `reset-tailscale-routing.ps1`
  - `enter-maintenance.bat`
  - `exit-maintenance.bat`

### 6-3. 啟用 Funnel 並設定路由

確認新裝置在 Tailscale admin console 已啟用 Funnel 權限，然後執行：

```powershell
.\reset-tailscale-routing.ps1
```

確認 `tailscale serve status` 顯示：
```
/ -> http://localhost:3000
/api -> http://localhost:8000/api
```

---

## 7. 安裝前後端依賴

```bash
# Backend
cd backend
uv sync

# 確認 alembic schema 是最新的
uv run alembic upgrade head

# Frontend
cd ../frontend
yarn install
yarn build
```

---

## 8. 執行期資料（gitignore'd，需手動複製）

以下目錄不在 git 裡，若想保留歷史資料要手動複製：

| 目錄 | 說明 |
|---|---|
| `backend/data/uploads/` | VLM 使用者上傳的圖片 |
| `backend/data/search_outputs/` | SEARCH 模組產生的 Word 檔 |

---

## 9. COMODO EDR / 防毒軟體注意事項

目前舊機器上**後端無法透過 PM2 啟動**，是因為 COMODO EDR 擋掉 PM2 衍生的 python 行程連接 PostgreSQL。

- 新機器**沒裝 COMODO**：此限制不存在，可以考慮重新啟用 `ecosystem.config.js` 裡的 backend entry，讓 PM2 也管理後端。
- 新機器**有裝 COMODO 或其他 EDR**：後端依然要手動在 IDE terminal 啟動：
  ```bash
  cd backend
  uv run python run_server.py
  # 這個 terminal 要持續開著，關掉就等於停後端
  ```

---

## 10. 啟動系統

```bash
# 雙擊或右鍵以系統管理員身分執行
start-system.bat
```

腳本會：
1. PM2 啟動 frontend（`:3000`）
2. 設定 Tailscale Funnel 路由
3. 等待 `:3000` 就緒並顯示 `:8000` 狀態

後端需另開 IDE terminal 手動啟動（除非已確認防毒軟體不擋，見第 9 點）。

---

## 11. 驗證清單

| 項目 | 指令 / 方式 | 預期結果 |
|---|---|---|
| Backend 健康 | `curl http://localhost:8000/api/health` | `{"status":"ok"}` |
| Frontend | 瀏覽器開 `http://localhost:3000` | 顯示登入頁面 |
| 公開網址 | 瀏覽器開 Tailscale Funnel 網址 | 同上 |
| RAG 問答 | 登入後問「動員開工檢核表是什麼」 | 串流回應 + sources 側欄 |
| VLM 圖片 | 上傳圖片並送出問題 | 正常回應 |
| Tailscale 路由 | `tailscale serve status` | `/` 和 `/api` 都有對應規則 |
