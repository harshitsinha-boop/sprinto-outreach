"""Headcount band must be supported by its quote; G3 can only fire from a validated band."""

from __future__ import annotations

import pytest

from outreach.extract import headcount_reason, stage_reason, validate_profile
from outreach.models import CompanyProfile, HeadcountFact, PageResult, StageFact
from outreach.qualify import load_rubric, qualify

URL = "https://co.example/careers"


def profile_for(quote: str, band: str) -> tuple[CompanyProfile, list[PageResult]]:
    text = f"Careers at Co. {quote}. " + "We build software for finance teams and ship weekly. " * 12
    page = PageResult(url=URL, status="ok", text=text, chars=len(text), kind="careers")
    profile = CompanyProfile(
        name=None, offering=None, is_b2b=None, stage=None,
        headcount=HeadcountFact(value=band, quote=quote, source_url=URL),
        compliance_mentions=[], hiring_signals=[], enterprise_customers=[],
    )
    return profile, [page]


def run(quote, band):
    profile, pages = profile_for(quote, band)
    kept, drops, _ = validate_profile(profile, pages)
    q = qualify(kept, pages, load_rubric())
    return kept, drops, q


def test_attio_case_wrong_band_is_dropped_and_gate_does_not_fire():
    kept, drops, q = run("190+ team members", "1001+")
    assert kept.headcount is None
    assert [(d.field, d.reason) for d in drops] == [("headcount", "headcount_band_mismatch")]
    assert [g.status for g in q.score.gates if g.id == "G3_size_ceiling"] == ["unknown"]
    assert q.verdict != "disqualified" or "G3" not in q.reason


def test_same_quote_with_the_right_band_is_kept():
    kept, drops, _ = run("190+ team members", "51-200")
    assert kept.headcount is not None and kept.headcount.value == "51-200" and drops == []


def test_real_1001_plus_still_fails_the_gate():
    kept, drops, q = run("1,200 employees", "1001+")
    assert kept.headcount is not None and drops == []
    assert q.verdict == "disqualified" and "G3_size_ceiling" in q.reason


@pytest.mark.parametrize(
    ("quote", "band"),
    [
        ("over 10,000 people", "1001+"),
        ("team of 40", "11-50"),
        ("50-120 people", "51-200"),
        ("about 2.5k employees", "1001+"),
        ("10k employees worldwide", "1001+"),
        ("thousands of employees", "1001+"),
        ("1000+ employees", "1001+"),
        ("a team of 30 to 60 people", "11-50"),
        ("40-300 people", "51-200"),  # range overlaps the band
    ],
)
def test_supported_bands_are_kept(quote, band):
    assert headcount_reason(band, quote) is None
    kept, drops, _ = run(quote, band)
    assert kept.headcount is not None and drops == []


def test_quote_without_a_number_is_dropped():
    kept, drops, q = run("a growing team of builders", "51-200")
    assert kept.headcount is None
    assert [d.reason for d in drops] == ["headcount_no_number"]
    assert "headcount_band" in q.score.unknown_signals


@pytest.mark.parametrize(
    ("quote", "band"),
    [("team of 40", "51-200"), ("founded in 2019 by two friends", "1001+"), ("190+ team members", "1001+")],
)
def test_unsupported_bands_are_rejected(quote, band):
    assert headcount_reason(band, quote) in ("headcount_band_mismatch", "headcount_no_number")


def test_gate_defends_itself_against_an_unvalidated_profile():
    # a profile that never went through validate_profile (hand-built or stale) still cannot fire G3
    profile, pages = profile_for("190+ team members", "1001+")
    q = qualify(profile, pages, load_rubric())
    assert all(g.status != "fail" for g in q.score.gates)
    assert "headcount_band" in q.score.unknown_signals


def test_stage_letter_must_agree_with_the_quote():
    assert stage_reason("series_b", "We closed our Series B") is None
    assert stage_reason("series_b", "We closed our Series A") == "stage_mismatch"
    assert stage_reason("series_d_or_later", "our Series A round") == "stage_mismatch"
    assert stage_reason("seed", "backed by a seed round") is None
    profile, pages = profile_for("We are 40 people", "11-50")
    text = pages[0].text.replace("We are 40 people", "We closed our Series A")
    pages[0] = pages[0].model_copy(update={"text": text})
    profile = profile.model_copy(
        update={"headcount": None, "stage": StageFact(value="series_c", as_of=None, quote="We closed our Series A", source_url=URL)}
    )
    kept, drops, _ = validate_profile(profile, pages)
    assert kept.stage is None and [d.reason for d in drops] == ["stage_mismatch"]
