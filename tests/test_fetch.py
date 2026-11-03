"""PageFetcher: caching, size and text caps, HTML-only, error handling. No real network."""

from __future__ import annotations

import hashlib
import json
import socket

import httpx
import pytest

import outreach.fetch as fetch_mod
from conftest import SAMPLE_HTML, SAMPLE_PAGE_TEXT, SAMPLE_SENTENCES
from outreach.fetch import MAX_BYTES, MAX_CHARS, USER_AGENT, PageFetcher

URL = "https://example.com/"


def make(tmp_path, handler, **kwargs):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return PageFetcher(tmp_path / "pages", http=http, **kwargs), calls


def page_calls(calls):
    """Requests that are not the robots.txt lookup."""
    return [r for r in calls if r.url.path != "/robots.txt"]


def with_robots(robots, page):
    """A handler answering /robots.txt with `robots` (a Response factory) and the rest with `page`."""

    def handler(request):
        if request.url.path == "/robots.txt":
            return robots(request)
        return page(request)

    return handler


def robots_body(text):
    return lambda request: httpx.Response(200, text=text, headers={"content-type": "text/plain"})


def html_ok(body: str = SAMPLE_HTML, ctype: str = "text/html; charset=utf-8"):
    return lambda request: httpx.Response(200, content=body.encode(), headers={"content-type": ctype})


def cache_file(tmp_path, url=URL):
    return tmp_path / "pages" / f"{hashlib.sha1(url.encode()).hexdigest()}.json"


def test_fetch_ok_page_is_cached_and_second_fetch_makes_no_request(tmp_path):
    f, calls = make(tmp_path, html_ok())
    first = f.fetch(URL)
    assert first.status == "ok" and first.from_cache is False and first.text
    assert len(page_calls(calls)) == 1
    assert cache_file(tmp_path).exists()

    second = f.fetch(URL)
    assert second.from_cache is True
    assert second.text == first.text
    assert len(page_calls(calls)) == 1
    assert f.http_calls == 1


def test_fetch_sends_polite_user_agent_and_follows_redirects(tmp_path):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, content=SAMPLE_HTML.encode(), headers={"content-type": "text/html"})

    f, _ = make(tmp_path, handler)
    f.fetch(URL)
    assert seen["ua"] == USER_AGENT


def test_ok_page_chars_equals_text_length(tmp_path):
    f, _ = make(tmp_path, html_ok())
    live = f.fetch(URL)
    assert live.status == "ok"
    assert live.chars == len(live.text) and live.chars > 0
    cached = f.fetch(URL)
    assert cached.from_cache is True
    assert cached.chars == len(cached.text) and cached.chars > 0

    long_html = "<html><body>" + "".join(
        f"<p>Sentence number {i} about a compliance platform for finance teams.</p>"
        for i in range(2000)
    ) + "</body></html>"
    f2, _ = make(tmp_path / "other", html_ok(long_html))
    over = f2.fetch("https://long.example/")
    assert over.status == "ok"
    assert over.chars == MAX_CHARS == len(over.text)


def test_fetch_non_html_content_type_is_unavailable(tmp_path):
    f, _ = make(tmp_path, html_ok("{}", ctype="application/json"))
    r = f.fetch(URL)
    assert r.status == "unavailable"
    assert r.text is None and r.chars == 0


def test_fetch_transport_error_is_error_and_not_cached(tmp_path):
    def boom(request):
        raise httpx.ConnectError("no route")

    f, _ = make(tmp_path, boom)
    r = f.fetch(URL)
    assert r.status == "error"
    assert "ConnectError" in (r.error or "")
    assert not cache_file(tmp_path).exists()


@pytest.mark.parametrize("code", [503, 500, 429])
def test_fetch_server_error_and_429_are_error_and_not_cached(tmp_path, code):
    f, _ = make(tmp_path, lambda request: httpx.Response(code, text="busy"))
    r = f.fetch(URL)
    assert r.status == "error"
    assert not cache_file(tmp_path).exists()


