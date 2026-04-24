# Docker 地端部署計畫書

> 目標：將 RAG 問答系統部署於本機，支援電腦與區網手機存取。  
> 分支：`docker/deployment`（master 保持不動作為備份）

---

## 系統架構

```
區網裝置（電腦 / 手機）
        ↓  http://機器IP:80
    ┌─────────────────────────────┐
    │          nginx:80           │
    │  /api/chat/stream → 後端    │  ← SSE，關閉 buffering
    │  /api/*           → 後端    │
    │  /images/*        → 後端    │
    │  /*               → 前端    │
    └─────┬──────────────┬────────┘
          │              │
   frontend:3000    backend:8000
   (Next.js)        (FastAPI)
          │              │
          └──────┬───────┘
            app-net（Docker 內部）
```

### 資料層（掛載至後端容器）

| 主機路徑 | 容器路徑 | 說明 |
|---------|---------|------|
| `./backend/app.db` | `/app/app.db` | SQLite 主資料庫（帳號、對話） |
| `./backend/langgraph.db` | `/app/langgraph.db` | LangGraph 狀態 checkpoint |
| `./backend/chroma_db/` | `/app/chroma_db/` | ChromaDB 向量索引 |
| `./data_markdown/` | `/data_markdown/` | 知識庫 markdown + 圖片（唯讀） |

---

## 前置需求

| 項目 | 版本要求 | 確認方式 |
|------|---------|---------|
| Docker Desktop | ≥ 4.x | `docker --version` |
| Docker Compose | ≥ 2.x（已含於 Desktop） | `docker compose version` |
| Port 80 可用 | 未被 IIS/其他服務佔用 | `netstat -ano \| findstr :80` |
| Port 3000, 8000 可用（備用） | 若 80 被占用再開 | 同上 |

> ⚠️ Windows 上 port 80 可能被 World Wide Web Publishing Service 佔用，  
> 若有衝突可在 `docker-compose.yml` 改成 `"8080:80"`。

---

## 需要建立 / 修改的檔案清單

### 新增檔案
```
data/
├── docker-compose.yml           ← 主要 Compose 設定
├── .env.docker                  ← Docker 專用環境變數
├── backend/
│   ├── Dockerfile
│   └── .dockerignore
├── frontend/
│   ├── Dockerfile
│   └── .dockerignore
└── nginx/
    └── nginx.conf
```

### 修改現有檔案
```
frontend/next.config.ts          ← 加入 output: 'standalone'（必要）
```

---

## Step 1：修改 `frontend/next.config.ts`

**目的**：加入 `output: 'standalone'`，讓 Next.js 生產 image 只包含必要檔案（否則 image 會超過 1GB）。

**修改內容**：
```ts
const nextConfig: NextConfig = {
  output: "standalone",     // ← 加這行
  allowedDevOrigins,
  async rewrites() { ... }
};
```

**潛在問題**：
- `standalone` 模式不會複製 `public/` 目錄，Dockerfile 需手動複製。
- `standalone` 模式不會複製 `.next/static/`，Dockerfile 需手動複製。

---

## Step 2：建立 `backend/Dockerfile`

**設計重點**：
- 使用 `python:3.12-slim` 基底
- 以 uv 安裝相依套件
- 非 root 使用者執行
- 啟動前自動執行 `alembic upgrade head`（migration 是 idempotent，重複執行安全）

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# 先複製 dependency 宣告（layer cache 最大化）
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# 複製應用程式碼
COPY . .

# 建立非 root 使用者
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --disabled-password --no-create-home appuser && \
    chown -R appuser:appgroup /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# migration 完再啟動
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

**潛在問題**：
- `uv.lock` 不存在時 `--frozen` 會失敗，加了 fallback 處理。
- alembic.ini 需確認存在於 `backend/` 目錄下（build context 是 `./backend`）。
- ChromaDB 含 C++ 二進位套件，build 時需要 gcc：`RUN apt-get update && apt-get install -y gcc g++ && rm -rf /var/lib/apt/lists/*`

---

## Step 3：建立 `backend/.dockerignore`

```
__pycache__/
*.pyc
*.pyo
.env
.env.*
*.db           ← SQLite 不打進 image（走 bind mount）
chroma_db/     ← 向量庫不打進 image（走 bind mount）
chroma_versions/
tests/
.venv/
```

---

## Step 4：建立 `frontend/Dockerfile`

