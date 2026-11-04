"""Vercel serverless function: POST /api/run runs ONE pipeline stage per request."""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Cache and out dirs must live on the only writable path; set before importing the package.
os.environ.setdefault("OUTREACH_DATA_DIR", "/tmp/outreach")
# Accept the shorter variable name for the Resend key as an alias.
if not os.environ.get("RESEND_API_KEY") and os.environ.get("RESEND_KEY"):
    os.environ["RESEND_API_KEY"] = os.environ["RESEND_KEY"]
_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(Path(__file__).resolve().parent), str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _logic import MAX_BODY_BYTES, WebApp  # noqa: E402

APP = WebApp()


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel requires this name
    def _serve(self, method: str) -> None:
        length = 0
        try:
            length = max(0, int(self.headers.get("content-length") or 0))
        except ValueError:
            pass
        body = self.rfile.read(min(length, MAX_BODY_BYTES + 1)) if length else b""
        fwd = (self.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        ip = fwd or self.headers.get("x-real-ip") or self.client_address[0]
        status, payload = APP.handle(method, self.path, dict(self.headers), body, ip)
        import json

        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def do_GET(self) -> None:  # noqa: N802
        self._serve("GET")

    def log_message(self, *args) -> None:  # never log request data
        pass
