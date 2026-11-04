"""Qualification: rubric loading and hashing, the pure interval scorer, verdict rules, the
printed breakdown and the zero-Hunter guarantee. Everything is offline (conftest fakes)."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from conftest import (
    CANARY_ENV,
    SAMPLE_PAGE_TEXT,
    FakeFetcher,
    FakeLLM,
    default_llm_responses,
)
from outreach.models import (
    AgentRun,
    ResearchOutcome,
    CompanyProfile,
    ComplianceMention,
    EnterpriseCustomer,
    EvidencedBool,
    EvidencedText,
    HeadcountFact,
    HiringSignal,
    PageResult,
    Qualification,
    StageFact,
)
from outreach.qualify import (
    DEFAULT_RUBRIC_PATH,
    RubricError,
    SignalRule,
    final_verdict,
    initial_verdict,
    load_rubric,
    qualification_from_record,
    qualify,
    render_breakdown,
    score_profile,
)
from outreach.runner import render_summary, run_batch, write_summary
from outreach.skeleton import run_one

DOMAIN = CANARY_ENV["SKELETON_DOMAIN"]

CONSUMER_QUOTE = "Pocket Pals is a free mobile game for kids and families"
CONSUMER_TEXT = (
    CONSUMER_QUOTE
    + ". Download the app and play with your friends every day after school. "
    "Collect new pets, decorate your room and trade stickers with people you know. "
    "Parents can set screen time limits from the settings menu, and every purchase is "
    "protected by a family password. The game is made for people who love to play, and "
    "new levels arrive every week for all of our players around the world."
)
CONSUMER_URL = f"https://{DOMAIN}/"


def consumer_profile() -> CompanyProfile:
    return CompanyProfile(
        name=EvidencedText(value="Pocket Pals", quote=CONSUMER_QUOTE, source_url=CONSUMER_URL),
        offering=EvidencedText(
            value="mobile game", quote=CONSUMER_QUOTE, source_url=CONSUMER_URL
        ),
        is_b2b=EvidencedBool(value=False, quote=CONSUMER_QUOTE, source_url=CONSUMER_URL),
        stage=None,
        headcount=HeadcountFact(
            value="11-50", quote=CONSUMER_QUOTE, source_url=CONSUMER_URL
        ),
        compliance_mentions=[],
        hiring_signals=[],
        enterprise_customers=[],
    )


# ---- Task 1: tracer ----


def test_default_company_qualifies_through_run_one_with_rubric_hash(ctx):
    rec = run_one(DOMAIN, ctx)

    assert rec.status == "dry_run"
    assert [s.name for s in rec.stages] == [
        "scrape",
        "extract",
        "qualify",
        "poc",
        "draft",
        "send",
    ]
    qualify_out = rec.stages[2].output
    assert qualify_out["verdict"] == "qualified"
    assert qualify_out["score"]["score_min"] == 95
    assert qualify_out["score"]["score_max"] == 100
    assert qualify_out["score"]["unknown_signals"] == ["funding_stage"]
    assert qualify_out["score"]["score_expected"] == 97.5

    expected_sha = hashlib.sha256(DEFAULT_RUBRIC_PATH.read_bytes()).hexdigest()
    assert rec.rubric["sha256"] == expected_sha
    assert rec.rubric["version"] == "icp.2"
    assert qualify_out["rubric_sha256"] == expected_sha
    on_disk = ctx.store.load(DOMAIN)
    assert on_disk.rubric["sha256"] == expected_sha


def test_consumer_company_is_disqualified_with_zero_hunter_calls(ctx, fake_hunter):
    ctx.fetcher = FakeFetcher(CONSUMER_TEXT)
    responses = default_llm_responses()
    responses["extract"] = consumer_profile()
    ctx.llm = FakeLLM(responses)

    rec = run_one(DOMAIN, ctx)

    assert rec.status == "stopped"
    assert rec.stop_reason == "disqualified"
    assert [s.name for s in rec.stages] == ["scrape", "extract", "qualify"]
    assert fake_hunter.calls == []
    stopped = rec.stages[-1]
    assert stopped.status == "stopped"
    assert stopped.output["reason"] == "disqualified"
    assert stopped.output["detail"]
    q = Qualification.model_validate(stopped.output["result"])
    assert q.verdict == "disqualified"
    gates = {g.id: g for g in q.score.gates}
    assert gates["G1_b2b"].status == "fail"
    assert len(q.score.signals) == 7


# ---- Task 2: calibration set, determinism, validation ----

FIXTURE = Path(__file__).parent / "fixtures" / "icp_calibration.json"
CALIBRATION = json.loads(FIXTURE.read_text())
CASES = CALIBRATION["cases"]
ALL_KINDS = {"home", "about", "careers", "security", "pricing", "customers"}
URL = "https://case.example/"


def pages_for(kinds) -> list[PageResult]:
    text = "x" * 500
    return [
        PageResult(url=f"https://case.example/{k}", status="ok", text=text, chars=500, kind=k)
        for k in sorted(kinds)
    ]


def make_profile(
    *,
    is_b2b=True,
    stage=None,
    as_of=None,
    headcount=None,
    offering=None,
    compliance=(),
    hiring=(),
    customers=(),
) -> CompanyProfile:
    q = "a quote long enough"
    return CompanyProfile(
        name=None,
        offering=None
        if offering is None
        else EvidencedText(value=offering, quote=q, source_url=URL),
        is_b2b=None if is_b2b is None else EvidencedBool(value=is_b2b, quote=q, source_url=URL),
        stage=None
        if stage is None
        else StageFact(value=stage, as_of=as_of, quote=q, source_url=URL),
        headcount=None
        if headcount is None
        else HeadcountFact(value=headcount, quote=q, source_url=URL),
        compliance_mentions=[
            ComplianceMention(
                framework=f, status=s, as_of=None, quote=f"quote about {f} {s}", source_url=URL
            )
            for f, s in compliance
        ],
        hiring_signals=[
            HiringSignal(role=r, quote=f"hiring {r} now", source_url=URL) for r in hiring
        ],
        enterprise_customers=[
            EnterpriseCustomer(name=n, quote=f"{n} is a customer", source_url=URL)
            for n in customers
        ],
    )


def signal(score, signal_id):
    return next(s for s in score.signals if s.id == signal_id)


def test_calibration_fixture_matches_the_rubric_version():
    assert CALIBRATION["rubric_version"] == load_rubric().rubric.version
    assert len(CASES) >= 8
    assert {c["expect"]["verdict"] for c in CASES} == {
        "qualified",
        "disqualified",
        "insufficient_data",
    }


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_calibration_cases(case):
    loaded = load_rubric()
    profile = CompanyProfile.model_validate(case["profile"])
    expect = case["expect"]

    research = None
    if case.get("research") == "stub":  # the loop ran but resolved nothing more
        def research(prof, pages, score):
            return ResearchOutcome(profile=prof, pages=pages, agent=AgentRun(stop_reason="no_candidates"))

    q = qualify(profile, pages_for(case["kinds_usable"]), loaded, research=research)

    assert q.initial_verdict == expect["initial_verdict"]
    assert q.verdict == expect["verdict"]
    assert q.score.score_min == expect["score_min"]
    assert q.score.score_max == expect["score_max"]
    assert q.score.score_expected == expect["score_expected"]
    if "gate_failed" in expect:
        assert [g.id for g in q.score.gates if g.status == "fail"] == [expect["gate_failed"]]
    if "penalties" in expect:
        assert [p.id for p in q.score.penalties] == expect["penalties"]
    if "decided_with_unknowns" in expect:
        assert q.decided_with_unknowns == expect["decided_with_unknowns"]
    # the same verdicts through the two public verdict functions
    assert initial_verdict(q.score, loaded.rubric) == expect["initial_verdict"]
    assert final_verdict(q.score, loaded.rubric, researched=research is not None)[0] == expect["verdict"]
    if case.get("research") == "stub":
        assert q.reason.startswith("qualified on expected score 62.0 (min 47..max 77)")
        assert q.decided_with_unknowns  # an estimate says so: the unknowns are listed
        # the same company without research stays undecided: the estimate needs the loop to have run
        assert qualify(profile, pages_for(case["kinds_usable"]), loaded).verdict == "insufficient_data"


def test_score_is_deterministic_and_order_independent():
    rubric = load_rubric().rubric
    by_id = {c["id"]: c for c in CASES}

    for case_id in ("reject_mature_certified", "fit_unknown_stage", "fit_series_b_full_signals"):
        case = by_id[case_id]
        kinds = set(case["kinds_usable"])
        profile = CompanyProfile.model_validate(case["profile"])
        first = score_profile(profile, kinds, rubric)
        second = score_profile(profile, kinds, rubric)
        assert first.model_dump() == second.model_dump()

        reversed_profile = profile.model_copy(
            update={
                "compliance_mentions": list(reversed(profile.compliance_mentions)),
                "hiring_signals": list(reversed(profile.hiring_signals)),
                "enterprise_customers": list(reversed(profile.enterprise_customers)),
            }
        )
        flipped = score_profile(reversed_profile, kinds, rubric)
        assert (flipped.score_min, flipped.score_max) == (first.score_min, first.score_max)
        assert flipped.unknown_signals == first.unknown_signals
        assert flipped.penalties == first.penalties
        assert flipped.model_dump() == first.model_dump()


def test_unknown_counts_zero_in_min_and_full_in_max():
    rubric = load_rubric().rubric
    score = score_profile(make_profile(is_b2b=None), set(), rubric)

    assert score.score_min == 0
    assert score.score_max == 100
    assert score.score_expected == 50.0  # unknown_credit 0.5 x (100 - 0)
    assert len(score.unknown_signals) == 7
    assert score.unknown_signals[0] == "compliance_pursuit"
    for s in score.signals:
        assert (s.status, s.points_min, s.points_max) == ("unknown", 0, s.weight)
    assert [g.status for g in score.gates] == ["unknown", "unknown"]

    one_known = score_profile(make_profile(is_b2b=True), set(), rubric)
    assert (one_known.score_min, one_known.score_max) == (10, 100)
    assert one_known.score_expected == 55.0


def test_penalty_lowers_both_bounds_with_floor_zero():
    rubric = load_rubric().rubric
    both = make_profile(
        is_b2b=None, compliance=[("SOC 2 Type II", "certified"), ("ISO 27001", "certified")]
    )
    score = score_profile(both, set(), rubric)
    assert [p.id for p in score.penalties] == ["P1_mature_soc2_type2_and_iso27001"]
    assert score.score_min == 0  # 7 - 30 floors at 0
    assert score.score_max == 77 - 30

    type_two_only = make_profile(is_b2b=None, compliance=[("SOC 2 Type 2", "certified")])
    score = score_profile(type_two_only, set(), rubric)
    assert [p.id for p in score.penalties] == ["P2_soc2_type2_only"]
    assert score.score_max == 77 - 15
    assert all(p.evidence for p in score.penalties)

    type_one = make_profile(is_b2b=None, compliance=[("SOC 2 Type I", "certified")])
    assert score_profile(type_one, set(), rubric).penalties == []


def test_empty_list_is_unknown_until_its_page_kind_is_read():
    rubric = load_rubric().rubric
    profile = make_profile()

    blind = signal(score_profile(profile, {"home"}, rubric), "compliance_pursuit")
    assert (blind.status, blind.points_min, blind.points_max) == ("unknown", 0, 30)
    assert blind.basis == "unknown: no security page read"

    read = signal(score_profile(profile, {"home", "security"}, rubric), "compliance_pursuit")
    assert (read.status, read.points_min, read.points_max) == ("known", 0, 0)
    assert read.basis == "no item; security page read"

    customers = signal(score_profile(profile, {"customers"}, rubric), "enterprise_customers")
    assert customers.status == "known" and customers.points_max == 0


@pytest.mark.parametrize(
    ("role", "points", "status"),
    [
        ("Head of IT", 7, "known"),
        ("Itinerary Planner", 0, "known"),
        ("Security Engineer", 20, "known"),
        ("Staff SRE", 7, "known"),
        ("Insecurity Analyst", 0, "known"),
    ],
)
def test_keyword_groups_match_whole_words(role, points, status):
    rubric = load_rubric().rubric
    score = score_profile(make_profile(hiring=[role]), {"home"}, rubric)
    hiring = signal(score, "security_hiring")
    assert (hiring.status, hiring.points_min, hiring.points_max) == (status, points, points)


@pytest.mark.parametrize(
    ("as_of", "points", "status"),
    [
        ("March 2025", 10, "known"),
        ("2024", 5, "known"),
        ("2019", 0, "known"),
        ("2030", 10, "known"),
        ("last year", 0, "unknown"),
        (None, 0, "unknown"),
    ],
)
def test_year_recency_uses_reference_year(as_of, points, status):
    base = load_rubric().rubric
    assert base.thresholds.reference_year == 2026
    # icp.2 dropped recent_funding; the year_recency kind is still supported, so test it on a
    # rubric with the signal added back (score_profile does not re-validate the weight sum)
    extra = SignalRule(
        id="recent_funding", label="Funding recency", group="C", weight=10, kind="year_recency",
        field="stage", points={"age_le_1": 10, "age_2": 5, "older": 0}, target_kinds=["about"],
    )
    rubric = base.model_copy(update={"signals": [*base.signals, extra]})
    score = score_profile(make_profile(stage="series_a", as_of=as_of), set(), rubric)
    recency = signal(score, "recent_funding")
    assert recency.status == status
    assert recency.points_min == points
    assert recency.points_max == (points if status == "known" else 10)


def _broken_copy(tmp_path, old: str, new: str) -> Path:
    text = DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "icp.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("weight = 30", "weight = 20", "sum to 100"),
        ('kind = "count"', 'kind = "median"', "invalid rubric schema"),
        ("qualify_min = 60", "qualify_min = 40", "must be above"),
        ('target_kinds = ["customers"]', 'target_kinds = ["blog"]', "not a page kind"),
        ('id = "G3_size_ceiling"', 'id = "G1_b2b"', "gate ids must be unique"),
        ('id = "funding_stage"', 'id = "b2b_software"', "signal ids must be unique"),
    ],
)
def test_rubric_validation_errors(tmp_path, old, new, message):
    with pytest.raises(RubricError, match=message):
        load_rubric(_broken_copy(tmp_path, old, new))


def test_rubric_refuses_invalid_toml_and_weight_mismatch(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(RubricError, match="invalid TOML"):
        load_rubric(bad)

    # weights still sum to 100 but one signal's points no longer reach its weight
    text = DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8")
    swapped = text.replace("weight = 30", "weight = 29", 1).replace("weight = 20", "weight = 21", 1)
    path = tmp_path / "icp.toml"
    path.write_text(swapped, encoding="utf-8")
    with pytest.raises(RubricError, match="differ from weight"):
        load_rubric(path)


def test_rubric_hash_changes_with_file_bytes(tmp_path):
    original = DEFAULT_RUBRIC_PATH.read_bytes()
    assert load_rubric().sha256 == hashlib.sha256(original).hexdigest()

    edited = tmp_path / "icp.toml"
    edited.write_bytes(original + b"# one more byte\n")
    loaded = load_rubric(edited)
    assert loaded.sha256 != load_rubric().sha256
    assert loaded.sha256 == hashlib.sha256(edited.read_bytes()).hexdigest()


def test_repo_rubric_thresholds_are_pinned():
    """Changing the thresholds or the version means editing this test, on purpose: the
    calibration set was written against these numbers before any demo domain was scored."""
    rubric = load_rubric().rubric
    assert rubric.version == "icp.2"
    assert rubric.thresholds.qualify_min == 60
    assert rubric.thresholds.reject_max == 45
    assert rubric.thresholds.unknown_credit == 0.5
    assert rubric.thresholds.qualify_expected == 55
    assert {s.id: s.weight for s in rubric.signals} == {
        "b2b_software": 10,
        "funding_stage": 5,
        "headcount_band": 5,
        "compliance_pursuit": 30,
        "enterprise_customers": 20,
        "security_hiring": 20,
        "regulated_vertical": 10,
    }
    assert sum(s.weight for s in rubric.signals) == 100
    assert [p.id for p in rubric.penalties] == [
        "P1_mature_soc2_type2_and_iso27001",
        "P2_soc2_type2_only",
    ]
    assert [(p.points) for p in rubric.penalties] == [30, 15]


# ---- Task 3: visible verdicts ----


def case_qualification(case_id: str) -> Qualification:
    case = next(c for c in CASES if c["id"] == case_id)
    profile = CompanyProfile.model_validate(case["profile"])
    return qualify(profile, pages_for(case["kinds_usable"]), load_rubric())


def test_render_breakdown_lists_gates_signals_and_penalties():
    q = case_qualification("reject_mature_certified")
    text = render_breakdown(q)
    lines = text.split("\n")

    assert all(line.startswith("    ") for line in lines)
    first = lines[0]
    assert "disqualified" in first
    assert q.reason in first
    assert "score_min 10" in first and "score_max 10" in first and "score_expected 10.0" in first
    assert f"icp.2 sha256={q.rubric_sha256[:12]}" in first

    assert any("G1_b2b" in ln and "pass" in ln for ln in lines)
    assert any("G3_size_ceiling" in ln and "pass" in ln for ln in lines)
    for signal_id in (
        "b2b_software",
        "funding_stage",
        "headcount_band",
        "compliance_pursuit",
        "enterprise_customers",
        "security_hiring",
        "regulated_vertical",
    ):
        assert any(f"signal {signal_id} " in ln for ln in lines), signal_id
    assert any("compliance_pursuit" in ln and "+7" in ln and "known" in ln for ln in lines)
    assert not any("recent_funding" in ln for ln in lines)
    assert any("penalty P1_mature_soc2_type2_and_iso27001" in ln and "-30" in ln for ln in lines)
    assert any('"We hold a SOC 2 Type II report" (https://reject_mature_certified.example/)' in ln for ln in lines)


def test_render_breakdown_strips_control_characters():
    q = case_qualification("fit_series_b_full_signals")
    nasty = "bad \x1b[31mred\x1b[0m\rtext\x7f\nnext"
    compliance = q.score.signals[3].model_copy(
        update={
            "basis": nasty,
            "evidence": [q.score.signals[3].evidence[0].model_copy(update={"quote": nasty})],
        }
    )
    signals = list(q.score.signals)
    signals[3] = compliance
    hostile = q.model_copy(
        update={
            "reason": nasty,
            "score": q.score.model_copy(update={"signals": signals}),
        }
    )

    text = render_breakdown(hostile)

    for bad in ("\x1b", "\r", "\x7f", "\t"):
        assert bad not in text
    assert text.count("\n") == len(text.split("\n")) - 1
    assert "red" in text and "[31m" in text  # the visible remainder is kept, only controls go
    assert all(line.startswith("    ") for line in text.split("\n"))


def test_qualification_from_record_handles_ok_stopped_and_absent(ctx):
    ok = run_one(DOMAIN, ctx)
    from_ok = qualification_from_record(ok)
    assert from_ok is not None and from_ok.verdict == "qualified"

    ctx.fetcher = FakeFetcher(CONSUMER_TEXT)
    responses = default_llm_responses()
    responses["extract"] = consumer_profile()
    ctx.llm = FakeLLM(responses)
    stopped = run_one("stopped.example", ctx)
    from_stopped = qualification_from_record(stopped)
    assert from_stopped is not None and from_stopped.verdict == "disqualified"
    # it also survives the trip through run.json
    assert qualification_from_record(ctx.store.load("stopped.example")) == from_stopped

    ctx.fetcher = FakeFetcher("too short to be a real page")
    early = run_one("early.example", ctx)
    assert early.stop_reason == "insufficient_data"
    assert qualification_from_record(early) is None


THIN_QUOTE = "Flowdesk is a workflow tool that agencies use to run client projects"
THIN_TEXT = (
    THIN_QUOTE
    + ". Teams plan work, share files and keep every client request in one place. "
    "Our team of about 30 people builds the product, and we raised a seed round to grow. "
    "Agencies pick Flowdesk because it keeps projects, tasks and approvals together. "
    "Start a trial, invite your team and move your first project in under an hour. "
    "Templates cover onboarding, retainers, campaigns and reporting for agency work."
)
THIN_QUOTE_B2B = "Agencies pick Flowdesk because it keeps projects"
THIN_QUOTE_STAGE = "we raised a seed round to grow"
THIN_QUOTE_SIZE = "Our team of about 30 people"


def thin_profile(url: str) -> CompanyProfile:
    return CompanyProfile(
        name=EvidencedText(value="Flowdesk", quote="Flowdesk is a workflow tool", source_url=url),
        offering=EvidencedText(
            value="workflow tool for agencies", quote=THIN_QUOTE, source_url=url
        ),
        is_b2b=EvidencedBool(value=True, quote=THIN_QUOTE_B2B, source_url=url),
        stage=StageFact(value="seed", as_of=None, quote=THIN_QUOTE_STAGE, source_url=url),
        headcount=HeadcountFact(value="11-50", quote=THIN_QUOTE_SIZE, source_url=url),
        compliance_mentions=[],
        hiring_signals=[],
        enterprise_customers=[],
    )


class RoutingFetcher:
    """Serves a different page per site; every URL of a site (subdomains included) gets that
    site's text, so only the homepage stays usable (the duplicates are demoted)."""

    def __init__(self, texts: dict[str, str]):
        self.texts = texts
        self.calls: list[str] = []

    def fetch(self, url, site=None):
        self.calls.append(url)
        host = urlparse(url).hostname or ""
        text = SAMPLE_PAGE_TEXT
        for domain, candidate in self.texts.items():
            if host == domain or host.endswith("." + domain):
                text = candidate
        return PageResult(url=url, status="ok", text=text, chars=len(text))


