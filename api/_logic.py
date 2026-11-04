"""Request handling for the web runner, independent of the HTTP server (WEB-01..05).

`WebApp.handle` is a pure function of (method, path, headers, body): it returns a status
code and a JSON-able dict. The Vercel handler (api/run.py) and the local dev server
(scripts/serve_web.py) both delegate here, so tests exercise the exact production logic.

Security properties:
- every request needs the shared password in `x-app-password` (hmac.compare_digest);
  an unset APP_PASSWORD refuses everything (never open by default).
- the send stage ignores any recipient in the request; the pipeline mails OWNER_EMAIL only,
  and only when `confirm_send` is exactly boolean true (otherwise a dry-run preview).
- per-IP rate limits and a per-instance Hunter live-search budget bound credit usage.
- responses never contain secret values (redact()) or stack traces.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from pathlib import Path

STAGES = ("scrape", "extract", "qualify", "poc", "draft", "send")
MAX_BODY_BYTES = 4_000_000  # Vercel caps request bodies at 4.5 MB
MAX_REQ_PER_MIN = 10
MAX_RUNS_PER_HOUR = 30
DEFAULT_HUNTER_BUDGET = 10
ENV_NAMES = ("APP_PASSWORD", "GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY", "OWNER_EMAIL")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_BAD_TLDS = frozenset(
    {"local", "localhost", "internal", "lan", "home", "corp", "intranet", "test", "invalid", "arpa"}
)

NOT_CONFIGURED_MSG = (
    "The web runner is not configured. Set these environment variables on the host: "
    + ", ".join(ENV_NAMES)
    + " (optional: WEB_HUNTER_BUDGET, GEMINI_MODEL_SMART, GEMINI_MODEL_FAST, RESEND_FROM)."
)


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def validate_domain(raw: object) -> str:
    """Bare public hostname only. No scheme, path, port, credentials, IPs or private names."""
    if not isinstance(raw, str):
        raise RequestError(400, "bad_domain", "domain must be a string")
    value = raw.strip().lower().rstrip(".")
    if not value or len(value) > 253:
        raise RequestError(400, "bad_domain", "enter a company domain such as example.com")
    if any(ch in value for ch in "/\\?#@:%[] \t\r\n") or ".." in value:
        raise RequestError(400, "bad_domain", "enter a bare domain only (no scheme, path or port)")
    if value.startswith("www."):
        value = value[4:]
    labels = value.split(".")
    if len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
        raise RequestError(400, "bad_domain", "that does not look like a public domain name")
    if labels[-1].isdigit():
        raise RequestError(400, "bad_domain", "IP addresses are not allowed")
    if labels[-1] in _BAD_TLDS or labels[0] == "localhost":
        raise RequestError(400, "bad_domain", "private or local names are not allowed")
    return value


class RateLimiter:
    """In-memory sliding windows, best effort per serverless instance."""

    def __init__(self, per_min: int = MAX_REQ_PER_MIN, runs_per_hour: int = MAX_RUNS_PER_HOUR):
        self.per_min, self.runs_per_hour = per_min, runs_per_hour
        self._req: dict[str, deque] = defaultdict(deque)
        self._runs: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _trim(q: deque, now: float, window: float) -> None:
        while q and now - q[0] >= window:
            q.popleft()

    def check(self, ip: str, now: float, *, run_start: bool) -> str | None:
        with self._lock:
            req = self._req[ip]
            self._trim(req, now, 60)
            if len(req) >= self.per_min:
                return f"rate limit: at most {self.per_min} requests per minute"
            if run_start:
                runs = self._runs[ip]
                self._trim(runs, now, 3600)
                if len(runs) >= self.runs_per_hour:
                    return f"rate limit: at most {self.runs_per_hour} runs per hour"
                runs.append(now)
            req.append(now)
        return None


class WebApp:
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        run_stage: Callable | None = None,
        settings_factory: Callable | None = None,
        clock: Callable[[], float] = time.time,
        limiter: RateLimiter | None = None,
    ):
        self._env = env if env is not None else os.environ
        self._run_stage = run_stage
        self._settings_factory = settings_factory
        self._clock = clock
        self.limiter = limiter or RateLimiter()
        self._hunter_used = 0
        self._lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------------------
    def _hunter_budget(self) -> int:
        try:
            return max(0, int(self._env.get("WEB_HUNTER_BUDGET", DEFAULT_HUNTER_BUDGET)))
        except (TypeError, ValueError):
            return DEFAULT_HUNTER_BUDGET

    def _take_hunter(self) -> bool:
        with self._lock:
            if self._hunter_used >= self._hunter_budget():
                return False
            self._hunter_used += 1
            return True

    def hunter_remaining(self) -> int:
        return max(0, self._hunter_budget() - self._hunter_used)

    def _settings(self):
        if self._settings_factory is not None:
            return self._settings_factory()
        from outreach.config import ConfigError, load_settings

        data_dir = Path(self._env.get("OUTREACH_DATA_DIR") or "/tmp/outreach")
        try:
            settings = load_settings(env=self._env)
        except ConfigError as exc:
            raise RequestError(503, "not_configured", f"{exc} {NOT_CONFIGURED_MSG}") from None
        return settings.model_copy(
            update={"cache_dir": data_dir / "cache", "out_dir": data_dir / "out"}
        )

    def _stage_fn(self) -> Callable:
        if self._run_stage is not None:
            return self._run_stage
        try:
            from outreach.webapi import run_stage
        except ImportError:
            raise RequestError(
                503, "not_configured", "pipeline module outreach.webapi is not available"
            ) from None
        return run_stage

    def _redact(self, payload: dict, settings) -> dict:
        from outreach.config import redact

        secrets = [
            v for k, v in self._env.items() if k.endswith("_API_KEY") or k == "APP_PASSWORD"
        ]
        text = json.dumps(payload, default=str)
        text = redact(text, settings, secrets=secrets)
        return json.loads(text)

    # -- entry point -----------------------------------------------------------------------
    def handle(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes = b"",
        client_ip: str = "unknown",
    ) -> tuple[int, dict]:
        try:
            return self._handle(method, path, headers, body, client_ip)
        except RequestError as exc:
            return exc.status, {"error": exc.code, "message": exc.message}
        except Exception as exc:  # never leak a trace or a secret
            msg = type(exc).__name__
            try:
                from outreach.config import redact

                msg += ": " + redact(str(exc)[:300], None, secrets=self._secrets())
            except Exception:
                pass
            return 500, {"error": "internal", "message": msg}

    def _secrets(self) -> list[str]:
        return [v for k, v in self._env.items() if k.endswith("_API_KEY") or k == "APP_PASSWORD"]

    def _handle(self, method, path, headers, body, client_ip):
        h = {k.lower(): v for k, v in headers.items()}
        expected = self._env.get("APP_PASSWORD") or ""
        if not expected:
            return 503, {"error": "not_configured", "message": NOT_CONFIGURED_MSG}
        wait = self.limiter.check(
            client_ip, self._clock(), run_start=False
        )
        if wait:
            return 429, {"error": "rate_limited", "message": wait}
        supplied = h.get("x-app-password", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return 401, {"error": "unauthorized", "message": "wrong or missing password"}

        route = path.split("?", 1)[0].rstrip("/")
        if route == "/api/health" and method == "GET":
            return 200, {
                "ok": True,
                "configured": {n: bool(self._env.get(n)) for n in ENV_NAMES},
                "hunter_budget_remaining": self.hunter_remaining(),
            }
        if route == "/api/run" and method == "POST":
            return self._run(body, client_ip)
        raise RequestError(404 if route.startswith("/api") else 400, "not_found", "unknown route")

    def _run(self, body: bytes, client_ip: str) -> tuple[int, dict]:
        if len(body) > MAX_BODY_BYTES:
            raise RequestError(400, "too_large", "request body too large")
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            raise RequestError(400, "bad_json", "body must be JSON") from None
        if not isinstance(req, dict):
            raise RequestError(400, "bad_json", "body must be a JSON object")
        stage = req.get("stage")
        if stage not in STAGES:
            raise RequestError(400, "bad_stage", f"stage must be one of {', '.join(STAGES)}")
        domain = validate_domain(req.get("domain"))
        state = req.get("state") or {}
        if not isinstance(state, dict):
            raise RequestError(400, "bad_state", "state must be a JSON object")

        if stage == "scrape":  # a run start counts against the hourly ceiling
            wait = self.limiter.check(client_ip, self._clock(), run_start=True)
            if wait:
                return 429, {"error": "rate_limited", "message": wait}

        stage_fn = self._stage_fn()
        settings = self._settings()
        send = stage == "send" and req.get("confirm_send") is True
        live_hunter = stage == "poc" and self._take_hunter()
        state = {**state, "domain": domain}  # the validated domain always wins
        result = stage_fn(stage, state, settings=settings, send=send, live_hunter=live_hunter)
        if not isinstance(result, dict):
            raise RequestError(500, "internal", "pipeline returned an unexpected value")
        out = dict(result)
        out.setdefault("stage", stage)
        out["live_send"] = send
        out["owner_email"] = getattr(settings, "owner_email", "")
        out["hunter_budget_remaining"] = self.hunter_remaining()
        return 200, self._redact(out, settings)
