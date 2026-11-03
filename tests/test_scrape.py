"""Multi-page discovery: six page kinds, harvested links, scope, duplicates, caps and the
batch-level guarantee that an unusable page never reaches the LLM. All offline."""

from __future__ import annotations

import httpx
import pytest

import outreach.scrape as scrape_mod
from conftest import SAMPLE_HTML, SAMPLE_PAGE_TEXT
from outreach.models import Link, PageResult
from outreach.runner import run_batch
from outreach.stages import DomainUnreachable, StopStage, stage_scrape, usable_pages

DOMAIN = "example.com"
HOME = f"https://{DOMAIN}/"
KINDS = ["home", "about", "careers", "security", "pricing", "customers"]
CHALLENGE = (
    "Just a moment... Checking your browser before accessing the site. This process is "
    "automatic and your browser will redirect shortly. Please verify you are human and "
    "enable JavaScript and cookies to continue. " * 3
)


def text_for(label: str) -> str:
    return f"{label}: " + SAMPLE_PAGE_TEXT


def ok(url: str, text: str | None = None, links: list[Link] | None = None) -> PageResult:
    text = text if text is not None else text_for(url)
    return PageResult(url=url, status="ok", text=text, chars=len(text), links=links or [])


def not_found(url: str) -> PageResult:
    return PageResult(url=url, status="unavailable", reason="http_404", error="HTTP 404")


class ScriptedFetcher:
    """Serves `by_url`; anything else gets `default` (re-addressed to the asked URL) or a 404."""

    def __init__(self, by_url: dict[str, PageResult] | None = None, default: PageResult | None = None,
                 on_fetch=None):
        self.by_url = by_url or {}
        self.default = default
        self.on_fetch = on_fetch
        self.calls: list[tuple[str, str | None]] = []

    def fetch(self, url, site=None):
        self.calls.append((url, site))
        if self.on_fetch is not None:
            self.on_fetch(url)
        if url in self.by_url:
            return self.by_url[url]
        if self.default is not None:
            return self.default.model_copy(update={"url": url})
        return not_found(url)

    @property
    def urls(self) -> list[str]:
        return [u for u, _ in self.calls]


def six_kind_pages() -> dict[str, PageResult]:
    urls = [HOME] + [f"https://{DOMAIN}{p}" for p in ("/about", "/careers", "/security", "/pricing", "/customers")]
    return {u: ok(u) for u in urls}


def test_scrape_fetches_home_and_five_page_kinds():
    fetcher = ScriptedFetcher(six_kind_pages())

    out = scrape_mod.scrape_domain(fetcher, DOMAIN)

    assert out.usable == 6 and out.kinds_found == KINDS
    assert [p.kind for p in out.pages] == KINDS
    assert out.fetches == 6 and out.skipped_kinds == []
    assert all(site == DOMAIN for _, site in fetcher.calls)
    assert fetcher.urls[0] == HOME


def test_harvested_nav_link_is_preferred_over_fallback_path():
    links = [
        Link(url="https://example.com/company/about-us", text="About"),
        Link(url="https://trust.example.com/", text="Trust Center"),
    ]
    fetcher = ScriptedFetcher(
        {
            HOME: ok(HOME, links=links),
            "https://example.com/company/about-us": ok("https://example.com/company/about-us"),
            "https://trust.example.com/": ok("https://trust.example.com/"),
        }
    )

    out = scrape_mod.scrape_domain(fetcher, DOMAIN)

    assert scrape_mod.candidate_urls(DOMAIN, "about", links)[0] == "https://example.com/company/about-us"
    assert scrape_mod.candidate_urls(DOMAIN, "security", links)[0] == "https://trust.example.com/"
    assert fetcher.urls[1] == "https://example.com/company/about-us"
    assert "https://example.com/about" not in fetcher.urls  # the harvested page was usable
    assert "https://trust.example.com/" in fetcher.urls
    assert {"about", "security"} <= set(out.kinds_found)


