"""Qualification: rubric loading and hashing, the pure interval scorer, verdict rules, the
printed breakdown and the zero-Hunter guarantee. Everything is offline (conftest fakes)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import (
    CANARY_ENV,
    FakeFetcher,
    FakeLLM,
    default_llm_responses,
)
from outreach.models import (
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
    final_verdict,
    initial_verdict,
    load_rubric,
    qualify,
    score_profile,
)
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
        "hunter",
        "draft",
        "send",
    ]
    qualify_out = rec.stages[2].output
    assert qualify_out["verdict"] == "qualified"
    assert qualify_out["score"]["score_min"] == 80
    assert qualify_out["score"]["score_max"] == 100
    assert qualify_out["score"]["unknown_signals"] == ["funding_stage", "recent_funding"]

    expected_sha = hashlib.sha256(DEFAULT_RUBRIC_PATH.read_bytes()).hexdigest()
    assert rec.rubric["sha256"] == expected_sha
    assert rec.rubric["version"] == "icp.1"
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
    assert len(q.score.signals) == 8


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

    q = qualify(profile, pages_for(case["kinds_usable"]), loaded)

    assert q.initial_verdict == expect["initial_verdict"]
    assert q.verdict == expect["verdict"]
    assert q.score.score_min == expect["score_min"]
    assert q.score.score_max == expect["score_max"]
    if "gate_failed" in expect:
        assert [g.id for g in q.score.gates if g.status == "fail"] == [expect["gate_failed"]]
    if "penalties" in expect:
        assert [p.id for p in q.score.penalties] == expect["penalties"]
    if "decided_with_unknowns" in expect:
        assert q.decided_with_unknowns == expect["decided_with_unknowns"]
    # the same verdicts through the two public verdict functions
    assert initial_verdict(q.score, loaded.rubric) == expect["initial_verdict"]
    assert final_verdict(q.score, loaded.rubric)[0] == expect["verdict"]


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
    assert len(score.unknown_signals) == 8
    assert score.unknown_signals[0] == "compliance_pursuit"
    for s in score.signals:
        assert (s.status, s.points_min, s.points_max) == ("unknown", 0, s.weight)
    assert [g.status for g in score.gates] == ["unknown", "unknown"]

    one_known = score_profile(make_profile(is_b2b=True), set(), rubric)
    assert (one_known.score_min, one_known.score_max) == (10, 100)


def test_penalty_lowers_both_bounds_with_floor_zero():
    rubric = load_rubric().rubric
    both = make_profile(
        is_b2b=None, compliance=[("SOC 2 Type II", "certified"), ("ISO 27001", "certified")]
    )
    score = score_profile(both, set(), rubric)
    assert [p.id for p in score.penalties] == ["P1_mature_soc2_type2_and_iso27001"]
    assert score.score_min == 0  # 6 - 30 floors at 0
    assert score.score_max == 81 - 30

    type_two_only = make_profile(is_b2b=None, compliance=[("SOC 2 Type 2", "certified")])
    score = score_profile(type_two_only, set(), rubric)
    assert [p.id for p in score.penalties] == ["P2_soc2_type2_only"]
    assert score.score_max == 81 - 15
    assert all(p.evidence for p in score.penalties)

    type_one = make_profile(is_b2b=None, compliance=[("SOC 2 Type I", "certified")])
    assert score_profile(type_one, set(), rubric).penalties == []


def test_empty_list_is_unknown_until_its_page_kind_is_read():
    rubric = load_rubric().rubric
    profile = make_profile()

    blind = signal(score_profile(profile, {"home"}, rubric), "compliance_pursuit")
    assert (blind.status, blind.points_min, blind.points_max) == ("unknown", 0, 25)
    assert blind.basis == "unknown: no security page read"

    read = signal(score_profile(profile, {"home", "security"}, rubric), "compliance_pursuit")
    assert (read.status, read.points_min, read.points_max) == ("known", 0, 0)
    assert read.basis == "no item; security page read"

    customers = signal(score_profile(profile, {"customers"}, rubric), "enterprise_customers")
    assert customers.status == "known" and customers.points_max == 0


@pytest.mark.parametrize(
    ("role", "points", "status"),
    [
        ("Head of IT", 5, "known"),
        ("Itinerary Planner", 0, "known"),
        ("Security Engineer", 15, "known"),
        ("Staff SRE", 5, "known"),
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
    rubric = load_rubric().rubric
    assert rubric.thresholds.reference_year == 2026
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
        ("weight = 25", "weight = 20", "sum to 100"),
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
    swapped = text.replace("weight = 25", "weight = 24", 1).replace("weight = 15", "weight = 16", 1)
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
    assert rubric.version == "icp.1"
    assert rubric.thresholds.qualify_min == 60
    assert rubric.thresholds.reject_max == 45
    assert sum(s.weight for s in rubric.signals) == 100