**設計重點**：
- Multi-stage build（deps → builder → runner）
- Build 時 `NEXT_PUBLIC_BACKEND_URL=""` → SSE 走相對路徑，nginx 處理路由
- `BACKEND_URL=http://backend:8000` → Next.js server-side proxy 用 Docker 服務名稱

```dockerfile
# ── Stage 1: 安裝相依套件 ─────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

# ── Stage 2: Build ────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC 在 build 時 bake 進 bundle
# 空字串 → fetch("/api/chat/stream") 走相對路徑 → nginx 轉到後端
ENV NEXT_PUBLIC_BACKEND_URL=""
ENV BACKEND_URL="http://backend:8000"

RUN npm run build

# ── Stage 3: 生產 runtime ─────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# standalone 模式的輸出
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
```

**潛在問題**：
- `next.config.ts` 若未加 `output: "standalone"`，`/app/.next/standalone` 不存在，Build 會失敗。
- `NEXT_PUBLIC_BACKEND_URL=""` 空字串：SSE 連線變成 `fetch("/api/chat/stream")`，nginx 需正確路由 `/api/chat/stream`（見 Step 5）。

---

## Step 5：建立 `frontend/.dockerignore`

```
node_modules/
.next/
.env
.env.*
.env.local
Dockerfile
.dockerignore
```

---

## Step 6：建立 `nginx/nginx.conf`

**關鍵設定**：SSE（`/api/chat/stream`）必須關閉 proxy buffering，否則 token 不會即時送出。

```nginx
server {
    listen 80;

    # ── SSE 串流（關閉 buffering）─────────────────────
    location = /api/chat/stream {
        proxy_pass         http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header   Connection '';
        proxy_buffering    off;
        proxy_cache        off;
        chunked_transfer_encoding on;
        proxy_read_timeout 300s;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    }

    # ── 其他 API + 圖片 ───────────────────────────────
    location ~ ^/(api|images)/ {
        proxy_pass         http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host            $host;
        proxy_set_header   X-Real-IP       $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }

    # ── 前端 Next.js ─────────────────────────────────
    location / {
        proxy_pass         http://frontend:3000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection 'upgrade';
        proxy_set_header   Host       $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

**潛在問題**：
- `proxy_read_timeout 300s`：LangGraph 複雜查詢可能超過 60 秒，需要足夠長的 timeout。
- nginx 容器啟動時 backend/frontend 可能還沒 ready，靠 `depends_on` + healthcheck 控制順序。

---

## Step 7：建立 `docker-compose.yml`

```yaml
services:

  # ── 後端 ─────────────────────────────────────────
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file:
      - .env.docker
    volumes:
      - ./backend/app.db:/app/app.db
      - ./backend/langgraph.db:/app/langgraph.db
      - ./backend/chroma_db:/app/chroma_db
      - ./data_markdown:/data_markdown:ro
    networks:
      - app-net
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s

  # ── 前端 ─────────────────────────────────────────
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - NODE_ENV=production
    networks:
      - app-net
    depends_on:
      backend:
        condition: service_healthy

  # ── nginx ─────────────────────────────────────────
  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    ports:
      - "80:80"          # 若 port 80 衝突，改 "8080:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - app-net
    depends_on:
      - frontend
      - backend

networks:
  app-net:
    driver: bridge
```

---

## Step 8：建立 `.env.docker`

**此檔案放在專案根目錄，不進入 git（已在 `.gitignore`）。**

```env
# OpenAI
OPENAI_API_KEY=sk-proj-你的金鑰

# 模型設定（與 .env 相同）
LLM_MODEL=gpt-5.4
GRADER_MODEL=gpt-5.4-mini
FORM_MODEL=gpt-5.4
EMBEDDING_MODEL=text-embedding-3-small

# 資料庫路徑（相對於容器 WORKDIR /app）
DATABASE_URL=sqlite+aiosqlite:///./app.db
SYNC_DATABASE_URL=sqlite:///./app.db
LANGGRAPH_DB_PATH=./langgraph.db

# JWT（正式部署請更換為隨機字串）
SECRET_KEY=請換成隨機字串至少32字元
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=7

# ChromaDB
CHROMA_PERSIST_PATH=./chroma_db
CHROMA_ACTIVE_VERSION=v3

# CORS：允許從同區網存取（加入機器 IP）
APP_ENV=production
CORS_ORIGINS=http://localhost,http://10.21.2.5

