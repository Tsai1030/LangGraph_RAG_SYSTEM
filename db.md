# SQLite → PostgreSQL 遷移計畫書

> 撰寫時間：2026-05-19
> 目標機器：Windows 11，PM2 + uv + uvicorn + Next.js
> 對應分支：`feat/tailscale-funnel-expose` → `feat/postgres-migration`（commit `c94337d` 是遷移前的最後快照）

## ⚙️ 執行狀態（2026-05-20 更新）

**🎉 MIGRATION COMPLETE** — 已成功遷移、生產運作中。

- ✅ PG 13.23 安裝 + 3 個 database 建立完成（`kb_app` / `kb_search` / `kb_langgraph`）
- ✅ Schema migration 全跑過（修一個 cross-dialect bug：`sa.text('0')` → `sa.false()`）
- ✅ Data 搬遷成功且 counts 100% 對齊：14 users / 54 conv / 325 msg / 41 generation_runs / 70 price_history / 26 csc_price_state / 2 csc_meta
- ✅ 端到端驗證（透過瀏覽器發訊息，PG 即時寫入 325 → 327）
- ⚠️ 過程中踩到 3 個踩雷（見下方 §8 「Post-migration 觀察」）

完成於 commit `24baf59`（feat/postgres-migration）。SQLite 三個 .db 檔保留在原位作為 rollback 保險。

---

## 0. TL;DR

**為什麼遷移**：目前看到的「重啟後 API 看到舊版 DB / 磁碟與 API 不一致」是 SQLite 在 Windows + 多 process 環境的固有問題（PM2 殺不乾淨子進程 + Windows WAL 鎖殘留），治標反覆無效。PostgreSQL 從架構面消除這類問題。

**做什麼**：把 3 個 SQLite 檔案搬到 1 個 PostgreSQL server：
- `backend/app.db` → PG database `kb_app`（users / conversations / messages）
- `backend/search.db` → PG database `kb_search`（price_history / generation_runs / csc_*）
- `backend/langgraph.db` → PG database `kb_langgraph`（LangGraph checkpointer state，**不搬資料，重新開始**）

**預估時程**：半天到一天（含安裝、code 改、資料搬、驗證）。

**停機窗口**：~30 分鐘（資料搬遷期間）。中途可隨時 rollback 回 SQLite。

---

## 1. 為什麼遷移可以根本解決問題

### 1.1 目前的痛點

| 現象 | 觀察 | 原因 |
|---|---|---|
| 磁碟 `app.db` 顯示 325 messages | 直接 sqlite3 開檔 | 對的 |
| Backend API 回 238 messages | 透過 `/api/admin/stats` | 開到「舊版」 |
| pm2 restart 後常態發生 | 第一次 boot 後 OK，restart 後變差 | PM2 殺不乾淨子進程 |
| 重開機可解 | OS 強制收回所有 FD | 證實是 process 級問題 |

### 1.2 為什麼 SQLite 在這環境會壞