def test_offsite_ats_link_is_never_fetched():
    links = [Link(url="https://jobs.lever.co/example", text="Careers")]
    fetcher = ScriptedFetcher({HOME: ok(HOME, links=links)})

    scrape_mod.scrape_domain(fetcher, DOMAIN)

    assert all("lever.co" not in u for u in fetcher.urls)
    assert scrape_mod.candidate_urls(DOMAIN, "careers", links) == [
        "https://example.com/careers",
        "https://example.com/jobs",
    ]
    assert "https://example.com/careers" in fetcher.urls and "https://example.com/jobs" in fetcher.urls


def test_candidate_urls_dedupe_by_canonical_form_and_cap_harvested_links():
    links = [
        Link(url="https://www.example.com/about/", text="About"),
        Link(url="https://example.com/about?ref=nav#team", text="About us"),
        Link(url="https://example.com/team", text="Team"),
    ]
    got = scrape_mod.candidate_urls(DOMAIN, "about", links)
    # at most two harvested links, then the fixed paths; one entry per canonical URL, so the
    # second harvested link and the fixed /about collapse into the first
    assert got == [
        "https://www.example.com/about/",
        "https://example.com/company",
        "https://example.com/about-us",
    ]
    canon = [scrape_mod.canonical(u) for u in got]
    assert len(canon) == len(set(canon))
    # an anchor-text match works even when the path says nothing
    text_only = [Link(url="https://example.com/x1", text="Our Customers")]
    assert scrape_mod.candidate_urls(DOMAIN, "customers", text_only)[0] == "https://example.com/x1"


def test_duplicate_content_is_marked_unavailable():
    fetcher = ScriptedFetcher({HOME: ok(HOME)}, default=ok(HOME))  # every path serves the homepage

    out = scrape_mod.scrape_domain(fetcher, DOMAIN)

    assert out.usable == 1 and out.kinds_found == ["home"]
    dupes = [p for p in out.pages if p.kind != "home"]
    assert dupes and all(p.status == "unavailable" and p.reason == "duplicate_content" for p in dupes)
    assert all(p.text is None for p in dupes)
    assert out.fetches == len(out.pages) == 13


def test_attempt_and_fetch_caps_hold():
    many = [Link(url=f"https://example.com/about-{i}", text="About") for i in range(10)]
    fetcher = ScriptedFetcher({HOME: ok(HOME, links=many)})  # every other page is a 404

    out = scrape_mod.scrape_domain(fetcher, DOMAIN)

    per_kind = {k: sum(1 for p in out.pages if p.kind == k) for k in KINDS[1:]}
    assert max(per_kind.values()) <= scrape_mod.MAX_ATTEMPTS_PER_KIND == 3
    assert out.fetches <= scrape_mod.MAX_FETCHES_PER_DOMAIN == 14 and out.usable == 1
    assert out.fetches == len(out.pages) == len(fetcher.calls)


def test_fetch_cap_stops_discovery_and_lists_skipped_kinds(monkeypatch):
    monkeypatch.setattr(scrape_mod, "MAX_FETCHES_PER_DOMAIN", 5)
    fetcher = ScriptedFetcher({HOME: ok(HOME)})

    out = scrape_mod.scrape_domain(fetcher, DOMAIN)

    assert out.fetches == 5 == len(fetcher.calls)
    assert out.skipped_kinds == ["security", "pricing", "customers"]


def test_attempt_cap_is_per_kind(monkeypatch):
    monkeypatch.setattr(scrape_mod, "MAX_ATTEMPTS_PER_KIND", 1)

    out = scrape_mod.scrape_domain(ScriptedFetcher({HOME: ok(HOME)}), DOMAIN)

    assert [sum(1 for p in out.pages if p.kind == k) for k in KINDS[1:]] == [1, 1, 1, 1, 1]


