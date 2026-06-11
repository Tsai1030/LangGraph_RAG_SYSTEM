# Tailscale Funnel 外網存取排查 SOP

當「外網（手機 / 公司外的員工）打不開 `https://kccw0077.tail138ec9.ts.net:8443`」時，本檔記錄完整排查順序、兩層根因、與修復方式。

> 本檔起源：2026-06-09 換機（舊機 `kccc3798` → 新機 `kccw0077`）後外網全面進不去的排查紀錄。

---

## 一句話 TL;DR

外網進不去通常是**兩層問題之一**：

1. **憑證錯**（`ERR_TLS_CERT_ALTNAME_INVALID`）→ Funnel 跑在 443、被本機 IIS/SSTP VPN 搶走 → **Funnel 改走 8443**（已是現狀）。
2. **連主機名都找不到**（手機顯示「無法連上這個網站 / 無法找到指定主機」）→ Tailscale 雲端沒幫這台發布 funnel 的公開 DNS → **重啟 Tailscale 服務**（`Restart-Service Tailscale -Force`，要系統管理員）。

換機後最常踩第 2 個。

---

## 現在的正確狀態（基準線）

```
公開網址：https://kccw0077.tail138ec9.ts.net:8443

tailscale funnel status 應該看到：
  https://kccw0077.tail138ec9.ts.net:8443 (Funnel on)
  |-- /    proxy http://localhost:3000
  |-- /api proxy http://localhost:8000/api
```

- `/`    → Next.js 前端（:3000）
- `/api` → FastAPI 後端（:8000/api，直連、繞過 Next.js 的 SSE buffer）
- 對外 port 是 **8443**（不是 443，原因見下）

---

## 為什麼是 8443 不是 443（第一層根因）

這台機器（kccw0077）的 **IIS（W3SVC）+ SSTP VPN** 已經佔住作業系統的 **443**，並在 HTTP.sys 綁了公司的萬用憑證 `*.bes.com.tw`（TWCA 簽發）。

```
外網訪客 → Tailscale Funnel 入口 → 本機 :443
        → 被 IIS 接走，回傳「*.bes.com.tw」公司憑證（不是 kccw0077 的憑證）
        → 瀏覽器：ERR_TLS_CERT_ALTNAME_INVALID（憑證名稱不符）→ 卡警告頁 → 進不去
```

**證據怎麼抓的：**

```powershell
# 本機看誰佔 443（會看到 PID 4 = System / HTTP.sys）
Get-NetTCPConnection -State Listen -LocalPort 443

# 看 HTTP.sys 綁的 SSL 憑證（會看到 *.bes.com.tw、AppID 是 IIS 的 {4dc3e181-...}）
netsh http show sslcert ipport=0.0.0.0:443
```

**解法**：Funnel 改用空閒的 **8443**（Tailscale Funnel 只允許 443 / 8443 / 10000 三個 port，443 被佔，故用 8443）。tailscaled 在 8443 上會送正確的 kccw0077 Let's Encrypt 憑證。

> 舊機 kccc3798 沒這問題，是因為它沒裝/沒開 IIS 佔 443。

---

## 為什麼換機後「連主機名都找不到」（第二層根因 ← 換機主因）

改成 8443 後**內網**正常、從乾淨外網（如手機行動網路以外）也能通，但**手機/部分外網仍顯示「無法連上這個網站」**。

排查發現：**`kccw0077.tail138ec9.ts.net` 的公開 DNS 是 NODATA（完全沒有 A/AAAA 記錄）**，而舊機 `kccc3798` 有。

```
外網裝置 → 想解析 kccw0077.tail138ec9.ts.net → 查無此記錄 → 「無法找到指定主機」
```

**為什麼沒記錄**：Funnel 的公開 DNS（ingress 記錄）是 **Tailscale 雲端**根據節點回報的「連線資訊」幫忙發布的。換機後新節點的狀態卡住，**沒有把連線資訊回報給雲端**：

- admin console → Machines → kccw0077 → **「Client Connectivity」整欄空白**（舊機有顯示 yes/no）。
- 這代表雲端沒收到這台的 netcheck/endpoint 回報 → 不幫它發布 funnel DNS。

**節點端其實全對**（用以下確認過都正常，所以本機怎麼調都沒用，問題在雲端發布那步）：

```powershell
$ts="C:\Program Files\Tailscale\tailscale.exe"
& $ts status --json | ConvertFrom-Json | % { $_.Self.Capabilities }  # 有 funnel / https / funnel-ports
& $ts status --json | ConvertFrom-Json | % { $_.CertDomains }        # = kccw0077.tail138ec9.ts.net
```

**解法**：**乾淨重啟 Tailscale 服務**，逼節點重新做 netcheck 並把連線資訊回報給雲端 → Client Connectivity 出現數值 → 雲端發布 funnel DNS → 外網解析得到 → 進得去。

