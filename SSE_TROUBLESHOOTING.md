# SSE 串流失效排查 SOP

當聊天回應「不是一個字一個字浮現、而是 loading 結束後整段一次性蹦出」，就是 SSE 串流被中途某層 buffer 起來了。本檔記錄排查順序、根因與一鍵修復腳本。

---

## 症狀判斷

| 現象 | 可能類別 |
|---|---|
| Loading 結束後**整段一次性蹦出**（逐字效果消失） | ★ 99% 是路由 / proxy buffer 問題 |
| 完全沒回應、卡在 Thinking | backend 沒起、token 過期、Tailscale Funnel 沒開 |
| **外網開不了 / 瀏覽器憑證警告頁（`ERR_TLS_CERT_ALTNAME_INVALID`）** | Funnel 跑在 443，被本機 IIS/SSTP VPN 搶走、回公司憑證 → 改用 **8443**（見 Step 1 說明、跑 reset 腳本） |
| `Something went wrong. Please try again later.` | backend 起來但路由錯（看後端 log 確認 path） |

下面 SOP 主要解決第一種（最常見）。

---

## Step 1 — 確認 Tailscale 路由（最常見元凶）

```powershell
tailscale serve status
```

**預期**（兩條規則都要在，且 port 是 **8443**）：

```
https://kccw0077.tail138ec9.ts.net:8443 (Funnel on)
|-- /    proxy http://127.0.0.1:3000
|-- /api proxy http://localhost:8000/api
```

> **為什麼是 8443 不是 443**：本機（kccw0077）的 IIS + SSTP VPN 已經佔住作業系統的 443，並送公司憑證 `*.bes.com.tw`。Funnel 若用 443 會搶輸，外網訪客拿到錯憑證（`ERR_TLS_CERT_ALTNAME_INVALID`）連不進來。改用空閒的 8443，tailscaled 才能送正確的 kccw0077 憑證。所以對外網址帶 `:8443` 尾巴。

**不對的情況對照表**：

| 看到 | 意思 | 修法 |
|---|---|---|
| `(tailnet only)` 而非 `(Funnel on)` | Funnel 關了，外網連不進 | 跑 Step 3 reset 腳本 |
| 只有 `/`，沒有 `/api` | `/api` 規則被覆寫掉 ← **SSE 失效最常見禍首** | 跑 Step 3 reset 腳本 |
| `/api proxy http://localhost:8000`（少結尾 `/api`） | path prefix 被剝光、backend 收到 `/chat/stream` 變 404 | 跑 Step 3 reset 腳本 |
| `/` 指向 `:443` 或其他奇怪 port | 之前哪條 tailscale 指令誤覆寫 | 跑 Step 3 reset 腳本 |

> **核心知識**：Tailscale `serve` / `funnel` CLI 是**全域 mutate** — 不是 append。任何指令會影響整體 config，少寫 `--set-path=/api` 就會把那條規則弄掉。所以恢復時要用「reset → 重建兩條」的方式，不能只補一條。

---

## Step 2 — 確認後端是否在跑

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000
```

**預期**：看到 `8000  Listen ...` 一行。

**沒輸出 = backend 沒在跑**。COMODO EDR 限制下，backend 只能在 IDE terminal 手動起：

```powershell
cd C:\Users\226376\Desktop\data\backend
uv run python run_server.py
```

看到 `Application startup complete` 才算 OK，**這個 terminal 不能關**（關掉 = backend 停）。

> COMODO 為何擋：PM2 / 雙擊 `.bat` 起的 python 父 process chain 不被 COMODO 信任，連 PostgreSQL :5432 會 `WSAEACCES 10013`。只有「使用者前景互動 shell」起的 process chain 才會通過。

---

## Step 3 — 一鍵修復路由

如果 Step 1 路由有任何不對，PowerShell 跑：

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\226376\Desktop\data\reset-tailscale-routing.ps1
```

腳本流程：

1. `tailscale serve reset`（清空現有規則）
2. `tailscale funnel --bg http://localhost:3000` 加回 `/` → frontend
3. `tailscale funnel --bg --set-path=/api http://localhost:8000/api` 加回 `/api` → backend
4. 印出 `tailscale serve status` 給你驗證

---

## Step 4 — 瀏覽器強制刷新

```
Ctrl + Shift + R
```