def test_fetch_404_is_unavailable_and_cached(tmp_path):
    f, calls = make(tmp_path, lambda request: httpx.Response(404, text="nope"))
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.error == "HTTP 404"
    assert cache_file(tmp_path).exists()
    assert f.fetch(URL).from_cache is True
    assert len(page_calls(calls)) == 1


def test_fetch_body_is_cut_at_max_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_mod, "MAX_BYTES", 3000)
    monkeypatch.setattr(fetch_mod, "MAX_CHARS", 1_000_000)
    body = (
        "<html><body>"
        + "".join(f"<p>HEADPART paragraph {i} describing the product in detail here.</p>" for i in range(100))
        + "".join(f"<p>TAILPART paragraph {i} that sits far beyond the byte cap.</p>" for i in range(400))
        + "</body></html>"
    )
    assert len(body) > 3000 * 4
    f, _ = make(tmp_path, html_ok(body))
    r = f.fetch(URL)
    assert r.status == "ok"
    assert "HEADPART" in r.text
    assert "TAILPART" not in r.text
    assert len(r.text) <= 3000


def test_fetch_real_max_bytes_constant_is_one_and_a_half_megabytes():
    assert MAX_BYTES == 1_500_000


def test_fetch_falls_back_to_beautifulsoup_when_trafilatura_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: None)
    f, _ = make(tmp_path, html_ok())
    r = f.fetch(URL)
    assert r.status == "ok"
    assert "Acme Ledger" in r.text
    assert r.chars == len(r.text)


def test_fetch_empty_extracted_text_is_unavailable(tmp_path):
    f, _ = make(tmp_path, html_ok("<html><body></body></html>"))
    r = f.fetch(URL)
    assert r.status == "unavailable"
    assert r.chars == 0


def test_fetch_cache_entry_is_page_result_json(tmp_path):
    f, _ = make(tmp_path, html_ok())
    f.fetch(URL)
    data = json.loads(cache_file(tmp_path).read_text())
    assert data["url"] == URL and data["status"] == "ok"
    assert data["chars"] == len(data["text"])
    assert SAMPLE_PAGE_TEXT.split(" ")[0] in data["text"]


# ---- Plan 02-02 Task 1: robots.txt, address guard, redirects, deadline, politeness, sanitising, gate ----

PUBLIC = "93.184.216.34"
INJECTION = "PLANTED-INJECTION"


def test_robots_disallowed_path_is_unavailable_without_request(tmp_path):
    handler = with_robots(robots_body("User-agent: *\nDisallow: /pricing\n"), html_ok())
    f, calls = make(tmp_path, handler)

    blocked = f.fetch("https://example.com/pricing")

    assert blocked.status == "unavailable" and blocked.reason == "robots_disallowed"
    assert blocked.text is None
    assert [r.url.path for r in page_calls(calls)] == []
    assert f.fetch("https://example.com/pricing").from_cache is True  # the verdict is cached

    ok = f.fetch(URL)
    assert ok.status == "ok"
    assert [r.url.path for r in page_calls(calls)] == ["/"]


def test_robots_sent_with_project_user_agent_and_parsed_per_agent_group(tmp_path):
    seen = {}

    def robots(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="User-agent: sprinto-outreach\nDisallow: /\n")

    f, calls = make(tmp_path, with_robots(robots, html_ok()))
    r = f.fetch(URL)
    assert seen["ua"] == USER_AGENT
    assert r.status == "unavailable" and r.reason == "robots_disallowed"
    assert page_calls(calls) == []


def test_robots_404_allows_all(tmp_path):
    f, calls = make(tmp_path, with_robots(lambda r: httpx.Response(404), html_ok()))
    assert f.fetch(URL).status == "ok"
    assert f.fetch("https://example.com/anything").status == "ok"
    assert [r.url.path for r in page_calls(calls)] == ["/", "/anything"]


