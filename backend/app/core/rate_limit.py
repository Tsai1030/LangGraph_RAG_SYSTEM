"""
rate_limit.py — slowapi 共用 limiter，避免主程式 / route 之間的循環 import。

主程式 (main.py) 負責註冊 exception handler 和 SlowAPIMiddleware。
Route 模組 import `limiter` 並在端點上套 @limiter.limit("...") 裝飾器。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
