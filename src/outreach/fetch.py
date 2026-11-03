"""Polite, guarded single-page fetcher with a disk cache (SCR-01, SCR-02).

Every request is bounded and checked before and while it runs:

* only http(s) URLs on the input site are requested (`same_site`), never a host that resolves
  to a non-public address (SSRF guard, every redirect hop included);
* robots.txt is fetched once per host with the project user agent and honoured per RFC 9309
  (a 4xx robots.txt allows everything, a 5xx or 429 or a transport error stops the host);
* redirects are followed by hand: at most MAX_REDIRECTS hops, each one same-site;
* 10 s read / 5 s connect timeouts, a streamed 1.5 MB body cap, a 20 s wall-clock deadline
  and a 1 s politeness gap between requests to one host;
* hidden elements, comments, scripts and styles are stripped before any text is extracted,
  so hidden text can never reach an LLM prompt, and nav links are captured from what is left;
* a page with too little text or a block/challenge signature is returned as `unavailable`
  with a reason (`pagegate.page_gate`).

Pages are cached under `<cache_dir>/<sha1(url)>.json` so a rerun makes zero requests. Entries
carry GUARD_VERSION: an entry without the current version (every Phase 1 entry) is a miss and
is fetched again through every guard. Bump GUARD_VERSION whenever a guard changes.

Invariant: `chars` is the extracted character count (after the MAX_CHARS cut) for ok and
unavailable pages alike, and `chars == len(text)` for ok pages.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from bs4 import BeautifulSoup, Comment

from outreach.cache import atomic_write_json, read_json
from outreach.models import Link, PageResult
from outreach.pagegate import page_gate, same_site

__all__ = [
    "FETCH_DEADLINE_S",
    "GUARD_VERSION",
    "MAX_REDIRECTS",
    "POLITE_INTERVAL_S",
    "PageFetcher",
    "is_public_address",
    "page_gate",
    "same_site",
]

USER_AGENT = "sprinto-outreach/0.1 (polite single-page fetch)"
MAX_BYTES = 1_500_000
MAX_CHARS = 8000
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

GUARD_VERSION = 2
MAX_REDIRECTS = 5
FETCH_DEADLINE_S = 20.0
POLITE_INTERVAL_S = 1.0
ROBOTS_MAX_BYTES = 500_000
MAX_LINKS = 200
LINK_TEXT_CHARS = 80

REDIRECT_CODES = (301, 302, 303, 307, 308)
_REMOVE_TAGS = ["script", "style", "noscript", "template", "iframe", "svg", "object", "embed"]
_HIDDEN_STYLE = re.compile(r"(?<![\w-])(display\s*:\s*none|visibility\s*:\s*hidden)", re.I)


def _system_resolve(host: str) -> list[str]:
    """The distinct addresses the system resolver returns for `host`."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in seen:
            seen.append(addr)
    return seen


def is_public_address(ip: str) -> bool:
    """True only for a globally routable unicast address. IPv4-mapped IPv6 is unwrapped first.

    `is_global` alone misses a few ranges (multicast, for one), so the other classes are
    refused explicitly as well.
    """
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return False
    return addr.is_global


# ---- HTML to text: sanitise first, then extract ----


def _is_hidden(tag) -> bool:
    if tag.has_attr("hidden"):
        return True
    if str(tag.get("aria-hidden", "")).strip().lower() == "true":
        return True
    style = tag.get("style")
    return bool(style and _HIDDEN_STYLE.search(str(style)))


def _sanitise(soup: BeautifulSoup) -> None:
    """Remove everything a human reader would not see (T-02-11). Hidden text is a prompt
    injection channel, so it is dropped before text extraction and link capture."""
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    for tag in soup.find_all("input", attrs={"type": re.compile(r"^\s*hidden\s*$", re.I)}):
        tag.decompose()
    hidden = [tag for tag in soup.find_all(True) if _is_hidden(tag)]
    for tag in hidden:  # extract (not decompose): a hidden child of a hidden parent stays valid
        tag.extract()


def _links(soup: BeautifulSoup, base_url: str) -> list[Link]:
    found: list[Link] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        try:
            absolute = urldefrag(urljoin(base_url, href))[0]
            scheme = urlsplit(absolute).scheme
        except ValueError:
            continue
        if scheme not in ("http", "https") or absolute in seen:
            continue
        seen.add(absolute)
        found.append(Link(url=absolute, text=anchor.get_text(" ", strip=True)[:LINK_TEXT_CHARS]))
        if len(found) >= MAX_LINKS:
            break
    return found


def _extract(html: str, final_url: str) -> tuple[str, list[Link]]:
    soup = BeautifulSoup(html, "lxml")
    _sanitise(soup)
    links = _links(soup, final_url)
    text: str | None
    try:
        text = trafilatura.extract(
            str(soup), url=final_url, output_format="markdown", favor_recall=True
        )
    except Exception:  # trafilatura can raise on malformed markup; fall through to the fallback
        text = None
    if text and text.strip():
        return text.strip(), links
    return soup.get_text(" ", strip=True), links