@pytest.mark.parametrize("code", [401, 403])
def test_robots_401_and_403_allow_all(tmp_path, code):
    f, _ = make(tmp_path, with_robots(lambda r: httpx.Response(code), html_ok()))
    assert f.fetch(URL).status == "ok"


@pytest.mark.parametrize("code", [503, 429])
def test_robots_5xx_is_error_and_page_not_requested(tmp_path, code):
    f, calls = make(tmp_path, with_robots(lambda r: httpx.Response(code), html_ok()))
    r = f.fetch(URL)
    assert r.status == "error" and r.reason == "robots_unreachable"
    assert page_calls(calls) == []
    assert not cache_file(tmp_path).exists()


def test_robots_transport_error_is_error_and_page_not_requested(tmp_path):
    def boom(request):
        raise httpx.ConnectError("no route")

    f, calls = make(tmp_path, with_robots(boom, html_ok()))
    r = f.fetch(URL)
    assert r.status == "error" and "ConnectError" in (r.error or "")
    assert r.reason == "transport_error"
    assert page_calls(calls) == []
    assert not cache_file(tmp_path).exists()


def test_robots_fetched_once_per_host_and_reused_from_disk(tmp_path):
    handler = with_robots(robots_body("User-agent: *\nDisallow: /private\n"), html_ok())
    f, calls = make(tmp_path, handler)
    f.fetch("https://example.com/")
    f.fetch("https://example.com/about")
    assert f.robots_calls == 1
    assert [r.url.path for r in calls].count("/robots.txt") == 1

    f2, calls2 = make(tmp_path, handler)
    assert f2.fetch("https://example.com/pricing").status == "ok"
    assert f2.robots_calls == 0
    assert "/robots.txt" not in [r.url.path for r in calls2]
    assert f2.fetch("https://example.com/private").reason == "robots_disallowed"


@pytest.mark.parametrize(
    "addr",
    ["127.0.0.1", "10.0.0.5", "169.254.169.254", "100.64.0.1", "224.0.0.1", "::1", "::ffff:127.0.0.1", "fd00::1"],
)
def test_private_address_is_refused_without_request(tmp_path, addr):
    f, calls = make(tmp_path, html_ok(), resolve=lambda host: [addr])
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "private_address"
    assert r.text is None
    assert calls == []


def test_any_private_address_in_a_mixed_answer_refuses_the_host(tmp_path):
    f, calls = make(tmp_path, html_ok(), resolve=lambda host: [PUBLIC, "10.0.0.5"])
    assert f.fetch(URL).reason == "private_address"
    assert calls == []


def test_is_public_address_classes():
    from outreach.fetch import is_public_address as pub

    for bad in ["127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254",
                "100.64.0.1", "224.0.0.1", "0.0.0.0", "::1", "::ffff:127.0.0.1", "fd00::1",
                "fe80::1", "not-an-ip"]:
        assert pub(bad) is False, bad
    assert pub(PUBLIC) is True
    assert pub("2606:2800:220:1:248:1893:25c8:1946") is True


def test_dns_failure_is_error_not_cached(tmp_path):
    def gone(host):
        raise socket.gaierror(-2, "Name or service not known")

    f, calls = make(tmp_path, html_ok(), resolve=gone)
    r = f.fetch(URL)
    assert r.status == "error" and r.reason == "dns_failure"
    assert calls == []
    assert not cache_file(tmp_path).exists()


