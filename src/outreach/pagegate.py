"""The single usable-content gate and the same-site scope rule (SCR-02).

A page is usable only when its extracted text is long enough to carry real content and does
not look like a bot-block or challenge page. Both the fetcher (which marks gated pages
unavailable) and `stages.usable_pages` (which re-checks at the extract call site) use the
functions here, so the thresholds and the scope rule have exactly one definition.

Pure: stdlib plus the models module, no I/O.
"""

from __future__ import annotations

from outreach.models import PageResult

MIN_PAGE_CHARS = 400
BLOCK_MAX_CHARS = 2000
BLOCK_SIGNATURES = (
    "just a moment",
    "checking your browser",
    "enable javascript",
    "please enable cookies",
    "access denied",
    "attention required",
    "verify you are human",
    "are you a robot",
    "captcha",
    "cf-chl",
    "ddos protection",
    "request blocked",
    "unusual traffic",
)


def looks_blocked(text: str) -> bool:
    """True for a short page carrying a challenge phrase. Long pages are never "blocked":
    a real article may legitimately mention a captcha."""
    lowered = text.lower()
    return len(text) < BLOCK_MAX_CHARS and any(sig in lowered for sig in BLOCK_SIGNATURES)


def page_gate(text: str | None) -> str | None:
    """None when the text is usable, else a machine reason: empty, blocked or too_short."""
    if text is None or not text.strip():
        return "empty"
    if looks_blocked(text):
        return "blocked"
    if len(text.strip()) < MIN_PAGE_CHARS:
        return "too_short"
    return None


def is_usable(page: PageResult) -> bool:
    return page.status == "ok" and page_gate(page.text) is None


def same_site(host: str, site: str) -> bool:
    """A host is in scope when it is the input domain or a subdomain of it, so `www.` and
    `trust.` are in and third-party hosts (an ATS, a CDN) are out."""
    host = host.lower().rstrip(".")
    site = site.lower().rstrip(".")
    return bool(host) and bool(site) and (host == site or host.endswith("." + site))
