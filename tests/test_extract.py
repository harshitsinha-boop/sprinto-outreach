"""Extraction: evidence-quoted CompanyProfile, verbatim-quote validation, untrusted page text."""

from __future__ import annotations

import json

from conftest import (
    HOME_URL,
    QUOTE_CUSTOMERS,
    QUOTE_HEADCOUNT,
    QUOTE_HIRING,
    QUOTE_NAME,
    QUOTE_SOC2,
    SAMPLE_PAGE_TEXT,
    FakeLLM,
    default_llm_responses,
)
from outreach.extract import extract_profile, validate_profile
from outreach.llm import gemini_schema
from outreach.models import (
    CompanyProfile,
    ComplianceMention,
    EvidencedBool,
    EvidencedText,
    HeadcountFact,
    PageResult,
    StageFact,
)
from outreach.skeleton import run_one

ABOUT_URL = "https://example.com/about"
ABOUT_TEXT = (
    "Founded in 2019, Acme Ledger raised a Series B round in March 2024 to expand its "
    "finance automation platform across Europe."
)
DOMAIN = "example.com"


def make_page(url: str, text: str, *, final_url: str | None = None) -> PageResult:
    return PageResult(url=url, status="ok", text=text, chars=len(text), final_url=final_url)


def home_page() -> PageResult:
    return make_page(HOME_URL, SAMPLE_PAGE_TEXT)


def empty_profile(**overrides) -> CompanyProfile:
    base = dict(
        name=None,
        offering=None,
        is_b2b=None,
        stage=None,
        headcount=None,
        compliance_mentions=[],
        hiring_signals=[],
        enterprise_customers=[],
    )
    base.update(overrides)
    return CompanyProfile(**base)


def soc2(quote: str, url: str = HOME_URL, **kw) -> ComplianceMention:
    return ComplianceMention(
        framework="SOC 2", status="in_progress", as_of=kw.get("as_of"), quote=quote, source_url=url
    )


def _all_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(node, list):
        for x in node:
            yield from _all_keys(x)


def _nullable(prop: dict) -> bool:
    return any(branch.get("type") == "null" for branch in prop.get("anyOf", []))


# ---------------------------------------------------------------- schema


def test_company_profile_schema_requires_every_field_and_has_no_defaults():
    schema = gemini_schema(CompanyProfile)
    fields = {
        "name",
        "offering",
        "is_b2b",
        "stage",
        "headcount",
        "compliance_mentions",
        "hiring_signals",
        "enterprise_customers",
    }
    assert set(schema["required"]) == fields
    assert "default" not in set(_all_keys(schema))
    for scalar in ("name", "offering", "is_b2b", "stage", "headcount"):
        assert _nullable(schema["properties"][scalar]), scalar
    for listed in ("compliance_mentions", "hiring_signals", "enterprise_customers"):
        assert schema["properties"][listed]["type"] == "array"
        assert not _nullable(schema["properties"][listed]), listed


# ---------------------------------------------------------------- validation


def test_valid_evidence_is_kept():
    profile = default_llm_responses()["extract"]

    kept, drops, checked = validate_profile(profile, [home_page()])

    assert drops == []
    assert checked == 9  # name, offering, is_b2b, headcount + 1 compliance + 1 hiring + 3 customers
    assert kept == profile


def test_quote_not_on_page_is_dropped():
    profile = empty_profile(
        compliance_mentions=[soc2("working towards SOC2 attestation this year")]
    )

    kept, drops, checked = validate_profile(profile, [home_page()])

    assert kept.compliance_mentions == []
    assert checked == 1
    assert [(d.field, d.reason) for d in drops] == [("compliance_mentions[0]", "quote_not_on_page")]
    assert drops[0].source_url == HOME_URL


def test_quote_on_other_page_is_dropped():
    about = make_page(ABOUT_URL, ABOUT_TEXT)
    profile = empty_profile(
        stage=StageFact(
            value="series_b", as_of=None, quote="raised a Series B round", source_url=HOME_URL
        ),
        compliance_mentions=[soc2(QUOTE_SOC2)],
    )

    kept, drops, _ = validate_profile(profile, [home_page(), about])

    assert kept.stage is None
    assert len(kept.compliance_mentions) == 1  # the home page quote on the home page stays
    assert [(d.field, d.reason) for d in drops] == [("stage", "quote_not_on_page")]


def test_unknown_source_url_is_dropped():
    profile = empty_profile(compliance_mentions=[soc2(QUOTE_SOC2, url="https://evil.example/")])

    kept, drops, _ = validate_profile(profile, [home_page()])

    assert kept.compliance_mentions == []
    assert [d.reason for d in drops] == ["unknown_source_url"]


def test_short_quote_is_dropped():
    profile = empty_profile(compliance_mentions=[soc2("SOC 2")])

    kept, drops, _ = validate_profile(profile, [home_page()])

    assert kept.compliance_mentions == []
    assert [d.reason for d in drops] == ["quote_too_short"]


