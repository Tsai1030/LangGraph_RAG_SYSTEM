import pytest

# 讓所有 async test 自動使用 asyncio
pytest_plugins = ("pytest_asyncio",)
