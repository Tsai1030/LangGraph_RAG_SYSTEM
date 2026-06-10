"""驗證 user_or_ip_key：有 Bearer token → user:<sub>；無/壞 token → IP fallback。

用法：uv run python scripts/test_rate_limit_key.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jose import jwt
from starlette.requests import Request

from app.core.rate_limit import user_or_ip_key


def make_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat/stream",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("203.0.113.7", 12345),
        "query_string": b"",
    }
    return Request(scope)


# 合法 token（簽章 key 隨便 — key func 不驗簽）
token = jwt.encode({"sub": "user-uuid-123"}, "whatever", algorithm="HS256")
r = make_request({"Authorization": f"Bearer {token}"})
key = user_or_ip_key(r)
print("with token ->", key)
assert key == "user:user-uuid-123"

# 無 token → IP
r = make_request({})
key = user_or_ip_key(r)
print("no token   ->", key)
assert key == "203.0.113.7"

# 壞 token → IP fallback
r = make_request({"Authorization": "Bearer not.a.jwt"})
key = user_or_ip_key(r)
print("bad token  ->", key)
assert key == "203.0.113.7"

# token 無 sub → IP fallback
token_nosub = jwt.encode({"foo": "bar"}, "whatever", algorithm="HS256")
r = make_request({"Authorization": f"Bearer {token_nosub}"})
key = user_or_ip_key(r)
print("no sub     ->", key)
assert key == "203.0.113.7"

print("ALL PASS")
