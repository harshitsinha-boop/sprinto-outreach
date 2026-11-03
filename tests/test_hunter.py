"""HunterClient (cache-first, budget-capped) and FixtureHunter. No real network."""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import CANARY_ENV, FIXTURE_DIR
from outreach.hunter import (
    BASE,
    SEARCH_PARAMS,
    FixtureHunter,
    HunterAuthError,
    HunterClient,
    HunterError,
    HunterQuotaError,
)
from outreach.stages import pick_contact

KEY = CANARY_ENV["HUNTER_API_KEY"]
FIXTURE = json.loads((FIXTURE_DIR / "hunter_domain_search.json").read_text())
MONTH = "2026-11"


def make(tmp_path, handler, budget=25, month=MONTH):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    client = HunterClient(KEY, tmp_path / "hunter", budget, http=http, month=lambda: month)
    return client, calls


def ok(body=None, headers=None):
    return lambda request: httpx.Response(200, json=body if body is not None else FIXTURE, headers=headers or {})


def account_body(credits=..., searches=...):
    requests: dict = {}
    if credits is not ...:
        requests["credits"] = {"used": 0, "available": 25, "remaining": credits}
    if searches is not ...:
        requests["searches"] = {"used": 0, "available": 25, "remaining": searches}
    return {"data": {"plan_name": "Free", "reset_date": "2026-12-01", "email": "owner@x.com", "requests": requests}}


def test_cache_miss_makes_one_request_with_header_auth_and_writes_cache(tmp_path):
    c, calls = make(tmp_path, ok(headers={"X-Credits-Used": "1"}))
    r = c.domain_search("example.com")

    assert len(calls) == 1
    req = calls[0]
    assert req.headers["X-API-KEY"] == KEY
    assert "api_key" not in req.url.params and KEY not in str(req.url)
    assert req.url.path.endswith("/domain-search")
    assert req.url.params["domain"] == "example.com"
    for k, v in SEARCH_PARAMS.items():
        assert req.url.params[k] == str(v)
    assert "offset" not in req.url.params

    assert r["from_cache"] is False and r["source"] == "live"
    path = tmp_path / "hunter" / "example.com.json"
    assert path.exists()
    entry = json.loads(path.read_text())
    assert set(entry) == {"domain", "fetched_at", "params", "credits_used", "response"}
    assert entry["response"] == FIXTURE and entry["credits_used"] == "1"
    assert c.live_calls_this_process == 1
    assert KEY not in path.read_text()


def test_cache_written_before_returning_even_if_caller_fails(tmp_path):
    c, _ = make(tmp_path, ok())
    c.domain_search("example.com")
    # a brand new client (a "second run") finds it without any request
    c2, calls = make(tmp_path, ok())
    r = c2.domain_search("example.com")
    assert calls == [] and r["from_cache"] is True and r["source"] == "cache"
    assert c2.live_calls_this_process == 0


def test_cache_hit_makes_no_request_and_normalises_domain(tmp_path):
    c, calls = make(tmp_path, ok())
    c.domain_search("WWW.Example.com")
    r = c.domain_search("example.com")
    assert len(calls) == 1
    assert r["from_cache"] is True and r["source"] == "cache"
    assert [p.name for p in (tmp_path / "hunter").glob("*.json") if not p.name.startswith("_")] == ["example.com.json"]


def test_zero_result_200_is_cached(tmp_path):
    empty = {"data": {"domain": "empty.com", "emails": []}, "meta": {"results": 0}}
    c, calls = make(tmp_path, ok(empty))
    c.domain_search("empty.com")
    again = c.domain_search("empty.com")
    assert len(calls) == 1
    assert again["from_cache"] is True
    assert (tmp_path / "hunter" / "empty.com.json").exists()


def test_401_raises_auth_error_and_is_not_cached(tmp_path):
    body = {"errors": [{"id": "authentication_failed", "code": 401, "details": "No user found for " + KEY}]}
    c, _ = make(tmp_path, lambda r: httpx.Response(401, json=body))
    with pytest.raises(HunterAuthError) as ei:
        c.domain_search("example.com")
    assert KEY not in str(ei.value) and "authentication_failed" in str(ei.value)
    assert not (tmp_path / "hunter" / "example.com.json").exists()
    assert c.live_calls_this_process == 0


def test_429_raises_quota_error_and_is_not_cached(tmp_path):
    body = {"errors": [{"id": "usage_limit_reached", "code": 429}]}
    c, calls = make(tmp_path, lambda r: httpx.Response(429, json=body))
    with pytest.raises(HunterQuotaError):
        c.domain_search("example.com")
    assert len(calls) == 1  # never retried
    assert not (tmp_path / "hunter" / "example.com.json").exists()


