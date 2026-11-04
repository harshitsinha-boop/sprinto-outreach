"""The bounded research loop (QUA-04, QUA-05): a gray-band company reads at most three more
same-domain pages, each chosen by a model with a logged reason, and never a page it was not
offered. Everything is offline: FakeLLM scripts the tool turns, FakeFetcher serves the pages.
"""

from __future__ import annotations

from conftest import (
    HOME_URL,
    FakeFetcher,
    FakeHunter,
    FakeLLM,
    default_llm_responses,
)
from outreach.models import (
    CompanyProfile,
    ComplianceMention,
    EvidencedBool,
    EvidencedText,
    HeadcountFact,
    HiringSignal,
    StageFact,
    ToolCall,
    ToolReply,
)
from outreach.skeleton import run_one

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
    assert [s.name for s in rec.stages] == ["scrape", "extract", "qualify", "hunter", "draft", "send"]
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
    assert [c["purpose"] for c in llm.calls] == ["extract", "research_extract", "draft"]
    assert [t["kind"] for t in llm.tool_turns] == ["send"]
    assert hunter.calls == ["example.com"]
