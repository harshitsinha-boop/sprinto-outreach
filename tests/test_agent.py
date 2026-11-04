"""The bounded research loop (QUA-04, QUA-05): a gray-band company reads at most three more
same-domain pages, each chosen by a model with a logged reason, and never a page it was not
offered. Everything is offline: FakeLLM scripts the tool turns, FakeFetcher serves the pages.
"""

from __future__ import annotations

import json

import pytest

from conftest import (
    CANARY_ENV,
    HOME_URL,
    FakeFetcher,
    FakeGenaiClient,
    FakeHunter,
    FakeLLM,
    default_llm_responses,
    function_call_response,
    text_response,
)
from outreach.agent import MAX_LOOP_FETCHES, MAX_LOOP_ITERATIONS, research_candidates, run_research
from outreach.llm import LLMAuthError, LLMClient, LLMError, LLMQuotaError
from outreach.models import (
    CompanyProfile,
    ComplianceMention,
    EnterpriseCustomer,
    EvidencedBool,
    EvidencedText,
    HeadcountFact,
    HiringSignal,
    Link,
    PageResult,
    StageFact,
    ToolCall,
    ToolReply,
)
from outreach.qualify import load_rubric, qualify, render_breakdown, score_profile, usable_kinds
from outreach.scrape import MAX_ATTEMPTS_PER_KIND, PAGE_KINDS, candidate_urls
from outreach.skeleton import run_one

DOMAIN = "example.com"
RUBRIC = load_rubric()

TRUST_URL = "https://example.com/trust-center"

HOME_BUSINESS = "Ledgerline is a B2B platform that builds workflow software for finance teams."
HOME_STAGE = "We are a small team backed by a seed round and we ship every week."
HOME_HEADCOUNT = "We are a team of around 30 people"
THIN_HOME_TEXT = (
    f"{HOME_BUSINESS} {HOME_STAGE} {HOME_HEADCOUNT} who care about careful, quiet software. "
    "Our product keeps month end close tasks, reviews and hand offs in one tidy workspace, so "
    "that accountants spend their days on judgement instead of chasing spreadsheets across "
    "email threads. Teams start with one checklist and grow into a full close calendar. "
    "Book a walkthrough to see the workspace in action."
)

TRUST_SOC2 = "We are currently working toward SOC 2 Type II certification"
TRUST_HIRING = "We are hiring a Security Engineer to own our compliance program."
TRUST_TEXT = (
    "Ledgerline Trust Center. "
    f"{TRUST_SOC2}, and our audit window opens next quarter. {TRUST_HIRING} "
    "Customer data is encrypted in transit and at rest, access is reviewed every quarter and "
    "every change to production is peer reviewed and logged. Report a vulnerability through "
    "the contact address listed on this page and a person will reply within two working days."
)


def thin_profile() -> CompanyProfile:
    """What the home page alone supports: 30 known points, four unknown signals (30..95)."""
    return CompanyProfile(
        name=EvidencedText(value="Ledgerline", quote=HOME_BUSINESS, source_url=HOME_URL),
        offering=EvidencedText(
            value="workflow software for finance teams",
            quote="builds workflow software for finance teams",
            source_url=HOME_URL,
        ),
        is_b2b=EvidencedBool(value=True, quote=HOME_BUSINESS, source_url=HOME_URL),
        stage=StageFact(
            value="seed", as_of=None, quote="backed by a seed round", source_url=HOME_URL
        ),
        headcount=HeadcountFact(value="11-50", quote=HOME_HEADCOUNT, source_url=HOME_URL),
        compliance_mentions=[],
        hiring_signals=[],
        enterprise_customers=[],
    )


def trust_profile() -> CompanyProfile:
    """What the trust page adds: a SOC 2 effort in progress and a security hire."""
    return CompanyProfile(
        name=None,
        offering=None,
        is_b2b=None,
        stage=None,
        headcount=None,
        compliance_mentions=[
            ComplianceMention(
                framework="SOC 2",
                status="in_progress",
                as_of=None,
                quote=TRUST_SOC2,
                source_url=TRUST_URL,
            )
        ],
        hiring_signals=[
            HiringSignal(role="Security Engineer", quote=TRUST_HIRING, source_url=TRUST_URL)
        ],
        enterprise_customers=[],
    )


