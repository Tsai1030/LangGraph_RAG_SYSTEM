"""
rate_limit.py — slowapi 共用 limiter，避免主程式 / route 之間的循環 import。

主程式 (main.py) 負責註冊 exception handler 和 SlowAPIMiddleware。
Route 模組 import `limiter` 並在端點上套 @limiter.limit("...") 裝飾器。

兩種 key：
- 預設 get_remote_address（per-IP）— auth 端點用（未登入請求）。
- user_or_ip_key（per-user）— 已認證的 LLM 端點用。經 Tailscale Funnel
  反向代理時所有外部請求的 remote IP 是同一個 proxy 位址，per-IP 會把
  所有外部使用者算進同一個 bucket，必須改以 JWT 身分分流。
"""
from fastapi import Request
from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def user_or_ip_key(request: Request) -> str:
    """已登入請求以 JWT sub 為 limit key；無 token / 解析失敗回退 IP。

    刻意不驗簽（get_unverified_claims）：key 只做分流，偽造 sub 的攻擊者
    只是換進新 bucket，之後仍會被端點的 get_current_user 以 401 擋下；
    在 key func 完整驗簽會讓每個請求做兩次 JWT 驗證，得不償失。
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            sub = jwt.get_unverified_claims(auth[7:]).get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    return get_remote_address(request)
