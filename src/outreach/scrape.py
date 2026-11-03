"""Multi-page discovery for one domain (SCR-01): the homepage plus about, careers,
security or trust, pricing and customers pages.

Takes the fetcher as a parameter and never imports fetch.py or an SDK. Every fetch passes
`site=domain`, so the fetcher refuses redirects and links that leave the site. Candidate URLs
come from the homepage's own nav links first and fixed paths second; every kind is bounded
(attempts per kind, fetches and seconds per domain) so a hostile or sprawling site cannot
turn one domain into an open-ended crawl.
"""

from __future__ import annotations

import hashlib
import time
from urllib.parse import urlsplit

from outreach.models import Link, ScrapeOutput
from outreach.pagegate import is_usable, same_site

PAGE_KINDS = ("home", "about", "careers", "security", "pricing", "customers")

FALLBACK_PATHS: dict[str, tuple[str, ...]] = {
    "home": ("/",),
    "about": ("/about", "/company", "/about-us"),
    "careers": ("/careers", "/jobs"),
    "security": ("/security", "https://trust.{domain}/", "/trust"),
    "pricing": ("/pricing", "/plans"),
    "customers": ("/customers", "/case-studies"),
}

KIND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "about": ("about", "company", "team"),
    "careers": ("careers", "jobs", "join", "hiring"),
    "security": ("security", "trust", "compliance"),
    "pricing": ("pricing", "plans"),
    "customers": ("customers", "case-studies", "case studies", "stories"),
}

MAX_HARVESTED_PER_KIND = 2
MAX_ATTEMPTS_PER_KIND = 3
MAX_FETCHES_PER_DOMAIN = 14
SCRAPE_BUDGET_S = 60.0


def canonical(url: str) -> str:
    """Identity of a page for duplicate-URL checks: lowercase host without `www.`, path
    without a trailing slash; scheme, query and fragment are ignored."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def candidate_urls(domain: str, kind: str, home_links: list[Link]) -> list[str]:
    """Harvested same-site nav links first (at most two, in page order), then the fixed paths."""
    keywords = KIND_KEYWORDS.get(kind, ())
    harvested: list[str] = []
    for link in home_links:
        parts = urlsplit(link.url)
        if not parts.hostname or not same_site(parts.hostname, domain):
            continue
        if any(k in parts.path.lower() or k in link.text.lower() for k in keywords):
            harvested.append(link.url)
            if len(harvested) == MAX_HARVESTED_PER_KIND:
                break
    fixed = [
        path.replace("{domain}", domain) if path.startswith("http") else f"https://{domain}{path}"
        for path in FALLBACK_PATHS[kind]
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for url in harvested + fixed:
        key = canonical(url)
        if key not in seen:
            seen.add(key)
            ordered.append(url)
    return ordered


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def scrape_domain(fetcher, domain: str, *, clock=time.monotonic) -> ScrapeOutput:
    start = clock()
    pages = []
    fetched: set[str] = set()
    seen_hashes: set[str] = set()
    kinds_found: list[str] = []
    skipped: list[str] = []
    fetches = 0

    def take(url: str, kind: str):
        """Fetch one URL, tag it, and demote a usable page whose text repeats an earlier one."""
        nonlocal fetches
        fetches += 1
        fetched.add(canonical(url))
        page = fetcher.fetch(url, site=domain).model_copy(update={"kind": kind})
        if page.final_url:
            fetched.add(canonical(page.final_url))
        if is_usable(page):
            digest = _text_hash(page.text or "")
            if digest in seen_hashes:  # a soft 404 or SPA shell serving the homepage everywhere
                page = page.model_copy(
                    update={
                        "status": "unavailable",
                        "reason": "duplicate_content",
                        "error": "same text as an earlier page",
                        "text": None,
                    }
                )
            else:
                seen_hashes.add(digest)
        pages.append(page)
        return page

    home = take(f"https://{domain}/", "home")
    if home.status == "error":  # the site is unreachable: do not spend more requests on it
        return ScrapeOutput(pages=pages, usable=0, fetches=fetches)
    if is_usable(home):
        kinds_found.append("home")

    others = PAGE_KINDS[1:]
    for index, kind in enumerate(others):
        stop = fetches >= MAX_FETCHES_PER_DOMAIN or clock() - start > SCRAPE_BUDGET_S
        attempts = 0
        for url in candidate_urls(domain, kind, home.links)[:MAX_ATTEMPTS_PER_KIND]:
            if canonical(url) in fetched:
                continue
            stop = fetches >= MAX_FETCHES_PER_DOMAIN or clock() - start > SCRAPE_BUDGET_S
            if stop:
                break
            attempts += 1
            if is_usable(take(url, kind)):
                kinds_found.append(kind)
                break
        if stop:
            # the current kind counts as untried only when nothing was fetched for it
            skipped.extend(others[index:] if attempts == 0 else others[index + 1 :])
            break

    usable = sum(1 for p in pages if is_usable(p))
    return ScrapeOutput(
        pages=pages,
        usable=usable,
        kinds_found=kinds_found,
        fetches=fetches,
        skipped_kinds=skipped,
    )