# LangSmith（可選，不需要可留空）
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=
```

**潛在問題**：
- `CORS_ORIGINS` 需包含實際存取的 URL。走 nginx port 80，不再需要 `:3000` 或 `:8000`。
- `SECRET_KEY` 若使用預設值，JWT token 在不同機器間不安全。

---

## Step 9：確認 `backend/alembic.ini` 路徑

alembic 在容器內從 `/app` 執行，需確認 `alembic.ini` 存在於 `backend/` 目錄。

```bash
# 確認指令（在 master 分支執行）
ls backend/alembic.ini
ls backend/alembic/
```

---

## Step 10：首次啟動流程

```bash
# 1. 確認現有資料庫檔案存在（bind mount 來源）
ls backend/app.db
ls backend/langgraph.db
ls backend/chroma_db/

# 2. 確認 .env.docker 已建立並填入金鑰
cat .env.docker | grep OPENAI_API_KEY

# 3. Build images（第一次較慢，10–20 分鐘）
docker compose build

# 4. 啟動（背景執行）
docker compose up -d

# 5. 觀察啟動狀態
docker compose logs -f

# 6. 確認所有容器健康
docker compose ps
```

**預期輸出**（`docker compose ps`）：
```
NAME         STATUS                   PORTS
backend      Up (healthy)
frontend     Up
nginx        Up                       0.0.0.0:80->80/tcp
```

---

## Step 11：驗證測試清單

| 測試項目 | 方法 | 預期結果 |
|---------|------|---------|
| 後端健康 | `curl http://localhost/api/health` | `{"status":"ok"}` |
| 前端頁面 | 瀏覽器開 `http://localhost` | 顯示登入頁面 |
| 登入功能 | 使用現有帳號登入 | 進入對話頁面 |
| 一般問答 | 輸入問題 | 串流回應正常顯示 |
| 表單生成 | 輸入需要表單的問題 | 表單卡片正常顯示 |
| 圖片顯示 | 對話中含圖片的回答 | 圖片正常載入 |
| 手機存取 | 手機瀏覽器開 `http://10.21.2.5` | 正常運作 |

---

## 日常操作

```bash
# 啟動
docker compose up -d

# 停止
docker compose down

# 查看日誌
docker compose logs -f backend     # 後端
docker compose logs -f nginx        # nginx access log

# 重啟單一服務
docker compose restart backend

# 更新程式碼後重新部署
git pull
docker compose build backend        # 或 frontend
docker compose up -d --no-deps backend

# 備份資料（重要！定期執行）
cp backend/app.db backup/app_$(date +%Y%m%d).db
cp backend/langgraph.db backup/langgraph_$(date +%Y%m%d).db
cp -r backend/chroma_db backup/chroma_$(date +%Y%m%d)
```

---

## 已知風險與解法

| 風險 | 說明 | 解法 |
|------|------|------|
| **ChromaDB 平台差異** | 現有 `chroma_db` 在 Windows 上建立，Linux 容器讀取可能有格式問題 | 首次啟動後立即測試語意搜尋，若異常需重新 ingest |
| **Port 80 被占用** | Windows IIS 或其他服務 | `docker-compose.yml` 改 `"8080:80"`，CORS_ORIGINS 也對應更新 |
| **NEXT_PUBLIC_BACKEND_URL bake 問題** | 若將來要換 IP，需重新 build frontend image | 因為走相對路徑（空字串），IP 變動不影響，不需要重 build |
| **SSE timeout** | LangGraph 長查詢超過 nginx 預設 timeout | 已在 nginx.conf 設定 `proxy_read_timeout 300s` |
| **SQLite 寫入鎖定** | 多個同時連線寫入 SQLite 可能造成 `database is locked` | SQLite WAL mode 已啟用（`backend/database.py`），可承受低至中度並發 |
| **SECRET_KEY 安全性** | 預設值不安全 | 部署前必須更換，產生方式：`python -c "import secrets; print(secrets.token_hex(32))"` |

---

## 執行順序總結

```
Step 1  修改 next.config.ts（加 output: standalone）
Step 2  建立 backend/Dockerfile
Step 3  建立 backend/.dockerignore
Step 4  建立 frontend/Dockerfile
Step 5  建立 frontend/.dockerignore
Step 6  建立 nginx/nginx.conf
Step 7  建立 docker-compose.yml
Step 8  建立 .env.docker（填入真實金鑰）
Step 9  確認 alembic.ini 路徑
Step 10 首次 build & 啟動
Step 11 驗證測試
```

> **每個 Step 完成後 commit 一次，方便回溯。**
