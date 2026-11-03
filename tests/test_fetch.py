"""PageFetcher: caching, size and text caps, HTML-only, error handling. No real network."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

import outreach.fetch as fetch_mod
from conftest import SAMPLE_HTML, SAMPLE_PAGE_TEXT
from outreach.fetch import MAX_BYTES, MAX_CHARS, USER_AGENT, PageFetcher

URL = "https://example.com/"


def make(tmp_path, handler):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return PageFetcher(tmp_path / "pages", http=http), calls


def html_ok(body: str = SAMPLE_HTML, ctype: str = "text/html; charset=utf-8"):
    return lambda request: httpx.Response(200, content=body.encode(), headers={"content-type": ctype})


def cache_file(tmp_path, url=URL):
    return tmp_path / "pages" / f"{hashlib.sha1(url.encode()).hexdigest()}.json"


def test_fetch_ok_page_is_cached_and_second_fetch_makes_no_request(tmp_path):
    f, calls = make(tmp_path, html_ok())
    first = f.fetch(URL)
    assert first.status == "ok" and first.from_cache is False and first.text
    assert len(calls) == 1
    assert cache_file(tmp_path).exists()

    second = f.fetch(URL)
    assert second.from_cache is True
    assert second.text == first.text
    assert len(calls) == 1
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
    assert len(calls) == 1


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