def fetch_call(url: str, reason: str = "resolve compliance_pursuit from a trust page") -> ToolReply:
    return ToolReply(calls=[ToolCall(name="fetch_page", args={"url": url, "reason": reason})])


def stage_output(rec, name: str) -> dict:
    stage = next(s for s in rec.stages if s.name == name)
    assert stage.output is not None
    return stage.output


def test_gray_band_company_researches_one_page_and_qualifies(ctx):
    responses = {
        **default_llm_responses(),
        "extract": thin_profile(),
        "research_extract": trust_profile(),
    }
    llm = FakeLLM(responses, tool_script=[fetch_call(TRUST_URL)])
    hunter = FakeHunter()
    ctx.llm = llm
    ctx.hunter = hunter
    ctx.fetcher = FakeFetcher(THIN_HOME_TEXT, by_url={TRUST_URL: TRUST_TEXT})

    rec = run_one("example.com", ctx)

    assert rec.status == "dry_run"
    assert [s.name for s in rec.stages] == ["scrape", "extract", "qualify", "poc", "draft", "send"]
    q = stage_output(rec, "qualify")
    assert q["initial_verdict"] == "loop"
    assert (q["initial_score"]["score_min"], q["initial_score"]["score_max"]) == (30, 95)
    assert q["verdict"] == "qualified"
    assert q["score"]["score_min"] == 70
    research = q["research"]
    assert research["stop_reason"] == "sufficient_data"
    assert research["fetches"] == 1
    assert len(research["steps"]) == 1
    step = research["steps"][0]
    assert step["outcome"] == "fetched"
    assert step["url"] == TRUST_URL
    assert step["page_kind"] == "security"
    assert step["reason"]
    assert {"compliance_pursuit", "security_hiring"} <= set(step["resolved_signals"])
    assert (step["score_min"], step["score_max"]) == (70, 70 + 15 + 10)  # customers and recent_funding unknown
    assert [c["purpose"] for c in llm.calls] == ["extract", "research_extract", "pain_points", "draft"]
    assert [t["kind"] for t in llm.tool_turns] == ["send"]
    assert hunter.calls == ["example.com"]


# ---------------------------------------------------------------- Task 2: loop guards

CUSTOMERS_URL = "https://example.com/customer-stories"
CAREERS_URL = "https://example.com/company/careers"
ABOUT_URLS = ["https://example.com/about/company", "https://example.com/team"]
ALL_RESEARCH_URLS = [CUSTOMERS_URL, CAREERS_URL, TRUST_URL, *ABOUT_URLS]

CUSTOMER_QUOTE = "Northwind Logistics runs its close calendar on Ledgerline"
DEVOPS_QUOTE = "We are hiring a DevOps Engineer for our platform team."
GDPR_QUOTE = "We process personal data in line with GDPR requirements."
FILLER = (
    "Every workspace keeps its own audit trail, role based access and a plain language activity "
    "log, so reviewers can follow a change from request to approval without asking anyone. "
    "Product updates ship weekly and release notes are published on this site for all "
    "customers. Support answers within one working day, and the status page lists every "
    "incident together with its cause and the fix that was applied afterwards."
)


def page_text(tag: str, *sentences: str) -> str:
    return f"{tag} at Ledgerline. {' '.join(sentences)} {FILLER}"


CUSTOMERS_TEXT = page_text("Customer stories", CUSTOMER_QUOTE + ".")
CAREERS_TEXT = page_text("Careers", DEVOPS_QUOTE)
SECURITY_TEXT = page_text("Trust and privacy", GDPR_QUOTE)
ABOUT_TEXTS = [page_text("About the company"), page_text("Meet the team")]
RESEARCH_TEXTS = {
    CUSTOMERS_URL: CUSTOMERS_TEXT,
    CAREERS_URL: CAREERS_TEXT,
    TRUST_URL: SECURITY_TEXT,
    ABOUT_URLS[0]: ABOUT_TEXTS[0],
    ABOUT_URLS[1]: ABOUT_TEXTS[1],
}


def empty_profile() -> CompanyProfile:
    return CompanyProfile(
        name=None,
        offering=None,
        is_b2b=None,
        stage=None,
        headcount=None,
        compliance_mentions=[],
        hiring_signals=[],
        enterprise_customers=[],
    )


