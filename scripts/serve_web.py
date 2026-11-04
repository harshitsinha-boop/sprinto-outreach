"""Local dev server: serves web/index.html and routes /api/* to the production handler logic.

    .venv/bin/python scripts/serve_web.py --fake      # no keys, fake pipeline
    .venv/bin/python scripts/serve_web.py                             # real pipeline, keys from env

Binds to 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OUTREACH_DATA_DIR", str(ROOT / ".cache" / "webdev"))
for p in (str(ROOT / "api"), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _logic import MAX_BODY_BYTES, WebApp  # noqa: E402


def make_handler(app: WebApp):
    index = (ROOT / "web" / "index.html").read_bytes()

    class Dev(BaseHTTPRequestHandler):
        def _send(self, status: int, data: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _api(self, method: str) -> None:
            n = max(0, int(self.headers.get("content-length") or 0))
            body = self.rfile.read(min(n, MAX_BODY_BYTES + 1)) if n else b""
            status, payload = app.handle(
                method, self.path, dict(self.headers), body, self.client_address[0]
            )
            self._send(status, json.dumps(payload).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/"):
                return self._api("GET")
            if self.path in ("/", "/index.html"):
                return self._send(200, index, "text/html; charset=utf-8")
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if self.path.startswith("/api/"):
                return self._api("POST")
            self._send(404, b"not found", "text/plain")

        def log_message(self, *args) -> None:
            pass

    return Dev


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="use the built-in fake pipeline (no keys)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.fake:
        from _fake import fake_run_stage, fake_settings

        app = WebApp(dict(os.environ), run_stage=fake_run_stage, settings_factory=fake_settings)
        print("FAKE mode. " + ("Password from APP_PASSWORD." if os.environ.get("APP_PASSWORD") else "Open (no password)."))
    else:
        app = WebApp()
    print(f"http://127.0.0.1:{args.port}/")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app)).serve_forever()


if __name__ == "__main__":
    main()