def test_scalar_with_bad_quote_becomes_null():
    profile = empty_profile(
        name=EvidencedText(value="Acme Ledger", quote=QUOTE_NAME, source_url=HOME_URL),
        headcount=HeadcountFact(
            value="201-500", quote="We employ more than 300 people", source_url=HOME_URL
        ),
    )

    kept, drops, checked = validate_profile(profile, [home_page()])

    assert kept.headcount is None
    assert kept.name is not None and kept.name.value == "Acme Ledger"
    assert checked == 2
    assert [(d.field, d.reason) for d in drops] == [("headcount", "quote_not_on_page")]


def test_whitespace_reflowed_quote_is_kept():
    page = make_page(
        HOME_URL, "We are hiring a\n  Security   Engineer to own\ncompliance at Acme Ledger."
    )
    profile = empty_profile(
        is_b2b=EvidencedBool(
            value=True, quote="hiring a Security Engineer to own compliance", source_url=HOME_URL
        )
    )

    kept, drops, _ = validate_profile(profile, [page])

    assert drops == []
    assert kept.is_b2b is not None


def test_final_url_citation_is_accepted():
    page = make_page(HOME_URL, SAMPLE_PAGE_TEXT, final_url="https://www.example.com/start")
    profile = empty_profile(
        compliance_mentions=[
            soc2(QUOTE_SOC2, url="https://www.example.com/start"),
            soc2(QUOTE_SOC2, url="https://example.com"),  # trailing slash differs only
        ]
    )

    kept, drops, _ = validate_profile(profile, [page])

    assert drops == []
    assert len(kept.compliance_mentions) == 2


def test_as_of_not_on_page_is_cleared():
    profile = empty_profile(
        stage=StageFact(
            value="series_b",
            as_of="March 2021",
            quote="raised a Series B round in March 2024",
            source_url=ABOUT_URL,
        ),
        compliance_mentions=[soc2(QUOTE_SOC2, as_of="2022")],
    )

    kept, drops, checked = validate_profile(
        profile, [home_page(), make_page(ABOUT_URL, ABOUT_TEXT)]
    )

    assert kept.stage is not None and kept.stage.value == "series_b"
    assert kept.stage.as_of is None
    assert kept.compliance_mentions[0].as_of is None
    assert checked == 2
    assert [(d.field, d.reason) for d in drops] == [
        ("stage.as_of", "as_of_not_on_page"),
        ("compliance_mentions[0].as_of", "as_of_not_on_page"),
    ]


def test_as_of_on_page_is_kept():
    profile = empty_profile(
        stage=StageFact(
            value="series_b",
            as_of="March 2024",
            quote="raised a Series B round in March 2024",
            source_url=ABOUT_URL,
        )
    )

    kept, drops, _ = validate_profile(profile, [make_page(ABOUT_URL, ABOUT_TEXT)])

    assert drops == []
    assert kept.stage is not None and kept.stage.as_of == "March 2024"


# ---------------------------------------------------------------- through the runner


def test_unknown_facts_stay_null_through_run_one(ctx):
    rec = run_one(DOMAIN, ctx)

    assert rec.status == "dry_run"
    extract = next(s for s in rec.stages if s.name == "extract")
    out = extract.output
    assert out["profile"]["stage"] is None  # the pages never state a funding stage
    assert out["profile"]["name"]["value"] == "Acme Ledger"
    assert out["profile"]["headcount"]["value"] == "51-200"
    assert out["pages_used"] == [HOME_URL]  # the fake serves one text, so duplicates are unusable
    assert out["evidence_dropped"] == []


def test_extract_stage_records_evidence_counts_in_run_json(ctx):
    run_one(DOMAIN, ctx)

    data = json.loads(ctx.store.path_for(DOMAIN).read_text())
    extract = next(s for s in data["stages"] if s["name"] == "extract")["output"]
    assert extract["evidence_total"] == 9
    assert extract["evidence_kept"] == 9
    assert extract["evidence_dropped"] == []
    assert extract["injection_suspected_pages"] == []
    assert HOME_URL in extract["pages_used"]
    quotes = {QUOTE_NAME, QUOTE_SOC2, QUOTE_HIRING, QUOTE_HEADCOUNT, QUOTE_CUSTOMERS}
    dumped = json.dumps(extract["profile"])
    for quote in quotes:
        assert quote in dumped


def test_extract_profile_drops_are_counted_and_logged():
    responses = default_llm_responses()
    responses["extract"].compliance_mentions.append(soc2("a made up compliance statement"))
    llm = FakeLLM(responses)

    out = extract_profile(llm, "fast-model", [home_page()])

    assert out.evidence_total == 10
    assert out.evidence_kept == 9
    assert [d.reason for d in out.evidence_dropped] == ["quote_not_on_page"]
    assert llm.calls[0]["schema"] is CompanyProfile
    assert llm.calls[0]["purpose"] == "extract"