#### A. PM2 在 Windows 上殺不乾淨 child process
- 你的進程鏈：**PM2 → `uv.exe` → `python.exe` → uvicorn**
- PM2 只用 `TerminateProcess(uv.exe)`，**不會** propagate 到 grandchildren
- `python.exe` 變孤兒、繼續活著、握著 DB 的 file handle
- 參考：[PM2 Issue #6084 — pm2 stop/delete does not kill child worker processes](https://github.com/Unitech/pm2/issues/6084)

#### B. SQLite WAL 在 Windows 上會留下 file lock
- 沒乾淨關閉的連線會留 `-wal`/`-shm`，且 Windows 的 file lock 在 close() 後不會立刻釋放
- 不同 process 同時開同一個 DB 時，可能看到不同的 mxFrame snapshot
- 參考：[Bun Issue #25964 — SQLite database file locked on Windows after close() with WAL mode](https://github.com/oven-sh/bun/issues/25964)
- 參考：[SQLite docs — WAL-mode File Format](https://sqlite.org/walformat.html)

#### C. 兩個問題疊在一起的結果
- 孤兒 python 進程握著舊 mxFrame 的 SQLite 連線
- 新 backend 進程拿到新 mxFrame
- frontend 打 :8000 不一定能保證打到「新」的那個
- 「重啟後看到不同版本」就是這樣

### 1.3 PostgreSQL 為什麼一勞永逸

```
SQLite（你現在）                          PostgreSQL
─────────────────────                  ─────────────────────────
backend ⇄ app.db 檔案                   backend ⇄ TCP ⇄ postgres.exe（背景常駐 server）
                                                          ↓
                                                        PG 自己的資料檔（你不會碰）

- backend 自己 hold FD                  - backend 只 hold TCP 連線
- restart 後 FD 殘留 → 競爭             - restart 後 TCP 斷掉 → 重連就好
- 孤兒進程 = 孤兒 FD                    - 孤兒進程 TCP 連線被 PG 踢掉就完了
- Windows file lock 問題                - 不存在（你的 app 不開檔）
```

**就算 PM2 不殺乾淨子進程，那些孤兒進程的 TCP 連線會被 PG 拒絕／關閉，影響 0。**

---

## 2. 現況盤點

### 2.1 三個 SQLite DB

| 檔 | 用途 | 大小 | 是否遷移資料 | 工具 |
|---|---|---|---|---|
| `backend/app.db` | users / conversations / messages | 839 KB | **要** | Alembic + 自製 Python script |
| `backend/search.db` | price_history / generation_runs / csc_* | 348 KB | **要** | `metadata.create_all` + 自製 Python script |
| `backend/langgraph.db` | LangGraph checkpointer 狀態 | 89 MB | **否（重新開始）** | `AsyncPostgresSaver.setup()` |

### 2.2 程式碼相關位置

| 檔案 | 改動類型 |
|---|---|
| `backend/app/database.py` | 改 driver / 移除 WAL pragma |
| `backend/app/search_database.py` | 同上 |
| `backend/app/main.py` | `AsyncSqliteSaver` → `AsyncPostgresSaver` |
| `backend/app/config.py` | 加 PG 連線設定 |
| `.env` | `DATABASE_URL`、`SEARCH_DB_PATH`、`LANGGRAPH_DB_PATH` 全改 |
| `backend/pyproject.toml` | 加 `asyncpg`、`langgraph-checkpoint-postgres` |
| `backend/alembic/versions/*.py` | 大多不用改（已用 SQLAlchemy 型別），確認 `batch_alter_table` 在 PG 下也能跑（會自動退化成普通 ALTER） |
| `start-system.bat` | 加「等 PG service 起來」一步 |

### 2.3 Alembic 現況
4 個 migration，最新版本 `6cd7a4c2bf6f`。前 3 個用 `batch_alter_table`（SQLite-specific recreate-table workaround），最新一個改成直接 `ADD COLUMN`。**PG 兼容性**：
- `batch_alter_table` 在 PG 上會直接呼叫 `ALTER TABLE`（alembic 自動退化），**不會有問題**
- 唯一風險：constraint 命名。SQLAlchemy 自動生成的名稱在 SQLite 上可以超過 63 char 但 PG 不行。你的 schema 都是短欄位、應該沒事，但要 dry-run 驗證

### 2.4 LangGraph Checkpointer
- 目前：`from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver`
- PG 替換：`from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`
- 需要新增 pip 套件：`langgraph-checkpoint-postgres`（目前**未安裝**，已查過）

---

## 3. 完整 Step List

### Phase 1：環境準備（~1 小時）

#### Step 1.1 — Commit & branch
```powershell
cd C:\Users\226376\Desktop\data
git status   # 應該乾淨（c94337d 之後沒新改）
git checkout -b feat/postgres-migration
```
**驗證**：`git branch --show-current` 顯示 `feat/postgres-migration`。

#### Step 1.2 — 安裝 PostgreSQL（Windows native）

> ✅ **已完成（2026-05-19 確認）**：你的機器已裝 PG 13、Windows service `postgresql-x64-13` 在跑。可以**直接跳到 Step 1.3**。
> 下面內容只當參考、或之後別台機器要裝時的指引。

1. 下載 EDB 安裝包：<https://www.enterprisedb.com/downloads/postgres-postgresql-downloads>
   - 選 **PostgreSQL 13.x Windows x86-64**（你目前已安裝這個版本）
2. 安裝（管理員執行）：
   - **Installation Directory**：預設 `C:\Program Files\PostgreSQL\13`
   - **Data Directory**：預設 `C:\Program Files\PostgreSQL\13\data`
   - **Password**（superuser `postgres` 的密碼）：**自己挑一個，記下來**（這個密碼會寫進 `.env`）
   - **Port**：`5432`（預設）
   - **Locale**：`Default locale`
   - **Stack Builder**：取消勾選（不需要）
3. 安裝完，會自動建立 Windows Service `postgresql-x64-13`，預設**自動啟動**

**驗證**（如果你不確定密碼還記不記得，這條會逼你回想或重設）：
```powershell
Get-Service postgresql-x64-13   # Status = Running   ← 你這邊已經 Running
& "C:\Program Files\PostgreSQL\13\bin\psql.exe" -U postgres -h 127.0.0.1 -c "select version();"
# 輸入安裝時設定的密碼，看到 PostgreSQL 13.x ... 字樣
```

> 💡 **如果你忘記 superuser `postgres` 的密碼**：
> 1. 開「服務」→ 停 `postgresql-x64-13`
> 2. 編輯 `C:\Program Files\PostgreSQL\13\data\pg_hba.conf`，把 `host all all 127.0.0.1/32 scram-sha-256` 暫時改成 `trust`
> 3. 起 service → `psql -U postgres -c "alter user postgres with password '新密碼';"` → 改回 `scram-sha-256` → 重啟 service

#### Step 1.3 — 建 3 個 database 與 1 個 app user
```powershell
$env:PGPASSWORD = "你剛剛設的 superuser 密碼"
$psql = "C:\Program Files\PostgreSQL\13\bin\psql.exe"

# 建 app user
& $psql -U postgres -h 127.0.0.1 -c "create user kb_user with password 'kb_strong_password_change_me';"

# 建 3 個 database
& $psql -U postgres -h 127.0.0.1 -c "create database kb_app owner kb_user;"
& $psql -U postgres -h 127.0.0.1 -c "create database kb_search owner kb_user;"
& $psql -U postgres -h 127.0.0.1 -c "create database kb_langgraph owner kb_user;"

# 驗證
& $psql -U postgres -h 127.0.0.1 -c "\l"
```
**驗證**：`\l` 列表裡看到 `kb_app`、`kb_search`、`kb_langgraph`。

#### Step 1.4 — Python 套件
```powershell
cd C:\Users\226376\Desktop\data\backend
uv add asyncpg psycopg2-binary "langgraph-checkpoint-postgres"
# psycopg2-binary 是 alembic / sync 用的；asyncpg 是 runtime async 用
```
**驗證**：`.venv\Scripts\python.exe -c "import asyncpg, psycopg2, langgraph.checkpoint.postgres"` 不報錯。

---

### Phase 2：Schema 重建（Dry-run，~1.5 小時）

> 這個 phase **不動** SQLite 資料，只在 PG 上把 schema 建好驗證。萬一有錯可以反覆 drop database / 重建。

#### Step 2.1 — `.env` 加新變數（**先別覆寫舊的**）
```env
# 既有的，保留：
DATABASE_URL=sqlite+aiosqlite:///./app.db
SYNC_DATABASE_URL=sqlite:///./app.db
SEARCH_DB_PATH=./search.db
LANGGRAPH_DB_PATH=./langgraph.db

# 新增（先註解掉，準備好但不啟用）：
# PG_DATABASE_URL=postgresql+asyncpg://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_app
# PG_SYNC_DATABASE_URL=postgresql+psycopg2://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_app
# PG_SEARCH_DATABASE_URL=postgresql+asyncpg://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_search
# PG_LANGGRAPH_URL=postgresql://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_langgraph
```

#### Step 2.2 — Alembic dry-run（驗證 migration 在 PG 上能跑）
```powershell
# 暫時把 alembic 指向 PG 跑一次 upgrade
$env:DATABASE_URL = "postgresql+psycopg2://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_app"
$env:SYNC_DATABASE_URL = $env:DATABASE_URL
cd backend
uv run alembic upgrade head
```
**驗證**：
```powershell
& $psql -U kb_user -h 127.0.0.1 -d kb_app -c "\dt"
# 應該看到 users / conversations / messages / conversation_summaries / alembic_version
& $psql -U kb_user -h 127.0.0.1 -d kb_app -c "select count(*) from users;"
# 應該是 0
```

**遇到錯誤怎麼辦**（已知可能踩到的雷）：
- `IDENTIFIER_TOO_LONG`：某個 constraint 名稱超過 63 char → 找到那條 migration 手動改短
- `cannot drop column with index`：PG 嚴格，要先 drop index 再 drop column → 補上
- 任何錯誤 → drop database 重建、修 migration、重試。直到 clean upgrade。

#### Step 2.3 — `search.db` schema 在 PG 上重建
Search 沒用 alembic，是 `SearchBase.metadata.create_all`。寫個小腳本：
```python
# backend/scripts/init_search_pg.py
import asyncio, os
os.environ["SEARCH_ASYNC_DATABASE_URL"] = "postgresql+asyncpg://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_search"
from app.search_database import search_engine, SearchBase
import app.modules.search.storage.models  # populate metadata

async def go():
    async with search_engine.begin() as conn:
        await conn.run_sync(SearchBase.metadata.create_all)
asyncio.run(go())
print("OK")
```
（**注意**：要先改 `search_database.py` 讓它能讀新 env 變數——下一步做）

#### Step 2.4 — 修改 `database.py` / `search_database.py` 支援 PG
**目標**：移除 WAL pragma（PG 不需要）；保留 SQLite/PG 共用的 SQLAlchemy 設定。

`backend/app/database.py`：
```python
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    connect_args=connect_args,
    pool_pre_ping=True,        # PG 連線健康檢查
    pool_recycle=3600,          # 1 小時 recycle 一次
)

# WAL pragma 只在 SQLite 時開，PG 完全略過
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_conn, _):
    if "sqlite" in settings.database_url:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```
`backend/app/search_database.py` 同樣處理。

---

### Phase 3：資料搬遷（~1 小時）

> ⚠️ **這個 phase 開始之前**：執行 `enter-maintenance.bat`。它會：
>   1. `pm2 stop frontend` + `pm2 stop backend`
>   2. 在 :3000 起一個 Python HTTP server 服務 `maintenance.html`（任何 URL 都回 HTTP 503 + 維護中頁面）
>
> 使用者在 `https://kccw0077.tail138ec9.ts.net:8443/` 會看到友善的「系統維護中」頁面而不是 502 錯誤。
>
> Phase 4 切換完成後，**關掉 `Maintenance Server` 視窗（Ctrl+C）→ 跑 `exit-maintenance.bat`** 就會恢復正常服務。

#### Step 3.1 — 寫資料搬遷腳本
建 `backend/scripts/migrate_sqlite_to_pg.py`：
```python
"""One-shot SQLite → PG data migration."""
from sqlalchemy import create_engine, MetaData

PAIRS = [
    ("sqlite:///./app.db",     "postgresql+psycopg2://kb_user:PWD@127.0.0.1:5432/kb_app"),
    ("sqlite:///./search.db",  "postgresql+psycopg2://kb_user:PWD@127.0.0.1:5432/kb_search"),
]

for src_url, dst_url in PAIRS:
    src = create_engine(src_url)
    dst = create_engine(dst_url)
    md = MetaData()
    md.reflect(bind=src)

    print(f"\n=== {src_url} → {dst_url} ===")
    with src.connect() as s, dst.begin() as d:
        for tbl in md.sorted_tables:
            rows = list(s.execute(tbl.select()).mappings())
            if not rows:
                print(f"  {tbl.name}: 0 rows")
                continue
            d.execute(tbl.insert(), [dict(r) for r in rows])
            print(f"  {tbl.name}: {len(rows)} rows")
    print("OK")
```

**注意**：
- 不搬 `langgraph.db`（重新開始）
- `alembic_version` 表會被一起搬，這樣 PG 端 alembic 認得目前版本
- SQLite 的 `BOOLEAN`（0/1）到 PG 的 `BOOLEAN`（true/false）→ SQLAlchemy ORM 自動處理
- `DATETIME` 字串到 PG `TIMESTAMP` → 同上

#### Step 3.2 — 執行搬遷
```powershell
cd backend
uv run python scripts/migrate_sqlite_to_pg.py
```
**驗證**：
```powershell
& $psql -U kb_user -h 127.0.0.1 -d kb_app -c "select count(*) from users;"           # 應該 14
& $psql -U kb_user -h 127.0.0.1 -d kb_app -c "select count(*) from conversations;"   # 應該 53~54
& $psql -U kb_user -h 127.0.0.1 -d kb_app -c "select count(*) from messages;"        # 應該 323~325
& $psql -U kb_user -h 127.0.0.1 -d kb_search -c "select count(*) from generation_runs;"  # 應該 40~41
```
比對你磁碟 SQLite 的數字。**完全一致才繼續**。

---

### Phase 4：切換到 PG（~30 分鐘）

#### Step 4.1 — 換 `.env`
把 SQLite 那 3 條註解掉，PG 那 4 條取消註解：
```env
DATABASE_URL=postgresql+asyncpg://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_app
SYNC_DATABASE_URL=postgresql+psycopg2://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_app
SEARCH_ASYNC_DATABASE_URL=postgresql+asyncpg://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_search
LANGGRAPH_DB_URL=postgresql://kb_user:kb_strong_password_change_me@127.0.0.1:5432/kb_langgraph
# 舊的 SQLite-only 變數可留可註解
# SEARCH_DB_PATH=./search.db
# LANGGRAPH_DB_PATH=./langgraph.db
```

#### Step 4.2 — 改 `config.py` 讀新變數
`backend/app/config.py` 加：
```python
search_async_database_url: str | None = None  # 改成可從 env 直接覆寫
langgraph_db_url: str | None = None

@property
def search_async_database_url_resolved(self) -> str:
    if self.search_async_database_url:
        return self.search_async_database_url
    # fallback: SQLite path（向後相容）
    path = self.search_db_path.lstrip("./").lstrip(".\\")
    return f"sqlite+aiosqlite:///{path}"
```

#### Step 4.3 — 改 `main.py` 的 langgraph checkpointer
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

@asynccontextmanager
async def lifespan(app: FastAPI):
    pg_url = settings.langgraph_db_url
    if pg_url:
        async with AsyncPostgresSaver.from_conn_string(pg_url) as checkpointer:
            await checkpointer.setup()
            app.state.graph = build_graph(checkpointer=checkpointer)
            app.state.checkpointer = checkpointer
            # ... rest of lifespan
            yield
    else:
        # 既有 SQLite 路徑保留作 fallback
        async with aiosqlite.connect(settings.langgraph_db_path) as conn:
            # ... 原本的 code
```

#### Step 4.4 — 啟動 + 端到端測試
```powershell
pm2 start backend
pm2 logs backend --lines 30 --nostream
# 應該看到 [Startup] DATABASE_URL=postgresql+asyncpg://...
# 應該看到 LangGraph checkpointer 連到 PG 成功

# 端到端
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/admin/stats -H "Authorization: Bearer <token>"
```
打開瀏覽器 `https://kccw0077.tail138ec9.ts.net:8443/`，登入、看一筆對話、發新訊息。

---

### Phase 5：穩定性驗證（~30 分鐘）

#### Step 5.1 — 反覆 pm2 restart
```powershell
for ($i=1; $i -le 5; $i++) {
    pm2 restart backend
    Start-Sleep -Seconds 5
    curl http://127.0.0.1:8000/api/admin/stats -H "Authorization: Bearer <token>"
    Write-Host "iteration $i ok"
}
```
**驗證**：每次都顯示同樣的 user/conv/msg count（就是 PG 裡的真實值）。**如果這個成立 → 原始問題徹底解決**。

#### Step 5.2 — `start-system.bat` 加等 PG service 起來
```bat
REM 在 PM2 啟動 backend 之前
echo [0/4] Waiting for PostgreSQL service...
powershell -NoProfile -Command "$d=(Get-Date).AddSeconds(30); while ((Get-Service postgresql-x64-13).Status -ne 'Running' -and (Get-Date) -lt $d) { Start-Service postgresql-x64-13 -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }"
```

#### Step 5.3 — Commit
```powershell
git add backend/app/database.py backend/app/search_database.py backend/app/main.py backend/app/config.py backend/pyproject.toml backend/uv.lock backend/scripts/migrate_sqlite_to_pg.py backend/scripts/init_search_pg.py start-system.bat
git add .env  # 注意密碼是否要 commit；如果 repo 是私倉、密碼是「測試用」可以 commit；否則用 .env.example 範本
git commit -m "feat(db): migrate from SQLite to PostgreSQL"
```

---

## 4. Rollback 計畫

**任何時間出問題**，最差也只要 1 分鐘可以退回 SQLite：

1. `.env` 把 SQLite 3 行解註解、PG 4 行註解掉
2. `pm2 restart backend`
3. 確認 backend 起來、API 正常
4. SQLite DB 檔 (`backend/app.db` 等) 從頭到尾沒被動過，資料零損失

**PG database 怎麼處理**：
- 隨它放著（不刪），下次再嘗試遷移可以直接 reuse
- 或 `drop database kb_app; create database kb_app owner kb_user;` 重來

---

## 5. 風險清單

| 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|
| Alembic migration 在 PG 跑不過（constraint 名稱、batch_alter_table 問題） | 中 | 高 | Phase 2 Dry-run 階段就會抓到；修 migration 或加 `naming_convention` 設定 |
| 資料搬遷 type 轉換錯（BOOLEAN、DATETIME） | 低 | 中 | SQLAlchemy ORM-based 搬遷自動處理；逐表驗證 count |
| Langgraph checkpointer API 換了某個介面 | 低 | 中 | 套件版本鎖死、保留 SQLite fallback |
| PG service 沒自動啟動 | 低 | 低 | `start-system.bat` 加 `Start-Service` |
| asyncpg / psycopg2 在 Windows 上裝不起來 | 很低 | 低 | binary wheel 早就有，`uv add` 直接成功 |
| 密碼被誤 commit 到 public repo | **重要** | 高 | 你確認是 private repo（先前已確認）；或改用 `.env.example` |

---

## 6. 完工後可順手做（不在主流程裡）

- [ ] 移掉 `Caddy` 相關殘留檔（你已經不用了）
- [ ] 把 `langgraph.db` 89 MB 從 git 移除（用 `git rm --cached` 然後 .gitignore）
- [ ] `pgAdmin 4`（PG 安裝包附帶）裝起來，當作 PG 的 GUI 管理工具
- [ ] PG 設定 `pg_hba.conf` 確認只接受 `127.0.0.1` 連線（不開外網）

---

## 7. 決策點

開始前確認：
- [ ] 安裝 PG 的密碼想好沒
- [ ] 計畫時段（**約半天到一天**，中間有 30 分鐘左右系統不能用）
- [ ] 如果遇到 alembic 跑不過、要不要當下花時間修還是先退回 SQLite

如果都 ✓，按 Step 1.1 開始。

---

## 8. Post-migration 觀察（實際執行中踩到的雷）

> 這節是「執行完才知道」的部分，給未來重做或維護的人參考。

### 8.1 Alembic `server_default=sa.text('0')` 在 PG 上炸

第 4 個 migration（`6cd7a4c2bf6f_add_search_enabled_to_users.py`）的：
```python
sa.Column('search_enabled', sa.Boolean(), server_default=sa.text('0'))
```
SQLite 接受字面 `0` 當 BOOLEAN DEFAULT；PG 嚴格區分型別、會丟：
```
DatatypeMismatch: column "search_enabled" is of type boolean
                  but default expression is of type integer
```

**修法**：`sa.text('0')` → `sa.false()`，SQLAlchemy 會 emit dialect-appropriate boolean literal。已 commit。

### 8.2 `alembic/env.py` 的 PRAGMA 在 PG 會炸

`set_pragmas` listener 對所有 connect event 跑 `PRAGMA journal_mode=WAL`。PG 沒 PRAGMA 語法、報錯。

**修法**：listener 改成只在 SQLite URL 下註冊（已 commit）。

### 8.3 `config.py` 的 `@property` 不會吃 env 變數

最初的 `search_async_database_url` 是 `@property`，硬寫 `sqlite+aiosqlite://`。我曾用 `os.environ.get(...)` 試圖在 property 內動態覆寫——**沒用**，因為 pydantic-settings 把 .env 灌進 Settings 物件，不會塞回 `os.environ`。

**修法**：改用真正的 Field（`search_database_url: str | None = None`），property 變成「先查 Field 再 fallback 到 SQLite path」。已 commit。

### 8.4 Windows + psycopg + asyncio：ProactorEventLoop 不相容

`langgraph-checkpoint-postgres` 底下用 psycopg v3。psycopg 在 Windows 的 default `ProactorEventLoop` 上**直接 refuse**：
```
psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode
```

**修法**：把 event loop policy 切成 `WindowsSelectorEventLoopPolicy`。但**不能只在 main.py 頂端設**——uvicorn 在 import `app.main` 之前就已經建好 ProactorEventLoop 了。

正確作法：寫一個 `run_server.py` entrypoint，**先設 policy 再 import uvicorn 並用 asyncio.run(server.serve())**：

```python
# backend/run_server.py
import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from uvicorn import Config, Server
def main():
    config = Config("app.main:app", host="0.0.0.0", port=8000, loop="asyncio")
    asyncio.run(Server(config).serve())
if __name__ == "__main__":
    main()
```

然後 PM2/啟動腳本改成 `uv run python run_server.py`，**不要**直接 `uv run uvicorn app.main:app`。已 commit。

### 8.5 ⚠️ COMODO EDR 擋 PM2-spawned python → :5432

**最大踩雷**。PM2 啟動 backend 時，python → PG 連線 **間歇性**失敗於：
```
psycopg.OperationalError: connection failed: could not connect to server:
  Permission denied (0x0000271D/10013)
   Is the server running on host "127.0.0.1" and accepting TCP/IP on port 5432?
```

`0x271D = WSAEACCES (10013)`。同樣的 Windows ACL，跟之前 Caddy → Node 是同一回事。

**差異點**：foreground 跑 `uv run python run_server.py` 正常；PM2 spawn 同一支腳本就被擋。原因是 **COMODO 基於父進程鏈做信任決策**：
- Foreground：`cmd.exe (user session) → uv.exe → python.exe` → ✅ 放行
- PM2：`pm2 node daemon → cmd.exe → uv.exe → python.exe` → ❌ 拒絕

**已試過的修法**：
1. ❌ COMODO Application Rules 手動加 python.exe 為 Trusted — **時好時壞**，不穩定
2. ❌ PM2 改用 .venv python 直接 spawn（繞 uv）— 一樣被擋
3. ✅ **採用：backend 用 foreground cmd 視窗跑**（`start-backend.bat`），PM2 只管 frontend

`start-system.bat` / `exit-maintenance.bat` 都已調整成這個模式。

> 長遠來看若想徹底解，可考慮：
> - NSSM 包成 Windows Service（不同信任 context）
> - 把 COMODO 改成不基於父進程鏈，或關閉 EDR 模組
> - 換另一台沒 COMODO 的機器
> 但這些都不是當下優先。

### 8.6 .bat 檔不要用 Unicode box-drawing 字元

第一版 `start-backend.bat` 用了 `─` (U+2500) 當分隔線，cmd 預設 codepage 950 (Big5) 讀到亂碼、把 REM 行當指令執行、`@echo off` 失效。**bat 檔請保持純 ASCII**（用 `===`、`---`、`***` 等）。已修。

---

## Appendix A：給 Claude / 其他 AI 助理的 Hint

若這份計畫由 AI agent 執行：
- 嚴格按照 Phase 順序，每完成一個 Step 都要跑驗證指令、回報結果再進下一步
- 任何 Phase 出錯，先停下來跟使用者討論，不要自己嘗試「修一修」往下衝
- Phase 3 開始前必須 `pm2 stop all`；做完 Phase 4 才 `pm2 start`
- 密碼 token 寫進 `.env` 前確認沒誤 push 到 GitHub
