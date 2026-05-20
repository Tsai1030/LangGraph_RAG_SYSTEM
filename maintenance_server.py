"""Maintenance-page HTTP server.

Replies to EVERY request with maintenance.html + HTTP 503. Stand-in for
Next.js during DB migration when frontend/backend are both stopped.

Run from the project root:
    backend/.venv/Scripts/python.exe maintenance_server.py
Stop with Ctrl+C (or close the window).
"""
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 3000
HTML_PATH = Path(__file__).resolve().parent / "maintenance.html"

HTML_BYTES = HTML_PATH.read_bytes() if HTML_PATH.exists() else (
    b"<!doctype html><meta charset=utf-8><title>maintenance</title>"
    b"<p>System under maintenance.</p>"
)


class _Handler(BaseHTTPRequestHandler):
    def _serve(self) -> None:
        self.send_response(503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML_BYTES)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Retry-After", "60")
        self.end_headers()
        # HEAD requests still get headers but no body
        if self.command != "HEAD":
            self.wfile.write(HTML_BYTES)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _serve  # noqa: E305

    def log_message(self, fmt: str, *args: object) -> None:  # quiet
        pass


def main() -> None:
    print(f"[maintenance] serving {HTML_PATH.name} on 0.0.0.0:{PORT} (HTTP 503)")
    print("[maintenance] press Ctrl+C to stop")
    try:
        HTTPServer(("0.0.0.0", PORT), _Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[maintenance] stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