> 實測：`tailscale down/up` 不夠（沒讓 Client Connectivity 復活）；**重啟整個 Tailscale 服務**才有效。

---

## 怎麼驗證「外網真的通不通」（不靠自己機器，避免被 MagicDNS 污染）

本機用 `nslookup` / `Resolve-DnsName` 查會被本機 Tailscale 的 MagicDNS 攔截、回傳 100.x 內網位址，**不準**。要看「全世界外部視角」用：

```powershell
# 查公開 A 記錄（Status:0 且 Answer 非空 = 有發布；Answer 空 = NODATA = 沒發布）
# 直接瀏覽器開這個也行：
#   https://dns.google/resolve?name=kccw0077.tail138ec9.ts.net&type=A
```

或用手機**關掉 Wi-Fi、走行動網路**直接開網址測，最貼近真實外網。

---

## 復發排查 SOP（照順序）

### Step 1 — 先分辨是哪一層

| 外網症狀 | 是哪一層 | 跳到 |
|---|---|---|
| 瀏覽器憑證警告頁 `ERR_TLS_CERT_ALTNAME_INVALID` | 第一層：跑到 443 / 憑證錯 | Step 2 |
| 「無法連上這個網站 / 無法找到指定主機」 | 第二層：DNS 沒發布 | Step 3 |
| 頁面開得了但登入/對話失敗 | 不是網路層 | 看 [SSE_TROUBLESHOOTING.md](SSE_TROUBLESHOOTING.md) |

### Step 2 — 修「憑證錯 / 跑到 443」

確認 funnel 在 8443、規則齊全；不對就跑 reset：

```powershell
"C:\Program Files\Tailscale\tailscale.exe" funnel status
# 不對的話：
powershell -ExecutionPolicy Bypass -File C:\Users\226376\Desktop\LangGraph_RAG_SYSTEM\reset-tailscale-routing.ps1
```

### Step 3 — 修「DNS 沒發布」（換機 / 重開機後最常見）

1. **以系統管理員**開 PowerShell，重啟服務：
   ```powershell
   Restart-Service Tailscale -Force
   ```
   （或 `services.msc` → Tailscale → 重新啟動。**不要去工作管理員硬殺 tailscaled，它是服務會自動重生。**）
2. 等 Tailscale 重新連上（10-20 秒）。
3. 若 funnel 掉了，重新掛回：
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Users\226376\Desktop\LangGraph_RAG_SYSTEM\reset-tailscale-routing.ps1
   ```
4. 等 2-3 分鐘，回 admin console 看 kccw0077 的 **Client Connectivity** 是否出現數值。
5. 用手機行動網路（或 `dns.google/resolve`）確認外網能解析、能開。

---

## COMODO 環境注意事項（重要）

這台機器在 COMODO EDR 控管下，**非互動 / 非提權的 shell 會被擋**：

- `pm2 restart frontend` 一般 terminal 會噴 `EPERM \\.\pipe\rpc.sock`。
  → **用系統管理員（UAC 提權）執行 [start-system.bat](start-system.bat)，pm2 就能用**。這是重啟前端的標準方式。
- `Restart-Service Tailscale` / 砍 tailscaled 程序，**非提權會 Access denied**。
  → 一律用**系統管理員 PowerShell** 或 `services.msc`。
- 後端（FastAPI :8000）必須在**前景 IDE terminal** 手動起（PM2 起的 python 被 COMODO 擋）：
  ```powershell
  cd C:\Users\226376\Desktop\LangGraph_RAG_SYSTEM\backend
  uv run python run_server.py
  ```
  該 terminal 不能關。

---

## 改 port 時要連動更新的地方（萬一以後 8443 也要換）

Tailscale Funnel 只能用 443 / 8443 / 10000。若要換 port，以下要一起改（不然前端打錯位址）：

1. funnel 指令（`--https=<port>`）：[reset-tailscale-routing.ps1](reset-tailscale-routing.ps1)、[start-system.bat](start-system.bat)
2. 前端 API 位址：[frontend/.env.local](frontend/.env.local) 的 `NEXT_PUBLIC_BACKEND_URL`
   → **改完必須重新 `yarn build` 並重啟前端**（這變數是 build 時烤進瀏覽器 bundle 的）
3. 文件裡的網址：本檔、[README.md](README.md)、[SSE_TROUBLESHOOTING.md](SSE_TROUBLESHOOTING.md)、各 `.bat`

---

## 相關檔案

- [reset-tailscale-routing.ps1](reset-tailscale-routing.ps1) — 一鍵重設 funnel（8443、/ 與 /api）
- [start-system.bat](start-system.bat) — 啟動系統（前端 pm2 + funnel；需 UAC 提權）
- [SSE_TROUBLESHOOTING.md](SSE_TROUBLESHOOTING.md) — SSE 串流逐字失效的排查（路由/proxy buffer 層）
- [frontend/.env.local](frontend/.env.local) — `NEXT_PUBLIC_BACKEND_URL`（要帶 `:8443`）