def stepwise_profiles() -> list[CompanyProfile]:
    """One more signal per page, none enough to leave the gray band: 35..85, 40..75, 50..60."""
    customers = empty_profile().model_copy(
        update={
            "enterprise_customers": [
                EnterpriseCustomer(
                    name="Northwind Logistics", quote=CUSTOMER_QUOTE, source_url=CUSTOMERS_URL
                )
            ]
        }
    )
    careers = empty_profile().model_copy(
        update={
            "hiring_signals": [
                HiringSignal(role="DevOps Engineer", quote=DEVOPS_QUOTE, source_url=CAREERS_URL)
            ]
        }
    )
    security = empty_profile().model_copy(
        update={
            "compliance_mentions": [
                ComplianceMention(
                    framework="GDPR",
                    status="mentioned",
                    as_of=None,
                    quote=GDPR_QUOTE,
                    source_url=TRUST_URL,
                )
            ]
        }
    )
    return [customers, careers, security]


def max_iters_script() -> list[ToolReply]:
    return [fetch_call(u, f"resolve a signal from {u}") for u in ALL_RESEARCH_URLS]


class RecordingFetcher:
    """Records every URL it is asked for, so a never-fetched assertion is not vacuous."""

    def __init__(self, texts=None, *, default_text=None, errors=()):
        self.texts = dict(texts or {})
        self.default_text = default_text
        self.errors = set(errors)
        self.calls: list[str] = []
        self.sites: list[str | None] = []

    def fetch(self, url: str, site=None) -> PageResult:
        self.calls.append(url)
        self.sites.append(site)
        if url in self.errors:
            return PageResult(url=url, status="error", error="connection reset")
        text = self.texts.get(url, self.default_text)
        if text is None:
            return PageResult(url=url, status="unavailable", reason="http_404")
        return PageResult(url=url, status="ok", text=text, chars=len(text))


def home_page(links=()) -> PageResult:
    return PageResult(
        url=HOME_URL,
        status="ok",
        text=THIN_HOME_TEXT,
        chars=len(THIN_HOME_TEXT),
        kind="home",
        links=list(links),
    )


def scraped_pages() -> list[PageResult]:
    """The state after the scrape stage on a thin site: the home page usable and every fallback
    path the scraper tries already spent (unavailable), as in a real run."""
    pages = [home_page()]
    for kind in PAGE_KINDS[1:]:
        for url in candidate_urls(DOMAIN, kind, [])[:MAX_ATTEMPTS_PER_KIND]:
            pages.append(PageResult(url=url, status="unavailable", kind=kind, reason="http_404"))
    return pages


def run_loop(script, *, texts=None, errors=(), responses=None, pages=None, settings=None, llm=None):
    llm = llm or FakeLLM(
        {
            **default_llm_responses(),
            "extract": thin_profile(),
            "research_extract": empty_profile(),
            **(responses or {}),
        },
        tool_script=list(script),
    )
    fetcher = RecordingFetcher(texts=texts, errors=errors)
    pages = pages if pages is not None else scraped_pages()
    profile = thin_profile()
    score = score_profile(profile, usable_kinds(pages), RUBRIC.rubric)
    outcome = run_research(
        llm,
        fetcher,
        domain=DOMAIN,
        smart_model="smart-model",
        fast_model="fast-model",
        profile=profile,
        pages=pages,
        loaded=RUBRIC,
        score=score,
        settings=settings,
    )
    return outcome, llm, fetcher


def refusals(outcome) -> list[str | None]:
    return [step.refusal for step in outcome.agent.steps]


def test_off_domain_and_metadata_urls_are_refused_and_never_fetched():
    script = [
        fetch_call("https://evil.example/collect"),
        fetch_call("http://169.254.169.254/latest/meta-data/"),
    ]
    outcome, llm, fetcher = run_loop(script)
    assert fetcher.calls == []
    assert refusals(outcome) == ["off_domain", "off_domain"]
    assert [step.outcome for step in outcome.agent.steps] == ["refused", "refused"]
    assert outcome.agent.fetches == 0
    assert outcome.agent.stop_reason == "no_progress"


def test_same_site_url_not_offered_is_refused():
    outcome, llm, fetcher = run_loop([fetch_call("https://example.com/admin")])
    assert fetcher.calls == []
    assert refusals(outcome) == ["not_a_candidate"]


@pytest.mark.parametrize("reason", ["", "   "])
def test_missing_reason_is_refused(reason):
    outcome, llm, fetcher = run_loop([fetch_call(TRUST_URL, reason)])
    assert fetcher.calls == []
    assert refusals(outcome) == ["missing_reason"]