def test_same_site_redirect_is_followed_and_final_url_recorded(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "example.com":
            return httpx.Response(301, headers={"location": "https://www.example.com/home"})
        return html_ok()(request)

    f, calls = make(tmp_path, handler)
    r = f.fetch(URL)
    assert r.status == "ok" and r.final_url == "https://www.example.com/home"
    assert r.url == URL
    assert [str(c.url) for c in page_calls(calls)] == [URL, "https://www.example.com/home"]
    assert f.http_calls == 2  # one per hop


def test_relative_redirect_location_is_resolved_against_the_current_url(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return html_ok()(request)

    f, _ = make(tmp_path, handler)
    r = f.fetch("https://example.com/old")
    assert r.status == "ok" and r.final_url == "https://example.com/new"


def test_off_site_redirect_is_unavailable(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    f, calls = make(tmp_path, handler)
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "off_site_redirect"
    assert "evil.example" in (r.error or "")
    assert all(c.url.host != "evil.example" for c in calls)


def test_redirect_to_private_address_is_refused(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(301, headers={"location": "https://internal.example.com/admin"})

    resolve = lambda host: ["10.0.0.5"] if host == "internal.example.com" else [PUBLIC]  # noqa: E731
    f, calls = make(tmp_path, handler, resolve=resolve)
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "private_address"
    assert all(c.url.host != "internal.example.com" for c in calls)


def test_too_many_redirects_is_unavailable(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        n = 0 if request.url.path == "/" else int(request.url.path[2:])
        return httpx.Response(301, headers={"location": f"/r{n + 1}"})

    f, calls = make(tmp_path, handler)
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "too_many_redirects"
    assert len(page_calls(calls)) == 6  # the original request plus five followed hops


def test_non_http_scheme_is_unavailable_without_request(tmp_path):
    f, calls = make(tmp_path, html_ok())
    r = f.fetch("ftp://example.com/")
    assert r.status == "unavailable" and r.reason == "bad_scheme"
    assert calls == []
    assert not cache_file(tmp_path, "ftp://example.com/").exists()


def test_url_outside_the_site_is_unavailable_without_request(tmp_path):
    f, calls = make(tmp_path, html_ok())
    r = f.fetch("https://jobs.lever.co/example", site="example.com")
    assert r.status == "unavailable" and r.reason == "off_site"
    assert calls == []
    assert f.fetch("https://trust.example.com/", site="example.com").status == "ok"


def test_fetch_deadline_stops_slow_body(tmp_path):
    from outreach.fetch import FETCH_DEADLINE_S

    state = {"t": 0.0}

    def slow(request):
        def chunks():
            for _ in range(10):
                state["t"] += 5.0
                yield b"<p>slow chunk of text</p>"

        return httpx.Response(200, content=chunks(), headers={"content-type": "text/html"})

    f, _ = make(
        tmp_path,
        with_robots(lambda r: httpx.Response(404), slow),
        clock=lambda: state["t"],
        min_interval=0.0,
    )
    r = f.fetch(URL)
    assert FETCH_DEADLINE_S == 20.0
    assert r.status == "error" and r.reason == "deadline"
    assert not cache_file(tmp_path).exists()


def test_polite_interval_between_requests_to_same_host(tmp_path):
    state = {"t": 100.0}
    delays: list[float] = []

    def sleep(seconds):
        delays.append(seconds)
        state["t"] += seconds

    f, _ = make(
        tmp_path,
        with_robots(lambda r: httpx.Response(404), html_ok()),
        clock=lambda: state["t"],
        sleep=sleep,
        min_interval=1.0,
    )
    f.fetch("https://example.com/")  # robots.txt (no wait), then the page (waits)
    f.fetch("https://example.com/a")
    state["t"] += 0.4
    f.fetch("https://example.com/b")
    assert delays == pytest.approx([1.0, 1.0, 0.6])

    before = list(delays)
    assert f.fetch("https://example.com/b").from_cache is True  # a cache hit never sleeps
    assert delays == before

    state["t"] += 5.0
    f.fetch("https://other.example/")  # a different host is tracked on its own clock
    assert delays == pytest.approx(before + [1.0])  # robots.txt (no wait), then the page waits once


def test_system_resolver_reads_getaddrinfo(monkeypatch):
    from conftest import ORIGINAL_SYSTEM_RESOLVE

    rows = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800::1", 0, 0, 0)),
    ]
    seen = {}

    def fake_getaddrinfo(host, port, **kwargs):
        seen["args"] = (host, port, kwargs)
        return rows

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert ORIGINAL_SYSTEM_RESOLVE("example.com") == [PUBLIC, "2606:2800::1"]
    assert seen["args"][0] == "example.com"


def test_legacy_unversioned_cache_entry_is_ignored(tmp_path):
    from outreach.fetch import GUARD_VERSION

    f, calls = make(tmp_path, html_ok())
    path = cache_file(tmp_path)
    path.parent.mkdir(parents=True)
    legacy = {"url": URL, "status": "ok", "text": "STALE PHASE 1 TEXT " * 40, "chars": 760,
              "error": None, "from_cache": False}
    path.write_text(json.dumps(legacy))

    r = f.fetch(URL)
    assert r.from_cache is False and "STALE" not in (r.text or "")
    assert "/robots.txt" in [c.url.path for c in calls] and len(page_calls(calls)) == 1
    assert json.loads(path.read_text())["guard_version"] == GUARD_VERSION

    current = "https://example.com/team"
    f2, calls2 = make(tmp_path, html_ok())
    cache_file(tmp_path, current).write_text(
        json.dumps({**legacy, "url": current, "text": "CURRENT " * 80, "chars": 640,
                    "guard_version": GUARD_VERSION})
    )
    served = f2.fetch(current)
    assert served.from_cache is True and served.text.startswith("CURRENT")
    assert calls2 == []

    other = "https://example.com/old"
    cache_file(tmp_path, other).write_text(json.dumps({**legacy, "url": other, "guard_version": 1}))
    assert f2.fetch(other).from_cache is False  # a different version is also a miss


def _hidden_page() -> str:
    visible = "".join(f"<p>{s}</p>" for s in SAMPLE_SENTENCES)
    hidden = (
        f'<div style="display:none">{INJECTION} display</div>'
        f"<p hidden>{INJECTION} hidden attribute</p>"
        f'<span aria-hidden="true">{INJECTION} aria</span>'
        f'<div style="COLOR:red; Visibility : HIDDEN">{INJECTION} visibility</div>'
        f"<!-- {INJECTION} comment -->"
        f'<script>var x = "{INJECTION} script";</script>'
        f'<style>.a::after {{ content: "{INJECTION} style"; }}</style>'
        f"<noscript>{INJECTION} noscript</noscript>"
        f"<template><p>{INJECTION} template</p></template>"
        f'<div hidden><p hidden>{INJECTION} nested</p></div>'
        f'<input type="hidden" value="{INJECTION} input">'
    )
    return f"<html><head><title>Acme</title></head><body>{visible}{hidden}</body></html>"


@pytest.mark.parametrize("trafilatura_works", [True, False])
def test_hidden_elements_and_comments_never_reach_text(tmp_path, monkeypatch, trafilatura_works):
    if not trafilatura_works:
        monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: None)
    f, _ = make(tmp_path, html_ok(_hidden_page()))
    r = f.fetch(URL)
    assert r.status == "ok"
    assert "Acme Ledger" in r.text
    assert INJECTION not in r.text
    assert INJECTION not in (cache_file(tmp_path).read_text())


def test_links_are_captured_absolute_and_capped(tmp_path, monkeypatch):
    visible = "".join(f"<p>{s}</p>" for s in SAMPLE_SENTENCES)
    nav = (
        '<a href="/about">About us</a>'
        '<a href="https://example.com/careers#team">Careers</a>'
        '<a href="#top">Top</a>'
        '<a href="mailto:hi@example.com">Mail</a>'
        '<a href="javascript:void(0)">JS</a>'
        '<a href="/about">About again</a>'
        '<div hidden><a href="/secret">Secret</a></div>'
        '<a href="https://jobs.lever.co/example">Jobs board</a>'
        f'<a href="/long">{"x" * 200}</a>'
    )
    html = f"<html><body>{visible}{nav}</body></html>"
    f, _ = make(tmp_path, html_ok(html))
    r = f.fetch(URL)

    urls = [link.url for link in r.links]
    assert urls == [
        "https://example.com/about",
        "https://example.com/careers",
        "https://jobs.lever.co/example",
        "https://example.com/long",
    ]
    assert r.links[0].text == "About us"
    assert len(r.links[3].text) == 80

    monkeypatch.setattr(fetch_mod, "MAX_LINKS", 2)
    capped, _ = make(tmp_path / "capped", html_ok(html))
    assert len(capped.fetch(URL).links) == 2


def test_challenge_page_is_unavailable_blocked(tmp_path):
    challenge = (
        "<html><body><h1>Just a moment...</h1><p>Checking your browser before accessing "
        "example.com. This process is automatic. Your browser will redirect to your requested "
        "content shortly. Please allow up to five seconds before the check completes.</p>"
        "</body></html>"
    )
    f, _ = make(tmp_path, html_ok(challenge))
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "blocked"
    assert r.text is None


def test_thin_page_is_unavailable_too_short(tmp_path):
    thin = "<html><body><p>We are a small team building accounting software for clinics.</p></body></html>"
    f, _ = make(tmp_path, html_ok(thin))
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "too_short"
    assert r.text is None


def test_thin_page_chars_is_extracted_length_and_text_none(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: None)
    f, _ = make(tmp_path, html_ok(f"<html><body><p>{'a' * 150}</p></body></html>"))
    r = f.fetch(URL)
    assert r.status == "unavailable" and r.reason == "too_short"
    assert r.text is None and r.chars == 150

    again = f.fetch(URL)
    assert again.from_cache is True and again.text is None and again.chars == 150

    ok, _ = make(tmp_path / "ok", html_ok())
    page = ok.fetch(URL)
    assert page.status == "ok" and page.chars == len(page.text)


def test_page_gate_reasons():
    from outreach.models import PageResult
    from outreach.pagegate import (
        BLOCK_MAX_CHARS,
        MIN_PAGE_CHARS,
        is_usable,
        looks_blocked,
        page_gate,
        same_site,
    )

    assert MIN_PAGE_CHARS == 400 and BLOCK_MAX_CHARS == 2000
    assert page_gate(None) == "empty" and page_gate("") == "empty" and page_gate("  \n ") == "empty"
    blocked = ("Just a moment... Checking your browser " + "wait " * 80)[:300]
    assert len(blocked) == 300 and page_gate(blocked) == "blocked"
    paragraph = ("We build accounting software for small clinics and their finance teams. " * 3)[:120]
    assert len(paragraph) == 120 and page_gate(paragraph) == "too_short"
    assert page_gate(SAMPLE_PAGE_TEXT) is None
    article = ("Plain sentence about our product and customers. " * 110) + " captcha " + "More text. " * 20
    assert len(article) > 5000 and "captcha" in article and page_gate(article) is None
    assert looks_blocked("Access denied " * 5) is True and looks_blocked(article) is False

    ok = PageResult(url=URL, status="ok", text=SAMPLE_PAGE_TEXT, chars=len(SAMPLE_PAGE_TEXT))
    assert is_usable(ok) is True
    assert is_usable(ok.model_copy(update={"text": blocked})) is False
    assert is_usable(ok.model_copy(update={"status": "unavailable"})) is False
    assert is_usable(ok.model_copy(update={"text": None})) is False

    assert same_site("example.com", "example.com")
    assert same_site("WWW.Example.com.", "example.com")
    assert same_site("trust.example.com", "example.com")
    assert not same_site("notexample.com", "example.com")
    assert not same_site("example.com.evil.io", "example.com")
    assert not same_site("jobs.lever.co", "example.com")