# ---- the fetcher ----


@dataclass
class _Got:
    """One completed GET (after redirects), or the reason it could not be completed."""

    final_url: str
    code: int = 0
    ctype: str = ""
    body: bytes = b""
    encoding: str = "utf-8"
    failure: PageResult | None = None


@dataclass
class _Robots:
    """A host's robots verdict. `failure` (a PageResult template) means no page on that host
    may be requested; otherwise a missing `parser` means everything is allowed."""

    parser: RobotFileParser | None = None
    failure: PageResult | None = None


class PageFetcher:
    def __init__(
        self,
        cache_dir: Path | None,
        *,
        http: httpx.Client | None = None,
        resolve: Callable[[str], list[str]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float | None = None,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._http = http or httpx.Client(timeout=TIMEOUT)
        self._resolve = resolve
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, _Robots] = {}
        self.http_calls = 0  # page requests, one per hop
        self.robots_calls = 0

    # ---- cache ----

    def _path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"

    def _robots_path(self, origin: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{hashlib.sha1(f'robots:{origin}'.encode()).hexdigest()}.json"

    @staticmethod
    def _read_entry(path: Path | None) -> dict | None:
        """The stored entry, or None for a missing, unreadable or wrong-version file."""
        if path is None:
            return None
        try:
            data = read_json(path)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("guard_version") != GUARD_VERSION:
            return None
        return data

    def _cached_page(self, url: str) -> PageResult | None:
        data = self._read_entry(self._path(url))
        if data is None:
            return None
        data.pop("guard_version", None)
        try:
            page = PageResult(**data)
        except ValueError:
            return None
        updates: dict = {"from_cache": True}
        if page.status == "ok" and page.text is not None:
            updates["chars"] = len(page.text)
        return page.model_copy(update=updates)

    # ---- robots.txt (RFC 9309) ----

    @staticmethod
    def _parse_robots(text: str) -> _Robots:
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return _Robots(parser=parser)

    def _robots_for(self, origin: str, site: str) -> _Robots:
        memo = self._robots.get(origin)
        if memo is not None:
            return memo
        verdict = self._robots_from_disk(origin) or self._robots_fetch(origin, site)
        self._robots[origin] = verdict
        return verdict

    def _robots_from_disk(self, origin: str) -> _Robots | None:
        data = self._read_entry(self._robots_path(origin))
        if data is None:
            return None
        code, text = data.get("status"), data.get("text")
        if not isinstance(code, int) or not isinstance(text, str):
            return None
        return self._robots_verdict(code, text)

    @classmethod
    def _robots_verdict(cls, code: int, text: str) -> _Robots:
        if 200 <= code < 300:
            return cls._parse_robots(text)
        if 400 <= code < 500 and code != 429:  # RFC 9309: no robots.txt (or access refused) means no rules
            return _Robots()
        return _Robots(
            failure=PageResult(
                url="", status="error", reason="robots_unreachable", error=f"robots.txt HTTP {code}"
            )
        )

    def _robots_fetch(self, origin: str, site: str) -> _Robots:
        got = self._get(
            f"{origin}/robots.txt", site, max_bytes=ROBOTS_MAX_BYTES, html_only=False, robots=True
        )
        if got.failure is not None:
            return _Robots(failure=got.failure)  # never stored: a transport error is not a verdict
        text = got.body.decode(got.encoding or "utf-8", errors="replace")
        verdict = self._robots_verdict(got.code, text)
        path = self._robots_path(origin)
        # Only a definite answer is stored. A 5xx or 429 is transient and is retried next run.
        if path is not None and got.code < 500 and got.code != 429:
            atomic_write_json(
                path, {"status": got.code, "text": text, "guard_version": GUARD_VERSION}
            )
        return verdict

    # ---- one guarded GET with manual redirects ----

    def _wait_politely(self, host: str) -> None:
        interval = self._min_interval if self._min_interval is not None else POLITE_INTERVAL_S
        last = self._last_request.get(host)
        if last is not None and interval > 0:
            elapsed = self._clock() - last
            if elapsed < interval:
                self._sleep(interval - elapsed)
        self._last_request[host] = self._clock()

    def _get(self, url: str, site: str, *, max_bytes: int, html_only: bool, robots: bool = False) -> _Got:
        start = self._clock()
        resolve = self._resolve or _system_resolve
        current = url
        redirects = 0

        def fail(status: str, reason: str, error: str) -> _Got:
            return _Got(
                final_url=current,
                failure=PageResult(
                    url=url,
                    status=status,  # type: ignore[arg-type]
                    reason=reason,
                    error=error,
                    final_url=current,
                ),
            )

        while True:
            host = (urlsplit(current).hostname or "").lower()
            try:
                addresses = resolve(host)
            except socket.gaierror as e:
                return fail("error", "dns_failure", f"gaierror: {e}")
            if not addresses or not all(is_public_address(a) for a in addresses):
                return fail("unavailable", "private_address", f"{host} resolves to a non-public address")

            self._wait_politely(host)
            if robots:
                self.robots_calls += 1
            else:
                self.http_calls += 1
            try:
                with self._http.stream(
                    "GET",
                    current,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=False,
                    timeout=TIMEOUT,
                ) as resp:
                    code = resp.status_code
                    location = resp.headers.get("location")
                    if code in REDIRECT_CODES and location:
                        try:
                            target = str(httpx.URL(current).join(location))
                            parts = urlsplit(target)
                            target_host = (parts.hostname or "").lower()
                        except (httpx.InvalidURL, ValueError):
                            return fail("unavailable", "off_site_redirect", "redirect to an invalid target")
                        if parts.scheme not in ("http", "https") or not same_site(target_host, site):
                            return fail(
                                "unavailable",
                                "off_site_redirect",
                                f"redirect to {target_host or parts.scheme} leaves {site}",
                            )
                        redirects += 1
                        if redirects > MAX_REDIRECTS:
                            return fail(
                                "unavailable", "too_many_redirects", f"more than {MAX_REDIRECTS} redirects"
                            )
                        current = target
                        continue

                    ctype = resp.headers.get("content-type", "").lower()
                    body = b""
                    wanted = 200 <= code < 300 and (not html_only or "text/html" in ctype)
                    if wanted:
                        buf = bytearray()
                        for chunk in resp.iter_bytes():
                            buf.extend(chunk)
                            if self._clock() - start > FETCH_DEADLINE_S:
                                return fail("error", "deadline", f"exceeded {FETCH_DEADLINE_S:g}s")
                            if len(buf) >= max_bytes:
                                break
                        body = bytes(buf[:max_bytes])
                    return _Got(
                        final_url=current,
                        code=code,
                        ctype=ctype,
                        body=body,
                        encoding=resp.encoding or "utf-8",
                    )
            except httpx.HTTPError as e:
                return fail("error", "transport_error", f"{type(e).__name__}: {e}")

    # ---- public entry point ----

    def fetch(self, url: str, site: str | None = None) -> PageResult:
        try:
            parts = urlsplit(url)
            scheme = parts.scheme.lower()
            host = (parts.hostname or "").lower()
            port = parts.port
        except ValueError:
            return PageResult(url=url, status="unavailable", reason="bad_scheme", error="invalid URL")
        if scheme not in ("http", "https") or not host:
            return PageResult(
                url=url,
                status="unavailable",
                reason="bad_scheme",
                error=f"only http and https URLs are fetched, got {scheme or 'none'!r}",
            )
        site = (site or host.removeprefix("www.")).lower().rstrip(".")
        if not same_site(host, site):
            return PageResult(
                url=url, status="unavailable", reason="off_site", error=f"{host} is outside {site}"
            )

        cached = self._cached_page(url)
        if cached is not None:
            return cached

        origin = f"{scheme}://{host}" + (f":{port}" if port else "")
        robots = self._robots_for(origin, site)
        if robots.failure is not None:
            return robots.failure.model_copy(update={"url": url})  # not cached
        if robots.parser is not None and not robots.parser.can_fetch(USER_AGENT, url):
            result = PageResult(
                url=url,
                status="unavailable",
                reason="robots_disallowed",
                error="disallowed by robots.txt",
            )
        else:
            result = self._fetch_live(url, site)

        path = self._path(url)
        if path is not None and result.status in ("ok", "unavailable"):
            atomic_write_json(path, {**result.model_dump(), "guard_version": GUARD_VERSION})
        return result

    def _fetch_live(self, url: str, site: str) -> PageResult:
        got = self._get(url, site, max_bytes=MAX_BYTES, html_only=True)
        if got.failure is not None:
            return got.failure
        final_url = got.final_url
        code = got.code
        if code >= 500 or code == 429:
            return PageResult(
                url=url, status="error", reason=f"http_{code}", error=f"HTTP {code}", final_url=final_url
            )
        if not 200 <= code < 300:
            return PageResult(
                url=url,
                status="unavailable",
                reason=f"http_{code}",
                error=f"HTTP {code}",
                final_url=final_url,
            )
        if "text/html" not in got.ctype:
            return PageResult(
                url=url,
                status="unavailable",
                reason="not_html",
                error=f"content-type {got.ctype or 'missing'}",
                final_url=final_url,
            )

        html = got.body.decode(got.encoding, errors="replace")
        text, links = _extract(html, got.final_url)
        text = text[:MAX_CHARS]
        extracted_chars = len(text)  # taken before any field is cleared
        reason = page_gate(text)
        if reason is not None:
            return PageResult(
                url=url,
                status="unavailable",
                text=None,
                chars=extracted_chars,
                reason=reason,
                error=f"page gate: {reason}",
                final_url=final_url,
                links=links,
            )
        return PageResult(
            url=url,
            status="ok",
            text=text,
            chars=extracted_chars,
            final_url=final_url,
            links=links,
        )
