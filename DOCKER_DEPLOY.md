# Docker 部署指南

> 適用平台：Windows（新機器）、Linux  
> 前置需求：Docker Desktop、Git、Tailscale

---

## 架構

```
Internet
    ↓  https://kccc3798.tail138ec9.ts.net
Tailscale Funnel
    ↓  http://localhost:80
  nginx:80
  /api/chat/stream → backend:8000  (SSE, proxy_buffering off)
  /api/*           → backend:8000
  /images/*        → backend:8000
  /*               → frontend:3000
       ↓                  ↓
  backend:8000        frontend:3000
  (FastAPI/uvicorn)   (Next.js standalone)
       ↓
    db:5432
  (PostgreSQL 16)
  pg_data volume
```

---

## 新機器首次部署

### 1. 安裝前置工具

| 工具 | 說明 |
|---|---|
| Docker Desktop | https://www.docker.com/products/docker-desktop |
| Git | https://git-scm.com/ |
| Tailscale | https://tailscale.com/download — 登入同一個帳號 `Tsai1030@` |

### 2. Clone 專案

```bash
git clone https://github.com/Tsai1030/LangGraph_RAG_SYSTEM.git
cd LangGraph_RAG_SYSTEM
```

### 3. 設定 `.env.docker`

複製並填入真實值：

```powershell
Copy-Item .env.docker .env.docker.local   # 可選，方便區分
```

或直接編輯 `.env.docker`：

- `POSTGRES_PASSWORD` — 自訂一組新密碼
- `DATABASE_URL` 等四行 — 把 `請換成你的密碼` 換成同一組密碼
- `OPENAI_API_KEY` — 從舊機器 `.env` 複製
- `SECRET_KEY` — 從舊機器 `.env` 複製（或重新產生）
- `GOOGLE_CLIENT_ID` — 從舊機器 `.env` 複製
- `FRONTEND_URL` / `CORS_ORIGINS` — 換成新機器的 Tailscale hostname（見第 6 步）

### 4. 搬移資料庫（從舊機器）

**舊機器** — dump 三個 DB：

```powershell
pg_dump -U kb_user -F c -f kb_app.dump       kb_app
pg_dump -U kb_user -F c -f kb_search.dump    kb_search
pg_dump -U kb_user -F c -f kb_langgraph.dump kb_langgraph
```

把這三個 `.dump` 檔複製到新機器的專案根目錄。

**新機器** — 先啟動 DB 容器再還原：

```powershell
# 只啟動 db service（讓 init-db.sql 跑完建好三個 DB）
docker compose --env-file .env.docker up -d db

# 等 db 健康（約 10 秒）
docker compose ps

# 還原資料
pg_restore -h 127.0.0.1 -U kb_user -d kb_app       kb_app.dump
pg_restore -h 127.0.0.1 -U kb_user -d kb_search    kb_search.dump
pg_restore -h 127.0.0.1 -U kb_user -d kb_langgraph kb_langgraph.dump
```

### 5. 搬移執行期資料（可選）

以下目錄不在 git 裡，若要保留使用者上傳的圖片或產出檔，從舊機器手動複製：

```
backend/data/uploads/
backend/data/search_outputs/
backend/data/generated_forms/
```

### 6. Tailscale Funnel 設定

新機器的 Tailscale 裝置名稱可能不同，建議在 [Tailscale admin console](https://login.tailscale.com/admin/machines) 把新裝置改名為 `kccc3798`（這樣公開網址不變，不需要改其他設定）。

確認裝置名稱後，設定 Funnel（只需一條規則，nginx 統一處理）：

```powershell
tailscale serve reset
tailscale funnel --bg http://localhost:80
tailscale serve status   # 確認 / -> http://localhost:80
```

> 注意：如果改用了新 hostname，要同步更新 `.env.docker` 裡的 `FRONTEND_URL` 和 `CORS_ORIGINS`，再重新 build backend image。

### 7. Build 並啟動

```powershell
# Build 所有 image（首次約 15–25 分鐘）
docker compose --env-file .env.docker build

# 啟動全部服務（背景執行）
docker compose --env-file .env.docker up -d

# 觀察啟動過程
docker compose logs -f
```

預期狀態（`docker compose ps`）：

```
NAME          STATUS              PORTS
db            Up (healthy)
backend       Up (healthy)
frontend      Up
nginx         Up                  0.0.0.0:80->80/tcp
```

---

## 驗證清單

| 項目 | 方法 | 預期結果 |
|---|---|---|
| Backend 健康 | `curl http://localhost/api/health` | `{"status":"ok"}` |
| 前端頁面 | 瀏覽器開 `http://localhost` | 顯示登入頁面 |
| 公開網址 | 瀏覽器開 Tailscale Funnel URL | 同上 |
| 登入 | 用既有帳號登入 | 進入對話頁面 |
| RAG 問答 | 問「動員開工檢核表是什麼」 | 串流回應 + sources |
| SSE 串流 | 觀察回應是否一個 token 一個 token 出現 | 逐字出現（非一次全出） |
| VLM 圖片 | 上傳圖片並提問 | 正常回應 |

---

## 日常操作

```powershell
# 啟動
docker compose --env-file .env.docker up -d

# 停止
docker compose down

# 查看 log
docker compose logs -f backend
docker compose logs -f nginx

# 重啟單一服務
docker compose restart backend

# 更新程式碼後重新部署
git pull
docker compose --env-file .env.docker build backend   # 或 frontend
docker compose --env-file .env.docker up -d --no-deps backend
```

---

## 資料庫備份（定期執行）

```powershell
$date = Get-Date -Format "yyyyMMdd"
pg_dump -h 127.0.0.1 -U kb_user -F c -f "backup/kb_app_$date.dump"       kb_app
pg_dump -h 127.0.0.1 -U kb_user -F c -f "backup/kb_search_$date.dump"    kb_search
pg_dump -h 127.0.0.1 -U kb_user -F c -f "backup/kb_langgraph_$date.dump" kb_langgraph
```

---

## 已知問題與解法

| 問題 | 原因 | 解法 |
|---|---|---|
| `pg_restore` 連線被拒 | db 容器還沒 ready | `docker compose ps` 確認 db 狀態為 `(healthy)` 再 restore |
| backend build 失敗：`chromadb` 編譯錯誤 | gcc 沒安裝進 image | Dockerfile 已加 `apt-get install gcc g++`，若仍失敗檢查網路或 apt mirror |
| SSE 回應一次全出不串流 | nginx buffering 未關閉 | nginx.conf 的 `/api/chat/stream` 已設 `proxy_buffering off`；若仍有問題確認 Tailscale Funnel 指向 `:80` |
| Port 80 被佔用 | Windows IIS 或其他服務 | `docker-compose.yml` 改成 `"8080:80"` 並更新 Tailscale Funnel 目標為 `:8080` |
| `frontend` build 失敗：`.next/standalone` 不存在 | `next.config.ts` 沒有 `output: "standalone"` | 已在 `next.config.ts` 加入，確認這行存在後重新 build |
