"""Qualification: rubric loading and hashing, the pure interval scorer, verdict rules, the
printed breakdown and the zero-Hunter guarantee. Everything is offline (conftest fakes)."""

from __future__ import annotations

import hashlib

from conftest import (
    CANARY_ENV,
    FakeFetcher,
    FakeLLM,
    default_llm_responses,
)
from outreach.models import (
    CompanyProfile,
    EvidencedBool,
    EvidencedText,
    HeadcountFact,
    Qualification,
)
from outreach.qualify import DEFAULT_RUBRIC_PATH
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
