"""Every smoke check passes on a well-behaved fake and FAILs cleanly (no traceback) on a bad one."""

from __future__ import annotations

import io

import httpx

from conftest import (
    CANARY_ENV,
    FakeGenaiClient,
    FakeHunter,
    FakeSender,
    api_error,
    blocked_response,
    function_call_response,
    text_response,
)
from outreach.hunter import HunterClient
from outreach.llm import LLMClient
from outreach.smoke import (
    check_function_calling,
    check_gemini_structured,
    check_hunter,
    check_hunter_account,
    check_resend,
    run_smoke,
)

KEY = CANARY_ENV["GEMINI_API_KEY"]
FAST, SMART = "gemini-3.5-flash-lite", "gemini-3.8-flash"
PROBE = '{"company": "Acme", "is_saas": true}'
FC = function_call_response("fetch_page", {"url": "https://example.com/about", "reason": "smoke"})


def make_llm(queue, cache_dir=None):
    return LLMClient(KEY, cache_dir, client=FakeGenaiClient(queue), sleep=lambda s: None)


def good_gemini_queue():
    return [text_response(PROBE), text_response(PROBE), FC, text_response("Example Domain")]


def mode_of(call):
    mode = call["config"].tool_config.function_calling_config.mode
    return getattr(mode, "value", mode)


def test_structured_passes_on_valid_json():
    r = check_gemini_structured(make_llm([text_response(PROBE)]), FAST)
    assert r.ok and not r.skipped
    assert r.name == f"gemini_structured[{FAST}]"
    assert "Acme" in r.detail


def test_structured_fails_on_blocked_response():
    llm = make_llm([blocked_response(), blocked_response()])
    r = check_gemini_structured(llm, FAST)  # must return a FAIL result, not raise
    assert not r.ok and not r.skipped
    assert "LLMSchemaError" in r.detail


def test_structured_refuses_cached_client(tmp_path):
    llm = make_llm([text_response(PROBE)], cache_dir=tmp_path / "llm")
    r = check_gemini_structured(llm, FAST)
    assert not r.ok
    assert "cache" in r.detail
    assert llm._c.models.calls == []


def test_function_calling_passes_and_keeps_thought_signature():
    llm = make_llm([FC, text_response("Example Domain")])
    r = check_function_calling(llm, SMART)
    assert r.ok and "role=user" in r.detail

    calls = llm._c.models.calls
    assert len(calls) == 2
    assert mode_of(calls[0]) == "ANY" and mode_of(calls[1]) == "NONE"
    assert calls[1]["config"].automatic_function_calling.disable is True
    contents = calls[1]["contents"]
    model_turn = next(c for c in contents if c.role == "model")
    assert model_turn.parts[0].thought_signature == b"sig"
    assert contents[-1].role == "user"  # live-proven (01-04, A1): the API rejects role="tool"
    assert contents[-1].parts[0].function_response.name == "fetch_page"


def test_function_calling_fails_without_call():
    llm = make_llm([text_response("I will not call anything")])
    r = check_function_calling(llm, SMART)
    assert not r.ok and "fetch_page" in r.detail
    assert len(llm._c.models.calls) == 1


def test_function_calling_falls_back_to_user_role_on_400(monkeypatch):
    # The live default is now "user"; re-arm the "tool" default so the fallback path stays covered.
    monkeypatch.setattr("outreach.smoke.TOOL_RESULT_ROLE", "tool")
    llm = make_llm([FC, api_error(400, "INVALID_ARGUMENT", "bad role"), text_response("ok")])
    r = check_function_calling(llm, SMART, role="tool")
    assert r.ok and "role=user" in r.detail
    calls = llm._c.models.calls
    assert len(calls) == 3
    assert calls[1]["contents"][-1].role == "tool"
    assert calls[2]["contents"][-1].role == "user"


def test_hunter_refuses_when_remaining_zero():
    r = check_hunter_account(FakeHunter(remaining=0), 25)
    assert not r.ok and "remaining=0" in r.detail
    ok = check_hunter_account(FakeHunter(remaining=25), 25)
    assert ok.ok and "WARNING" not in ok.detail
    drift = check_hunter_account(FakeHunter(remaining=10), 25)
    assert drift.ok and "WARNING" in drift.detail


def test_hunter_cache_hit_fails_not_live():
    class CachedHunter(FakeHunter):
        def domain_search(self, domain):
            res = super().domain_search(domain)
            return {**res, "from_cache": True, "source": "cache"}

    r = check_hunter(CachedHunter(), "example.com")
    assert not r.ok and "NOT LIVE" in r.detail


def test_hunter_fails_on_more_than_one_live_call():
    h = FakeHunter()
    good = check_hunter(h, "example.com")
    assert good.ok and "results=1" in good.detail
    h.live_calls_this_process = 2
    assert not check_hunter(h, "example.com").ok

    empty = FakeHunter()
    r = check_hunter(empty, "")
    assert not r.ok and "SKELETON_DOMAIN" in r.detail and empty.calls == []