def test_time_budget_skips_remaining_kinds():
    state = {"t": 0.0}

    def jump(url):
        state["t"] = scrape_mod.SCRAPE_BUDGET_S + 1.0  # the homepage fetch used up the budget

    fetcher = ScriptedFetcher({HOME: ok(HOME)}, on_fetch=jump)

    out = scrape_mod.scrape_domain(fetcher, DOMAIN, clock=lambda: state["t"])

    assert out.fetches == 1 and len(fetcher.calls) == 1
    assert out.skipped_kinds == ["about", "careers", "security", "pricing", "customers"]
    assert out.usable == 1


def test_homepage_error_short_circuits():
    err = PageResult(url=HOME, status="error", reason="transport_error", error="ConnectError: no route")
    fetcher = ScriptedFetcher({HOME: err})

    out = scrape_mod.scrape_domain(fetcher, DOMAIN)

    assert len(fetcher.calls) == 1
    assert out.fetches == 1 and out.usable == 0 and [p.status for p in out.pages] == ["error"]
    assert out.pages[0].kind == "home"


def test_insufficient_data_detail_counts_reasons(ctx):
    thin = "too short to be a real page"
    ctx.fetcher = ScriptedFetcher(default=ok("x", thin))
    with pytest.raises(StopStage) as thin_all:
        stage_scrape(ctx, DOMAIN, {})
    assert thin_all.value.reason == "insufficient_data"
    assert thin_all.value.detail == "0 usable of 13 pages (too_short=13)"

    ctx.fetcher = ScriptedFetcher({HOME: ok(HOME, thin)})  # the rest are 404s
    with pytest.raises(StopStage) as mixed:
        stage_scrape(ctx, DOMAIN, {})
    assert mixed.value.detail == "0 usable of 13 pages (http_404=12, too_short=1)"

    ctx.fetcher = ScriptedFetcher({HOME: PageResult(url=HOME, status="error", error="ConnectError: x")})
    with pytest.raises(DomainUnreachable):
        stage_scrape(ctx, DOMAIN, {})


def test_usable_pages_reapplies_the_gate_for_any_fetcher():
    pages = [ok(HOME), ok("https://example.com/x", CHALLENGE), ok("https://example.com/y", "tiny"),
             not_found("https://example.com/z")]
    assert [p.url for p in usable_pages(pages)] == [HOME]


def test_blocked_page_never_reaches_llm_through_run_batch(ctx):
    # A fetcher that does NOT gate: a 200 challenge page for the homepage, 404 for the rest.
    ctx.fetcher = ScriptedFetcher({HOME: ok(HOME, CHALLENGE)})

    summary = run_batch([DOMAIN], ctx)

    row = summary.rows[0]
    assert row.outcome == "insufficient_data"
    assert "blocked=1" in row.detail and "http_404=12" in row.detail
    assert ctx.llm.calls == []


def test_only_usable_pages_reach_extract_prompt(ctx):
    pricing = "https://example.com/pricing"
    ctx.fetcher = ScriptedFetcher({HOME: ok(HOME, SAMPLE_PAGE_TEXT), pricing: ok(pricing, CHALLENGE)})

    summary = run_batch([DOMAIN], ctx)

    assert summary.rows[0].outcome == "qualified"
    extract = next(c for c in ctx.llm.calls if c["purpose"] == "extract")
    assert f'<page url="{HOME}" kind="home">' in extract["prompt"]
    assert pricing not in extract["prompt"]
    assert "verify you are human" not in extract["prompt"]


def test_dead_domain_is_failed_through_run_batch(ctx, settings):
    from outreach.fetch import PageFetcher

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dead.example":
            raise httpx.ConnectError("name resolution failed")
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=SAMPLE_HTML.encode(), headers={"content-type": "text/html"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    ctx.fetcher = PageFetcher(settings.cache_dir / "pages", http=http)

    summary = run_batch(["dead.example", "example.com"], ctx)

    assert [r.outcome for r in summary.rows] == ["failed", "qualified"]
    assert "ConnectError" in summary.rows[0].detail
    assert summary.aborted is False
