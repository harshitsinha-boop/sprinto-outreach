"""Polite single-page fetcher with a disk cache (FND-03 support, success criterion 5).

Pages are cached under `<cache_dir>/<sha1(url)>.json` so a rerun of the same domain
re-uses the exact same text, which keeps the LLM prompt (and therefore its cache key)
identical. Bounded on every axis: 10 s read / 5 s connect timeout, streamed body cap,
HTML only, extracted text cut to MAX_CHARS.

Invariant: every PageResult with status "ok" has `chars == len(text)` computed AFTER the
MAX_CHARS cut, because `stages.usable_pages` filters on `chars` and the model default is 0.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import trafilatura
from bs4 import BeautifulSoup

from outreach.cache import atomic_write_json, read_json
from outreach.models import PageResult

USER_AGENT = "sprinto-outreach/0.1 (polite single-page fetch)"
MAX_BYTES = 1_500_000
MAX_CHARS = 8000
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _extract_text(html: str, url: str) -> str:
    text: str | None
    try:
        text = trafilatura.extract(
            html, url=url, output_format="markdown", favor_recall=True
        )
    except Exception:  # trafilatura can raise on malformed markup; fall through to the fallback
        text = None
    if text and text.strip():
        return text.strip()
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


class PageFetcher:
    def __init__(self, cache_dir: Path | None, *, http: httpx.Client | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._http = http or httpx.Client(timeout=TIMEOUT)
        self.http_calls = 0

    def _path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"

    def fetch(self, url: str) -> PageResult:
        path = self._path(url)
        if path is not None:
            cached = read_json(path)
            if cached is not None:
                page = PageResult(**cached)
                updates: dict = {"from_cache": True}
                if page.status == "ok" and page.text is not None:
                    updates["chars"] = len(page.text)
                return page.model_copy(update=updates)

        self.http_calls += 1
        try:
            result = self._fetch_live(url)
        except httpx.HTTPError as e:
            return PageResult(url=url, status="error", error=f"{type(e).__name__}: {e}")

        if path is not None and result.status in ("ok", "unavailable"):
            atomic_write_json(path, result.model_dump())
        return result

    def _fetch_live(self, url: str) -> PageResult:
        with self._http.stream(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=TIMEOUT,
        ) as resp:
            code = resp.status_code
            if code >= 500 or code == 429:
                return PageResult(url=url, status="error", error=f"HTTP {code}")
            if not 200 <= code < 300:
                return PageResult(url=url, status="unavailable", error=f"HTTP {code}")
            ctype = resp.headers.get("content-type", "").lower()
            if "text/html" not in ctype:
                return PageResult(
                    url=url, status="unavailable", error=f"content-type {ctype or 'missing'}"
                )
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) >= MAX_BYTES:
                    break
            encoding = resp.encoding or "utf-8"
        html = bytes(buf[:MAX_BYTES]).decode(encoding, errors="replace")
        text = _extract_text(html, url)[:MAX_CHARS]
        if not text:
            return PageResult(url=url, status="unavailable", error="no extractable text")
        return PageResult(url=url, status="ok", text=text, chars=len(text))