def test_resend_passes_and_payload_to_is_owner(settings):
    sender = FakeSender()
    r = check_resend(settings, sender=sender)
    assert r.ok and "id=fake-msg-123" in r.detail
    (payload, options), = sender.calls
    assert payload["to"] == [settings.owner_email]
    assert "[SMOKE]" in payload["subject"]
    assert options["idempotency_key"].startswith("smoke-")
    assert "piedpiper" not in str(payload)


def test_resend_fails_without_id(settings):
    r = check_resend(settings, sender=FakeSender(response={}))
    assert not r.ok and "message id" in r.detail


def test_run_smoke_order_and_only_filter(settings):
    out = io.StringIO()
    results = run_smoke(
        settings, llm=make_llm(good_gemini_queue()), hunter=FakeHunter(), sender=FakeSender(), out=out
    )
    assert [r.name for r in results] == [
        f"gemini_structured[{FAST}]",
        f"gemini_structured[{SMART}]",
        "gemini_tools",
        "hunter_account",
        "hunter",
        "resend",
    ]
    assert all(r.ok for r in results)
    text = out.getvalue()
    assert "PASS hunter_account" in text and "config GEMINI_API_KEY: set (env)" in text
    assert "config SKELETON_DOMAIN: set (env)" in text

    only_out = io.StringIO()
    only = run_smoke(
        settings,
        only="hunter",
        llm=make_llm([]),
        hunter=FakeHunter(remaining=None),
        sender=FakeSender(),
        out=only_out,
    )
    assert [r.name for r in only] == ["hunter_account", "hunter"]
    assert "WARNING hunter_account: remaining unknown; zero-credit guard inactive" in only_out.getvalue()


def test_run_smoke_output_never_contains_key_values(settings):
    canaries = [CANARY_ENV[k] for k in ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY")]

    all_pass = io.StringIO()
    run_smoke(
        settings, llm=make_llm(good_gemini_queue()), hunter=FakeHunter(), sender=FakeSender(), out=all_pass
    )
    leaky = io.StringIO()
    run_smoke(
        settings,
        llm=make_llm([api_error(400, "INVALID_ARGUMENT", "bad request echoing " + KEY)]),
        hunter=FakeHunter(),
        sender=FakeSender(),
        out=leaky,
    )
    assert "FAIL" in leaky.getvalue() and "***" in leaky.getvalue()
    for stream in (all_pass, leaky):
        for canary in canaries:
            assert canary not in stream.getvalue()


def test_run_smoke_cheap_fail_skips_spending_checks(settings):
    hunter, sender, out = FakeHunter(), FakeSender(), io.StringIO()
    llm = make_llm([api_error(401, "UNAUTHENTICATED", "bad key")])
    results = run_smoke(settings, llm=llm, hunter=hunter, sender=sender, out=out)

    assert not results[0].ok and not results[0].skipped
    assert [r.name for r in results[1:]] == [
        f"gemini_structured[{SMART}]",
        "gemini_tools",
        "hunter_account",
        "hunter",
        "resend",
    ]
    assert all(r.skipped and not r.ok for r in results[1:])
    assert hunter.calls == [] and sender.calls == []
    assert len(llm._c.models.calls) == 1
    text = out.getvalue()
    assert "SKIPPED hunter " in text and "SKIPPED resend " in text
    assert "failed first" in text


def test_run_smoke_hunter_account_fail_skips_search_and_resend(settings):
    hunter, sender, out = FakeHunter(remaining=0), FakeSender(), io.StringIO()
    results = run_smoke(
        settings, llm=make_llm(good_gemini_queue()), hunter=hunter, sender=sender, out=out
    )
    by_name = {r.name: r for r in results}
    assert not by_name["hunter_account"].ok and not by_name["hunter_account"].skipped
    assert by_name["hunter"].skipped and by_name["resend"].skipped
    assert hunter.calls == [] and sender.calls == []
    assert "SKIPPED hunter " in out.getvalue() and "SKIPPED resend " in out.getvalue()


def test_run_smoke_real_hunter_zero_credits_skips_search_and_resend(settings, tmp_path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/account"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "plan_name": "Free",
                        "reset_date": "2026-12-01",
                        "requests": {
                            "credits": {"remaining": 0},
                            "searches": {"remaining": 25},
                        },
                    }
                },
            )
        return httpx.Response(500)

    hunter = HunterClient(
        CANARY_ENV["HUNTER_API_KEY"],
        tmp_path / "hunter",
        25,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    sender = FakeSender()
    results = run_smoke(
        settings, llm=make_llm(good_gemini_queue()), hunter=hunter, sender=sender, out=io.StringIO()
    )
    by_name = {r.name: r for r in results}
    assert not by_name["hunter_account"].ok and "remaining=0" in by_name["hunter_account"].detail
    assert by_name["hunter"].skipped and by_name["resend"].skipped
    assert not any(r.url.path.endswith("/domain-search") for r in seen)
    assert sender.calls == []