清掉舊的 fetch 連線 / cache，重新建立 SSE 連線。

---

## Step 5 — 仍然失效？看後端 log

切到跑 backend 的 IDE terminal，發一個訊息，觀察 log：

| 看到 | 意思 | 處理 |
|---|---|---|
| `POST /api/chat/stream HTTP/1.1" 200 OK` | 後端正常 | 問題在前端（→ Step 6）|
| `POST /chat/stream HTTP/1.1" 404 Not Found` | Tailscale 把 `/api` 剝光、target URL 少結尾 `/api` | 跑 Step 3 reset 腳本 |
| 什麼都沒收到 | Tailscale 路由根本沒導到 backend | 跑 Step 3 reset 腳本 |
| `500 / Internal Server Error` | 後端 graph 內部錯誤 | 看 stack trace，跟本 SOP 無關 |

---

## Step 6 — 後端真的沒問題，那是前端

```powershell
pm2 logs frontend --lines 50 --nostream
```

主要看 [frontend/lib/sse.ts](frontend/lib/sse.ts) 有沒有被改壞。**三個關鍵點不能動**：

1. **直連 backend，不走 Next.js rewrite**：
   ```ts
   const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
   fetch(`${backendUrl}/api/chat/stream`, ...)
   ```
   Next.js `rewrites()` 會 buffer SSE response，必須繞過。

2. **ReadableStream 逐 chunk 讀**：
   ```ts
   const reader = response.body!.getReader();
   const decoder = new TextDecoder();
   // ... 用 line buffer 切 \n\n 分隔的 event
   ```
   不能改成 `response.text()` / `response.json()` — 那樣會等收完才回。

3. **`.env.local` 的 `NEXT_PUBLIC_BACKEND_URL`** 要指 Funnel URL（不是 `localhost:8000`）：
   ```
   NEXT_PUBLIC_BACKEND_URL=https://kccw0077.tail138ec9.ts.net:8443
   ```
   因為這個變數是 build-time 烤進瀏覽器 bundle 的，外網員工的瀏覽器無法解析 `localhost`。

---

## 一句話 TL;DR

**SSE 失效 → 90% 是 `/api` 路由不見了 → 跑 [reset-tailscale-routing.ps1](reset-tailscale-routing.ps1) → 瀏覽器 Ctrl+Shift+R**

剩下 10% 才需要查 backend 是否在跑、後端 log、前端 reader 程式碼。

---

## 為什麼會這樣設計（背景知識）

完整流量路徑：

```
瀏覽器
   │  POST /api/chat/stream
   ▼
Tailscale Funnel  (公網入口)
   ├── /     → 127.0.0.1:3000  (Next.js frontend，給一般頁面用)
   └── /api  → 127.0.0.1:8000/api  (FastAPI backend，給 API + SSE 用)
                                    ↑
                                 SSE 走這條，繞開 Next.js
                                 (Next.js rewrites() 會 buffer streaming response)
```

**為什麼 `/api` target URL 要尾巴帶 `/api`**：Tailscale `--set-path=/api` 會在轉發前把 `/api` 前綴**剝掉**，所以 target URL 必須補回 `/api`，這樣 backend 收到的 path 才會跟 FastAPI router prefix 對上。

**為什麼 Next.js rewrites 不能用於 SSE**：Next.js 的 `rewrites()` 用 Node 內建 fetch（undici）做反向代理，對 streaming response 會 buffer 整個 body 收完才轉出。一般 JSON API 無感（response 本來就一次到位），只有 SSE / chunked response 會壞。詳細見 [frontend/lib/sse.ts:29](frontend/lib/sse.ts#L29) 的註解。

---

## 相關檔案

- [reset-tailscale-routing.ps1](reset-tailscale-routing.ps1) — 一鍵重設路由
- [start-system.bat](start-system.bat) — 啟動系統（含 Tailscale 路由設定）
- [frontend/lib/sse.ts](frontend/lib/sse.ts) — 前端 SSE reader
- [frontend/.env.local](frontend/.env.local) — `NEXT_PUBLIC_BACKEND_URL` 設定
- [backend/app/api/chat.py](backend/app/api/chat.py) — 後端 SSE endpoint
- [README.md](README.md#目前啟動方式comodo-acl-限制) — 啟動順序（COMODO 限制）
