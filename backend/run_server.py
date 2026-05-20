"""Entry point that forces SelectorEventLoop on Windows BEFORE uvicorn
creates its event loop.

Why this is needed:
    psycopg (used by langgraph-checkpoint-postgres) refuses to run on
    Windows' default ProactorEventLoop. We must use SelectorEventLoop.
    uvicorn.run() doesn't reliably honor `asyncio.set_event_loop_policy`
    on Windows in current versions, so we drive the server with our own
    `asyncio.run(server.serve())` after setting the policy — this gives
    us deterministic control over which loop runs.

PM2 launches this file (via ecosystem.config.js) instead of uvicorn
directly.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from uvicorn import Config, Server


def main() -> None:
    config = Config(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        loop="asyncio",   # use stdlib asyncio (respects our policy)
    )
    server = Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