def test_unknown_tool_is_refused():
    script = [ToolReply(calls=[ToolCall(name="delete_page", args={"url": TRUST_URL, "reason": "x"})])]
    outcome, llm, fetcher = run_loop(script)
    assert fetcher.calls == []
    assert refusals(outcome) == ["unknown_tool"]


def test_only_one_fetch_per_turn():
    both = ToolReply(
        calls=[
            ToolCall(name="fetch_page", args={"url": ABOUT_URLS[0], "reason": "first"}),
            ToolCall(name="fetch_page", args={"url": ABOUT_URLS[1], "reason": "second"}),
        ]
    )
    outcome, llm, fetcher = run_loop([both], texts=RESEARCH_TEXTS)
    assert fetcher.calls == [ABOUT_URLS[0]]
    assert [(s.iteration, s.outcome, s.refusal) for s in outcome.agent.steps] == [
        (1, "fetched", None),
        (1, "refused", "one_fetch_per_turn"),
    ]
    respond = llm.tool_turns[1]
    assert respond["kind"] == "respond"
    assert [r.response["status"] for r in respond["results"]] == ["fetched", "refused"]
    assert respond["results"][1].response["refusal"] == "one_fetch_per_turn"


def test_already_fetched_url_is_refused():
    script = [fetch_call(ABOUT_URLS[0]), fetch_call(ABOUT_URLS[0])]
    outcome, llm, fetcher = run_loop(script, texts=RESEARCH_TEXTS)
    assert fetcher.calls == [ABOUT_URLS[0]]
    assert refusals(outcome) == [None, "already_fetched"]


def test_fetch_cap_is_an_independent_guard(monkeypatch):
    monkeypatch.setattr("outreach.agent.MAX_LOOP_FETCHES", 1)
    script = [fetch_call(ABOUT_URLS[0]), fetch_call(ABOUT_URLS[1])]
    outcome, llm, fetcher = run_loop(script, texts=RESEARCH_TEXTS)
    assert fetcher.calls == [ABOUT_URLS[0]]
    assert refusals(outcome) == [None, "fetch_cap"]


def run_max_iters(llm=None):
    llm = llm or FakeLLM(
        {
            **default_llm_responses(),
            "extract": thin_profile(),
            "research_extract": stepwise_profiles(),
        },
        tool_script=max_iters_script(),
    )
    fetcher = RecordingFetcher(texts=RESEARCH_TEXTS)
    pages = scraped_pages()
    research = lambda profile, pgs, score: run_research(  # noqa: E731
        llm,
        fetcher,
        domain=DOMAIN,
        smart_model="smart-model",
        fast_model="fast-model",
        profile=profile,
        pages=pgs,
        loaded=RUBRIC,
        score=score,
    )
    q = qualify(thin_profile(), pages, RUBRIC, research=research)
    return q, llm, fetcher


def test_loop_stops_at_three_iterations():
    assert (MAX_LOOP_ITERATIONS, MAX_LOOP_FETCHES) == (3, 3)
    q, llm, fetcher = run_max_iters()
    run = q.research
    assert run is not None
    assert run.stop_reason == "max_iters"
    assert (run.iterations, run.fetches, run.llm_turns) == (3, 3, 3)
    assert [(s.score_min, s.score_max) for s in run.steps] == [(35, 85), (40, 75), (50, 60)]
    assert [t["kind"] for t in llm.tool_turns] == ["send", "respond", "respond"]
    assert fetcher.calls == ALL_RESEARCH_URLS[:3]
    assert [c["purpose"] for c in llm.calls] == ["research_extract"] * 3
    assert q.verdict == "insufficient_data"
    assert q.decided_with_unknowns == ["recent_funding"]
    assert "research stop_reason=max_iters, 3 fetches" in q.reason


def test_no_progress_stops_after_two_turns():
    script = [fetch_call(u) for u in ABOUT_URLS] + [fetch_call(CAREERS_URL)]
    outcome, llm, fetcher = run_loop(script, texts=RESEARCH_TEXTS)
    assert outcome.agent.stop_reason == "no_progress"
    assert len(outcome.agent.steps) == 2
    assert fetcher.calls == ABOUT_URLS
    assert [t["kind"] for t in llm.tool_turns] == ["send", "respond"]