class RoutedLLM(FakeLLM):
    """Answers the extract call with the profile that belongs to the page text it was given."""

    def __init__(self):
        super().__init__(on_call=self._route)

    def _route(self, purpose, call):
        if purpose != "extract":
            return
        if "Pocket Pals" in call["prompt"]:
            self.responses["extract"] = _with_url(consumer_profile(), "https://consumer.example/")
        elif "Flowdesk" in call["prompt"]:
            self.responses["extract"] = thin_profile("https://thin.example/")
        else:
            self.responses["extract"] = default_llm_responses()["extract"]


def _with_url(profile: CompanyProfile, url: str) -> CompanyProfile:
    return CompanyProfile.model_validate_json(
        profile.model_dump_json().replace(CONSUMER_URL, url)
    )


def batch_ctx(ctx):
    ctx.fetcher = RoutingFetcher({"consumer.example": CONSUMER_TEXT, "thin.example": THIN_TEXT})
    ctx.llm = RoutedLLM()
    return ctx


def test_batch_prints_breakdowns_and_spends_hunter_only_on_qualified(ctx, fake_hunter):
    batch_ctx(ctx)
    progress = io.StringIO()

    summary = run_batch(
        ["consumer.example", "thin.example", "good.example"], ctx, progress=progress
    )

    assert [r.outcome for r in summary.rows] == ["disqualified", "insufficient_data", "qualified"]
    assert fake_hunter.calls == ["good.example"]
    thin_row = summary.rows[1]
    assert "compliance_pursuit" in thin_row.detail and "unknown" in thin_row.detail

    text = progress.getvalue()
    first = text.index("[1/3] consumer.example -> disqualified")
    second = text.index("[2/3] thin.example -> insufficient_data")
    third = text.index("[3/3] good.example -> qualified")
    assert first < text.index("gate G1_b2b fail") < second
    assert second < text.index("insufficient_data: score 18..88") < third
    assert third < text.rindex("qualified: score_min 95")
    assert text.endswith("\n")


def test_summary_carries_rubric_identity(ctx, tmp_path):
    batch_ctx(ctx)
    summary = run_batch(["good.example"], ctx)
    sha = hashlib.sha256(DEFAULT_RUBRIC_PATH.read_bytes()).hexdigest()

    assert summary.rubric == {"version": "icp.2", "sha256": sha, "file": "icp.toml"}
    lines = render_summary(summary).split("\n")
    assert lines[0] == "SUMMARY mode=dry_run hunter=fixture"
    assert lines[1] == f"rubric icp.2 sha256={sha[:12]}"

    path = write_summary(summary, tmp_path / "out")
    on_disk = json.loads(path.read_text())
    assert on_disk["rubric"]["version"] == "icp.2"
    assert on_disk["rubric"]["sha256"] == sha