@pytest.mark.parametrize("code", [403, 451, 400, 500])
def test_other_errors_raise_hunter_error_not_cached(tmp_path, code):
    c, _ = make(tmp_path, lambda r: httpx.Response(code, json={"errors": [{"id": "some_id", "code": code}]}))
    with pytest.raises(HunterError) as ei:
        c.domain_search("example.com")
    assert not isinstance(ei.value, (HunterAuthError, HunterQuotaError))
    assert not (tmp_path / "hunter" / "example.com.json").exists()


def test_budget_blocks_next_miss_with_no_http_request(tmp_path):
    usage = tmp_path / "hunter" / "_usage.json"
    usage.parent.mkdir(parents=True)
    usage.write_text(json.dumps({"month": MONTH, "live_calls": 1, "credits_used": 1.0}))
    c, calls = make(tmp_path, ok(), budget=1)
    with pytest.raises(HunterQuotaError):
        c.domain_search("example.com")
    assert calls == []
    assert not (tmp_path / "hunter" / "example.com.json").exists()


def test_budget_does_not_block_a_cache_hit(tmp_path):
    c, calls = make(tmp_path, ok(), budget=1)
    c.domain_search("example.com")
    assert c.domain_search("example.com")["from_cache"] is True
    with pytest.raises(HunterQuotaError):
        c.domain_search("other.com")
    assert len(calls) == 1


def test_usage_counter_persists_and_resets_in_a_new_month(tmp_path):
    c, _ = make(tmp_path, ok(headers={"X-Credits-Used": "1"}), budget=1)
    c.domain_search("example.com")
    usage = json.loads((tmp_path / "hunter" / "_usage.json").read_text())
    assert usage == {"month": MONTH, "live_calls": 1, "credits_used": 1.0}

    c_next, calls = make(tmp_path, ok(), budget=1, month="2026-12")
    c_next.domain_search("other.com")
    assert len(calls) == 1
    usage = json.loads((tmp_path / "hunter" / "_usage.json").read_text())
    assert usage["month"] == "2026-12" and usage["live_calls"] == 1
    assert usage["credits_used"] == 0.0  # missing header counts as 0


def test_account_returns_credits_remaining(tmp_path):
    c, calls = make(tmp_path, lambda r: httpx.Response(200, json=account_body(credits=17, searches=3)))
    a = c.account()
    assert a == {"plan": "Free", "reset_date": "2026-12-01", "remaining": 17}
    assert calls[0].headers["X-API-KEY"] == KEY and calls[0].url.path.endswith("/account")
    assert not list((tmp_path / "hunter").glob("*")) if (tmp_path / "hunter").exists() else True


def test_account_falls_back_to_searches_when_credits_absent(tmp_path):
    c, _ = make(tmp_path, lambda r: httpx.Response(200, json=account_body(searches=9)))
    assert c.account()["remaining"] == 9


def test_account_zero_credits_returns_zero(tmp_path):
    c, _ = make(tmp_path, lambda r: httpx.Response(200, json=account_body(credits=0, searches=25)))
    remaining = c.account()["remaining"]
    assert remaining == 0 and remaining is not None


def test_account_unknown_remaining_is_none(tmp_path):
    c, _ = make(tmp_path, lambda r: httpx.Response(200, json=account_body()))
    assert c.account()["remaining"] is None


def test_account_error_maps_to_auth_error(tmp_path):
    c, _ = make(tmp_path, lambda r: httpx.Response(401, json={"errors": [{"id": "authentication_failed"}]}))
    with pytest.raises(HunterAuthError):
        c.account()


def test_base_url_is_hunter_v2():
    assert BASE == "https://api.hunter.io/v2"


# ------------------------------------------------------------ FixtureHunter


def test_fixture_hunter_returns_contact_only_for_fixture_domain():
    h = FixtureHunter()
    assert h.fixture_domain == "piedpiper.com"

    hit = h.domain_search("piedpiper.com")
    assert hit["source"] == "fixture" and hit["from_cache"] is False
    contact = pick_contact(hit)
    assert contact is not None and contact.first_name == "Richard" and contact.last_name == "Hendricks"

    other = h.domain_search("example.com")
    assert other["source"] == "fixture"
    assert other["response"]["data"]["emails"] == []
    assert other["response"]["meta"]["results"] == 0
    assert pick_contact(other) is None
    assert h.live_calls_this_process == 0


def test_fixture_hunter_normalises_domain_and_does_not_mutate_fixture():
    h = FixtureHunter()
    assert pick_contact(h.domain_search("https://WWW.PiedPiper.com/about")) is not None
    h.domain_search("example.com")
    assert pick_contact(h.domain_search("piedpiper.com")) is not None


def test_fixture_hunter_account_reports_fixture_plan():
    a = FixtureHunter().account()
    assert a["plan"] == "fixture" and a["remaining"] is None