def test_tool_errors_stop_after_two_failed_fetches():
    script = [fetch_call(u) for u in ABOUT_URLS] + [fetch_call(CAREERS_URL)]
    outcome, llm, fetcher = run_loop(script, texts=RESEARCH_TEXTS, errors=ABOUT_URLS)
    assert outcome.agent.stop_reason == "tool_errors"
    assert [s.outcome for s in outcome.agent.steps] == ["error", "error"]
    assert fetcher.calls == ABOUT_URLS


def test_model_done_when_no_call():
    outcome, llm, fetcher = run_loop([])
    assert outcome.agent.stop_reason == "model_done"
    assert outcome.agent.steps == []
    assert [t["kind"] for t in llm.tool_turns] == ["send"]
    # also when the model stops after a first fetch
    outcome, llm, fetcher = run_loop([fetch_call(ABOUT_URLS[0]), ToolReply()], texts=RESEARCH_TEXTS)
    assert outcome.agent.stop_reason == "model_done"
    assert len(outcome.agent.steps) == 1


def test_no_candidates_makes_no_tool_turn():
    pages = scraped_pages()
    while True:  # take every URL the loop could offer, in as many rounds as the cap needs
        score = score_profile(thin_profile(), usable_kinds(pages), RUBRIC.rubric)
        offered = research_candidates(DOMAIN, pages, score, RUBRIC.rubric)
        if not offered:
            break
        pages += [PageResult(url=c.url, status="unavailable", kind=c.kind) for c in offered]
    outcome, llm, fetcher = run_loop([fetch_call(TRUST_URL)], pages=pages)
    assert outcome.agent.stop_reason == "no_candidates"
    assert llm.tool_turns == [] and fetcher.calls == []


def test_not_needed_and_disabled_stop_reasons(ctx):
    llm = FakeLLM()
    ctx.llm = llm
    rec = run_one("example.com", ctx)
    assert rec.status == "dry_run"
    assert stage_output(rec, "qualify")["research"]["stop_reason"] == "not_needed"
    assert llm.tool_turns == []
    q = qualify(thin_profile(), [home_page()], RUBRIC)
    assert q.initial_verdict == "loop"
    assert q.research is not None and q.research.stop_reason == "disabled"
    assert q.verdict == "insufficient_data"


def test_duplicate_page_is_not_reextracted():
    texts = {ABOUT_URLS[0]: THIN_HOME_TEXT}
    outcome, llm, fetcher = run_loop([fetch_call(ABOUT_URLS[0])], texts=texts)
    step = outcome.agent.steps[0]
    assert (step.outcome, step.page_status) == ("unavailable", "unavailable")
    assert outcome.pages[-1].reason == "duplicate_content"
    assert llm.calls == []


def test_model_never_sees_page_text():
    link = Link(url="https://example.com/p/42", text="Security and trust vault diaries")
    pages = [*scraped_pages(), ]
    pages[0] = home_page(links=[link])
    _, llm2, _ = run_loop([], pages=pages)
    link_prompt = llm2.tool_turns[0]["prompt"]
    assert "https://example.com/p/42" in link_prompt  # the harvested link is a candidate url
    assert "vault diaries" not in link_prompt  # but its link text never reaches the model
    _, llm, _ = run_max_iters()
    blob = llm.tool_turns[0]["prompt"] + json.dumps(
        [[r.model_dump() for r in t["results"]] for t in llm.tool_turns if t["kind"] == "respond"]
    )
    for text in (THIN_HOME_TEXT, TRUST_TEXT, *RESEARCH_TEXTS.values()):
        for i in range(0, len(text) - 40):
            assert text[i : i + 40] not in blob


@pytest.mark.parametrize("error", [LLMError, LLMAuthError, LLMQuotaError])
def test_llm_error_ends_loop_but_quota_error_propagates(ctx, settings, error):
    key = CANARY_ENV["GEMINI_API_KEY"]
    script = [error(f"500 INTERNAL: key {key} rejected")]
    if error is LLMError:
        outcome, llm, fetcher = run_loop(script, settings=settings)
        assert outcome.agent.stop_reason == "tool_errors"
        assert outcome.agent.error is not None
        assert outcome.agent.error.startswith("LLMError") and key not in outcome.agent.error
        # the company still gets a final verdict from its unchanged profile
        q = qualify(
            thin_profile(),
            [home_page()],
            RUBRIC,
            research=lambda profile, pages, score: outcome,
        )
        assert q.verdict == "insufficient_data" and q.research is outcome.agent
    else:
        ctx.llm = FakeLLM(
            {**default_llm_responses(), "extract": thin_profile()}, tool_script=script
        )
        ctx.fetcher = FakeFetcher(THIN_HOME_TEXT)
        with pytest.raises(error):
            run_one("example.com", ctx)
        assert ctx.store.load("example.com").status == "failed"


