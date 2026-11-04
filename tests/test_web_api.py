"""Offline tests for the web runner (WEB-01..05). No keys, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import _fake  # noqa: E402
from _fake import fake_run_stage, fake_settings  # noqa: E402

_fake.DELAY = 0
from _logic import STAGES, RateLimiter, RequestError, WebApp, validate_domain  # noqa: E402

PW = "correct-horse-battery"
CANARY = "canary-gem-0001x"


def make_app(env_extra=None, run_stage=fake_run_stage, **kw):
    env = {"APP_PASSWORD": PW, "GEMINI_API_KEY": CANARY, "OWNER_EMAIL": "owner@example.com"}
    env.update(env_extra or {})
    return WebApp(env, run_stage=run_stage, settings_factory=fake_settings, **kw)


def post(app, body, pw=PW, ip="1.2.3.4"):
    headers = {"x-app-password": pw} if pw is not None else {}
    return app.handle("POST", "/api/run", headers, json.dumps(body).encode(), ip)


def test_password_enforced_when_set():
    app = make_app()
    assert post(app, {"stage": "scrape", "domain": "acme.com"}, pw=None)[0] == 401
    assert post(app, {"stage": "scrape", "domain": "acme.com"}, pw="wrong")[0] == 401
    assert post(app, {"stage": "scrape", "domain": "acme.com"})[0] == 200


def test_open_mode_without_password():
    app = make_app({"APP_PASSWORD": ""})
    for pw in (None, "", "anything"):
        assert post(app, {"stage": "scrape", "domain": "acme.com"}, pw=pw)[0] == 200


def test_503_only_when_keys_missing_and_names_only_keys():
    app = WebApp({}, run_stage=fake_run_stage)  # open mode, no keys
    status, body = post(app, {"stage": "scrape", "domain": "acme.com"}, pw=None)
    assert status == 503 and body["error"] == "not_configured"
    assert "GEMINI_API_KEY" in body["message"] and "APP_PASSWORD" not in body["message"]
    keys = {k: "canary-%s-xxxx" % k for k in
            ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY", "OWNER_EMAIL")}
    app = WebApp(keys, run_stage=fake_run_stage)
    assert app.configured() is True


def test_health_is_public_and_leaks_nothing():
    app = make_app()
    status, out = app.handle("GET", "/api/health", {}, b"", "1")
    assert status == 200 and set(out) == {"ok", "configured", "auth_required"}
    assert out["auth_required"] is True and isinstance(out["configured"], bool)
    blob = json.dumps(out)
    assert CANARY not in blob and PW not in blob
    status, out = WebApp({}).handle("GET", "/api/health", {}, b"", "1")
    assert out == {"ok": True, "configured": False, "auth_required": False}


def test_send_cap_falls_back_to_preview():
    t = [1000.0]
    app = make_app({"WEB_MAX_SENDS_PER_HOUR": "1"}, limiter=RateLimiter(99, 99), clock=lambda: t[0])
    body = {"stage": "send", "domain": "acme.com", "confirm_send": True}
    s1, o1 = post(app, body)
    assert o1["live_send"] is True and o1["result"]["mode"] == "sent"
    s2, o2 = post(app, body)
    assert s2 == 200 and o2["live_send"] is False and o2["result"]["mode"] == "dry_run"
    assert "limit" in o2["send_note"].lower()
    t[0] += 3601
    assert post(app, body)[1]["live_send"] is True


def test_rate_limiter_prunes_idle_entries(monkeypatch):
    import _logic

    monkeypatch.setattr(_logic, "MAX_TRACKED_IPS", 50)
    lim = RateLimiter(per_min=5, runs_per_hour=5)
    for i in range(500):
        lim.check(f"ip{i}", 1000.0 + i * 100, run_start=True)
    assert len(lim._req) <= 51 and len(lim._runs) <= 51
    for i in range(500):  # all active at the same instant: still bounded
        lim.check(f"x{i}", 5000.0, run_start=True)
    assert len(lim._req) <= 51 and len(lim._runs) <= 51


@pytest.mark.parametrize(
    "bad",
    ["localhost", "127.0.0.1", "10.0.0.5", "http://acme.com/path", "acme.com/path", "a..b.com",
     "../etc/passwd", "acme.com:8080", "user@acme.com", "", "foo.local", "[::1]", "acme", 42, None,
     "evil.internal"],
)
def test_domain_rejected(bad):
    with pytest.raises(RequestError) as e:
        validate_domain(bad)
    assert e.value.status == 400
    status, body = post(make_app(), {"stage": "scrape", "domain": bad})
    assert status == 400 and body["error"] == "bad_domain"


def test_domain_normalised():
    assert validate_domain("  WWW.Acme.COM. ") == "acme.com"


def test_bad_stage_and_json():
    app = make_app()
    assert post(app, {"stage": "nuke", "domain": "acme.com"})[0] == 400
    assert app.handle("POST", "/api/run", {"x-app-password": PW}, b"{not json", "1")[0] == 400
    assert post(app, {"stage": "scrape", "domain": "acme.com", "state": [1]})[0] == 400


def test_rate_limit_per_minute():
    app = make_app(limiter=RateLimiter(per_min=3, runs_per_hour=99), clock=lambda: 1000.0)
    codes = [post(app, {"stage": "extract", "domain": "acme.com"})[0] for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    # a different IP is unaffected
    assert post(app, {"stage": "extract", "domain": "acme.com"}, ip="9.9.9.9")[0] == 200


def test_rate_limit_runs_per_hour_and_window_expires():
    t = [1000.0]
    app = make_app(limiter=RateLimiter(per_min=99, runs_per_hour=2), clock=lambda: t[0])
    codes = [post(app, {"stage": "scrape", "domain": "acme.com"})[0] for _ in range(3)]
    assert codes == [200, 200, 429]
    t[0] += 3601
    assert post(app, {"stage": "scrape", "domain": "acme.com"})[0] == 200


def test_send_requires_explicit_confirm_and_ignores_recipient():
    seen = []

    def spy(stage, state, *, settings, send=False, live_hunter=False):
        seen.append((stage, send, live_hunter, state.get("to")))
        return fake_run_stage(stage, state, settings=settings, send=send, live_hunter=live_hunter)

    app = make_app(run_stage=spy)
    base = {"stage": "send", "domain": "acme.com", "to": "evil@attacker.com"}
    for confirm in (None, False, "true", 1, "yes"):
        body = dict(base, **({} if confirm is None else {"confirm_send": confirm}))
        status, out = post(app, body)
        assert status == 200 and out["live_send"] is False
        assert out["result"]["mode"] == "dry_run"
    status, out = post(app, dict(base, confirm_send=True))
    assert out["live_send"] is True and out["result"]["mode"] == "sent"
    assert out["result"]["payload"]["to"] == ["owner@example.com"]
    assert [s[1] for s in seen] == [False] * 5 + [True]


def test_hunter_live_only_for_poc_within_budget():
    seen = []

    def spy(stage, state, *, settings, send=False, live_hunter=False):
        seen.append((stage, live_hunter))
        return fake_run_stage(stage, state, settings=settings, send=send, live_hunter=live_hunter)

    app = make_app({"WEB_HUNTER_BUDGET": "2"}, run_stage=spy, limiter=RateLimiter(99, 99))
    for stage in ("draft", "poc", "poc", "poc"):
        post(app, {"stage": stage, "domain": "acme.com"})
    assert seen == [("draft", False), ("poc", True), ("poc", True), ("poc", False)]
    assert app.hunter_remaining() == 0


def test_no_secret_in_responses():
    def leaky(stage, state, *, settings, send=False, live_hunter=False):
        return {"stage": stage, "status": "failed", "stop_reason": "x",
                "detail": f"boom with {CANARY} and {PW}", "result": {"k": CANARY}, "state": {}}

    app = make_app(run_stage=leaky)
    status, out = post(app, {"stage": "scrape", "domain": "acme.com"})
    blob = json.dumps(out)
    assert status == 200 and CANARY not in blob and PW not in blob and "***" in blob

    def explode(*a, **k):
        raise RuntimeError(f"traceback with {CANARY}")

    status, out = post(make_app(run_stage=explode), {"stage": "scrape", "domain": "acme.com"})
    blob = json.dumps(out)
    assert status == 500 and CANARY not in blob and "Traceback" not in blob


def test_full_stage_sequence_with_fake():
    app = make_app(limiter=RateLimiter(99, 99))
    state = {}
    for stage in STAGES:
        status, out = post(app, {"stage": stage, "domain": "https-not-allowed.acme.com",
                                 "state": state, "confirm_send": True})
        assert status == 200 and out["status"] == "ok" and out["stage"] == stage
        state = out["state"]
    assert state["done"] == list(STAGES) and state["domain"] == "https-not-allowed.acme.com"
    assert out["result"]["payload"]["to"] == ["owner@example.com"]


def test_fake_stops_and_fails():
    app = make_app()
    status, out = post(app, {"stage": "qualify", "domain": "stop.acme.com"})
    assert status == 200 and out["status"] == "stopped"
    status, out = post(app, {"stage": "scrape", "domain": "fail.acme.com"})
    assert out["status"] == "failed"


def test_vercel_json_valid():
    cfg = json.loads((ROOT / "vercel.json").read_text())
    fn = cfg["functions"]["api/*.py"]
    assert fn["maxDuration"] == 60 and "src" in fn["includeFiles"] and "config" in fn["includeFiles"]
    assert cfg["outputDirectory"] == "web" and (ROOT / "web" / "index.html").is_file()
    reqs = (ROOT / "requirements.txt").read_text()
    assert "google-genai==" in reqs and "pytest" not in reqs and "respx" not in reqs


def test_vercel_handler_importable_and_sets_tmp_data_dir(monkeypatch):
    monkeypatch.delenv("OUTREACH_DATA_DIR", raising=False)
    sys.modules.pop("run", None)
    import run

    assert run.os.environ["OUTREACH_DATA_DIR"] == "/tmp/outreach"
    assert hasattr(run, "handler")


def test_real_settings_path_uses_tmp_dirs():
    env = {"APP_PASSWORD": PW, "GEMINI_API_KEY": "canary-gem-0001x", "HUNTER_API_KEY": "canary-hun-0002x",
           "RESEND_API_KEY": "canary-res-0003x", "OWNER_EMAIL": "owner@example.com",
           "OUTREACH_DATA_DIR": "/tmp/outreach"}
    seen = {}

    def spy(stage, state, *, settings, send=False, live_hunter=False):
        seen["s"] = settings
        return fake_run_stage(stage, state, settings=settings)

    status, out = post(WebApp(env, run_stage=spy), {"stage": "scrape", "domain": "acme.com"})
    assert status == 200
    assert str(seen["s"].cache_dir).startswith("/tmp/outreach")
    assert str(seen["s"].out_dir).startswith("/tmp/outreach")
    assert "canary-hun-0002x" not in json.dumps(out)


def test_missing_env_reports_names_503():
    app = WebApp({"APP_PASSWORD": PW}, run_stage=fake_run_stage)
    status, out = post(app, {"stage": "scrape", "domain": "acme.com"})
    assert status == 503 and "GEMINI_API_KEY" in out["message"]
    assert post(app, {"stage": "scrape", "domain": "acme.com"}, pw="bad")[0] == 401
