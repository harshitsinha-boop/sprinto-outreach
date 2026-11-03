"""Batch runner: loader, isolation, systemic abort, outcome mapping and rendering. All offline.

Every local fetcher double takes `fetch(self, url, site=None)`: Plan 02-02 calls
`fetch(url, site=domain)`, and a one-argument stub would then raise TypeError.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from conftest import CANARY_ENV, SAMPLE_PAGE_TEXT, FakeLLM
from outreach.hunter import HunterAuthError, HunterQuotaError
from outreach.llm import LLMAuthError, LLMQuotaError
from outreach.models import OUTCOMES, BatchRow, PageResult, RunRecord, StageRecord
from outreach.runner import (
    MAX_BATCH_DOMAINS,
    SYSTEMIC_ERRORS,
    BatchInputError,
    load_domains,
    outcome_for,
    render_summary,
    run_batch,
)
from outreach.send import SendError


def _ok(url: str, text: str = SAMPLE_PAGE_TEXT) -> PageResult:
    return PageResult(url=url, status="ok", text=text, chars=len(text))


def _in(host: str | None, names: set[str]) -> bool:
    """True when `host` is one of `names` or a subdomain of one (the scraper also asks for
    trust.<domain>, which belongs to the same site)."""
    return any(host == n or (host or "").endswith("." + n) for n in names)


class RoutingFetcher:
    """Per-host behaviour: dead hosts error at transport level, boom hosts raise, thin hosts
    return a short page, everything else returns the sample page."""

    def __init__(self, *, dead=(), boom=(), thin=()):
        self.dead, self.boom, self.thin = set(dead), set(boom), set(thin)
        self.calls: list[str] = []
        self.scopes: set[str] = set()  # the input domains the scraper asked about

    def fetch(self, url, site=None):
        self.calls.append(url)
        host = urlparse(url).hostname
        self.scopes.add(site or host)
        if _in(host, self.dead):
            return PageResult(url=url, status="error", error="ConnectError: dns failure")
        if _in(host, self.boom):
            raise RuntimeError(f"boom on {host}")
        if _in(host, self.thin):
            return _ok(url, "x" * 30)
        return _ok(url)

    def hosts(self) -> set[str]:
        return {urlparse(u).hostname for u in self.calls}


class HunterAuthFailing:
    live_calls_this_process = 0

    def __init__(self):
        self.calls: list[str] = []

    def domain_search(self, domain):
        self.calls.append(domain)
        raise HunterAuthError("401 bad key")

    def account(self):
        return {"plan": "x", "reset_date": None, "remaining": None}


FETCHER_CLASSES = [RoutingFetcher]


def _load(tmp_path, text):
    f = tmp_path / "domains.txt"
    f.write_text(text, encoding="utf-8")
    return load_domains(f)


# ---- Task 1 ----


def test_load_domains_normalises_dedupes_and_skips_comments(tmp_path):
    f = tmp_path / "domains.txt"
    f.write_text(
        "# demo set\n"
        "\n"
        "https://WWW.Example.com/about\n"
        "example.com\n"
        "acme.io   # trailing comment\n",
        encoding="utf-8",
    )
    assert load_domains(f) == ["example.com", "acme.io"]


def test_run_batch_runs_every_domain_in_order_and_maps_outcomes(ctx):
    summary = run_batch(["example.com", "example.org"], ctx)

    assert [r.domain for r in summary.rows] == ["example.com", "example.org"]
    assert [r.outcome for r in summary.rows] == ["qualified", "qualified"]
    assert set(summary.counts) == set(OUTCOMES)
    assert summary.counts["qualified"] == 2
    assert summary.mode == "dry_run"
    assert summary.aborted is False
    for row in summary.rows:
        assert row.run_record is not None
        assert json.loads(open(row.run_record).read())["domain"] == row.domain


def test_render_summary_lists_every_domain_and_all_seven_counts(ctx):
    summary = run_batch(["example.com", "example.org"], ctx)
    text = render_summary(summary)

    assert text.splitlines()[0] == "SUMMARY mode=dry_run hunter=fixture"
    assert "example.com" in text
    assert "example.org" in text
    assert (
        "outcomes: qualified=2 disqualified=0 insufficient_data=0 no_contact=0 "
        "rejected_draft=0 sent=0 failed=0"
    ) in text


# ---- Task 2: isolation and unreachable domains ----


def test_unreachable_domain_is_failed_and_batch_continues(ctx):
    ctx.fetcher = RoutingFetcher(dead={"dead.example"})
    summary = run_batch(["dead.example", "example.com"], ctx)

    dead, ok = summary.rows
    assert dead.outcome == "failed"
    assert "scrape" in dead.detail and "DomainUnreachable" in dead.detail
    assert ok.outcome == "qualified"
    rec = ctx.store.load("dead.example")
    assert rec.status == "failed" and rec.failed_stage == "scrape"


def test_thin_page_is_insufficient_data_not_failed(ctx):
    ctx.fetcher = RoutingFetcher(thin={"thin.example"})
    summary = run_batch(["thin.example"], ctx)
    assert summary.rows[0].outcome == "insufficient_data"


def test_stage_exception_is_failed_and_batch_continues(ctx):
    ctx.fetcher = RoutingFetcher(boom={"b.example"})
    summary = run_batch(["a.example", "b.example", "c.example"], ctx)

    assert [r.outcome for r in summary.rows] == ["qualified", "failed", "qualified"]
    assert "RuntimeError" in summary.rows[1].detail
    assert summary.aborted is False


# ---- Task 2: systemic abort ----

SYSTEMIC_CASES = [
    LLMAuthError("bad key"),
    LLMQuotaError("quota"),
    HunterAuthError("bad key"),
    HunterQuotaError("quota"),
    SendError("send refused"),
]


@pytest.mark.parametrize("exc", SYSTEMIC_CASES, ids=lambda e: type(e).__name__)
def test_systemic_error_aborts_batch(ctx, exc):
    ctx.llm = FakeLLM(raise_on={"extract": exc})
    fetcher = RoutingFetcher()
    ctx.fetcher = fetcher
    summary = run_batch(["a.example", "b.example", "c.example"], ctx)

    assert summary.aborted is True
    assert type(exc).__name__ in summary.abort_reason
    assert "a.example" in summary.abort_reason
    a, b, c = summary.rows
    assert a.outcome == "failed" and type(exc).__name__ in a.detail
    for row in (b, c):
        assert row.outcome == "failed"
        assert row.detail == "not run (batch aborted)"
        assert row.run_record is None
    assert fetcher.scopes == {"a.example"}
    assert summary.counts["failed"] == 3


def test_systemic_hunter_auth_error_at_hunter_seam_aborts(ctx):
    ctx.hunter = HunterAuthFailing()
    summary = run_batch(["a.example", "b.example"], ctx)

    assert summary.aborted is True
    assert "HunterAuthError" in summary.abort_reason
    assert ctx.hunter.calls == ["a.example"]
    assert summary.rows[1].detail == "not run (batch aborted)"


def test_abort_reason_is_redacted(ctx):
    canary = CANARY_ENV["GEMINI_API_KEY"]
    ctx.llm = FakeLLM(raise_on={"extract": LLMAuthError(f"API key {canary} rejected")})
    summary = run_batch(["a.example", "b.example"], ctx)

    assert "***" in summary.abort_reason
    assert canary not in summary.abort_reason
    assert canary not in render_summary(summary)
    assert canary not in json.dumps(summary.model_dump(mode="json"))


def test_systemic_errors_are_the_five_documented_types():
    assert {c.__name__ for c in SYSTEMIC_ERRORS} == {
        "LLMAuthError",
        "LLMQuotaError",
        "HunterAuthError",
        "HunterQuotaError",
        "SendError",
    }


# ---- Task 2: outcome mapping ----


def _rec(status, *, stop_reason=None, failed_stage=None, stages=None):
    return RunRecord(
        domain="x.example",
        status=status,
        started_at="t",
        stop_reason=stop_reason,
        failed_stage=failed_stage,
        stages=stages or [],
    )


def _stage(name, status, **kw):
    return StageRecord(name=name, status=status, started_at="t", **kw)


def test_outcome_for_maps_all_seven_outcomes():
    assert outcome_for(_rec("dry_run"))[0] == "qualified"
    sent = _rec("sent", stages=[_stage("send", "ok", output={"mode": "sent", "id": "msg-9"})])
    assert outcome_for(sent) == ("sent", "message id msg-9")
    for reason in ("insufficient_data", "no_contact", "disqualified", "rejected_draft"):
        stopped = _rec(
            "stopped",
            stop_reason=reason,
            stages=[_stage("x", "stopped", output={"reason": reason, "detail": "why"})],
        )
        assert outcome_for(stopped) == (reason, "why")
    failed = _rec(
        "failed",
        failed_stage="draft",
        stages=[_stage("draft", "failed", error="RuntimeError: nope")],
    )
    assert outcome_for(failed) == ("failed", "draft: RuntimeError: nope")
    assert outcome_for(_rec("running"))[0] == "failed"
    for rec in (_rec("dry_run"), sent, failed):
        assert outcome_for(rec)[0] in OUTCOMES


def test_unknown_stop_reason_maps_to_failed():
    rec = _rec("stopped", stop_reason="mystery")
    assert outcome_for(rec) == ("failed", "unknown stop reason mystery")


# ---- Task 2: input hygiene ----


def test_invalid_domain_lines_are_failed_rows(ctx, tmp_path):
    entries = _load(
        tmp_path, "localhost\n10.0.0.1\n[::1]\nexa mple.com\n-bad-.com\ngood.example\n"
    )
    rows = [e for e in entries if isinstance(e, BatchRow)]
    assert len(rows) == 5
    assert [r.detail for r in rows] == [f"invalid domain on line {n}" for n in range(1, 6)]
    assert all(r.outcome == "failed" for r in rows)

    fetcher = RoutingFetcher()
    ctx.fetcher = fetcher
    summary = run_batch(entries, ctx)
    assert fetcher.scopes == {"good.example"}
    assert summary.rows[-1].domain == "good.example"
    assert summary.rows[-1].outcome == "qualified"
    assert summary.counts["failed"] == 5


def test_rejected_lines_keep_file_order_in_summary(ctx, tmp_path):
    entries = _load(tmp_path, "a.example\nlocalhost\nb.example\n")
    ctx.fetcher = RoutingFetcher()
    summary = run_batch(entries, ctx)
    assert [(r.domain, r.outcome) for r in summary.rows] == [
        ("a.example", "qualified"),
        ("localhost", "failed"),
        ("b.example", "qualified"),
    ]

    entries = _load(tmp_path, "a.example\nlocalhost\nb.example\n")
    ctx.llm = FakeLLM(raise_on={"extract": LLMAuthError("bad key")})
    ctx.fetcher = RoutingFetcher()
    aborted = run_batch(entries, ctx)
    assert [r.domain for r in aborted.rows] == ["a.example", "localhost", "b.example"]
    assert aborted.rows[1].detail == "invalid domain on line 2"
    assert aborted.rows[2].detail == "not run (batch aborted)"


def test_batch_cap_rejects_oversized_file(tmp_path):
    ok = "\n".join(f"d{i}.example" for i in range(MAX_BATCH_DOMAINS)) + "\n"
    assert len(_load(tmp_path, ok)) == MAX_BATCH_DOMAINS
    too_many = ok + "extra.example\n"
    with pytest.raises(BatchInputError, match="per-run cap is 25"):
        _load(tmp_path, too_many)


def test_test_fetchers_accept_site_keyword():
    for cls in FETCHER_CLASSES:
        page = cls().fetch("https://example.com/", site="example.com")
        assert page.url == "https://example.com/"
        assert cls().fetch("https://example.com/").url == "https://example.com/"