def test_unresolved_loop_company_makes_zero_hunter_calls(ctx):
    llm = FakeLLM(
        {
            **default_llm_responses(),
            "extract": thin_profile(),
            "research_extract": stepwise_profiles(),
        },
        tool_script=max_iters_script(),
    )
    hunter = FakeHunter()
    ctx.llm, ctx.hunter = llm, hunter
    ctx.fetcher = RecordingFetcher(texts=RESEARCH_TEXTS, default_text=THIN_HOME_TEXT)
    rec = run_one("example.com", ctx)
    assert rec.status == "stopped" and rec.stop_reason == "insufficient_data"
    assert [s.name for s in rec.stages] == ["scrape", "extract", "qualify"]
    assert hunter.calls == []
    result = rec.stages[-1].output["result"]
    assert len(result["research"]["steps"]) == 3
    assert result["decided_with_unknowns"] == ["recent_funding"]


def test_breakdown_shows_research_steps():
    reason = "pick this page \x1b[31m\nnext line"
    script = [fetch_call("https://evil.example/collect", reason), fetch_call(ABOUT_URLS[0], "about")]
    llm = FakeLLM(
        {**default_llm_responses(), "extract": thin_profile(), "research_extract": empty_profile()},
        tool_script=script,
    )
    fetcher = RecordingFetcher(texts=RESEARCH_TEXTS)
    q = qualify(
        thin_profile(),
        scraped_pages(),
        RUBRIC,
        research=lambda profile, pages, score: run_research(
            llm,
            fetcher,
            domain=DOMAIN,
            smart_model="s",
            fast_model="f",
            profile=profile,
            pages=pages,
            loaded=RUBRIC,
            score=score,
        ),
    )
    text = render_breakdown(q)
    lines = text.split("\n")
    assert any(
        "research" in line and "stop_reason=no_progress" in line and "iterations=2" in line
        and "fetches=1" in line
        for line in lines
    )
    refused = next(line for line in lines if "evil.example" in line)
    assert '"pick this page [31mnext line"' in refused and "refused (off_domain)" in refused
    fetched = next(line for line in lines if ABOUT_URLS[0] in line)
    assert '"about"' in fetched and "fetched" in fetched
    assert "\x1b" not in text


def test_rerun_of_loop_company_makes_no_new_gemini_calls(ctx, fake_sleep, tmp_path):
    cache = tmp_path / "llm-cache"
    key = CANARY_ENV["GEMINI_API_KEY"]
    queue = [
        text_response(thin_profile().model_dump_json()),
        function_call_response(
            "fetch_page", {"url": TRUST_URL, "reason": "resolve compliance_pursuit"}
        ),
        text_response(trust_profile().model_dump_json()),
        text_response(default_llm_responses()["pain_points"].model_dump_json()),
        text_response(default_llm_responses()["draft"].model_dump_json()),
    ]
    first = LLMClient(key, cache, client=FakeGenaiClient(queue), sleep=fake_sleep)
    ctx.llm = first
    ctx.hunter = FakeHunter()
    ctx.fetcher = FakeFetcher(THIN_HOME_TEXT, by_url={TRUST_URL: TRUST_TEXT})
    rec = run_one("example.com", ctx)
    assert rec.status == "dry_run"
    assert stage_output(rec, "qualify")["research"]["stop_reason"] == "sufficient_data"
    assert first.stats.api_calls == 5 and first._c.models.queue == []

    second = LLMClient(key, cache, client=FakeGenaiClient([]), sleep=fake_sleep)
    ctx.llm = second
    rerun = run_one("example.com", ctx)
    assert rerun.status == "dry_run"
    assert second._c.models.calls == [] and second.stats.api_calls == 0
    assert second.stats.cache_hits == 5  # extract, the tool turn, research_extract, pain points and draft
    assert rerun.counters["llm_api_calls"] == 0
