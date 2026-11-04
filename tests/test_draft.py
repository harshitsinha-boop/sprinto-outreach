"""Pain points, the deterministic draft validator and the regenerate-once flow. Offline only."""

from __future__ import annotations

from conftest import GOOD_BODY, FakeLLM, default_llm_responses
from outreach.draft import (
    SPRINTO_WHITELIST,
    build_draft,
    build_evidence_pack,
    fallback_pain_points,
    validate_draft,
    validate_pain_points,
)
from outreach.models import ClaimUsed, DraftLLM, HunterContact, PainPoint, PainPointSet
from outreach.skeleton import run_one

CONTACT = HunterContact(first_name="Richard", last_name="Hendricks", email="r@x.com", position="CEO", source="fixture")
PROFILE = default_llm_responses()["extract"]
PACK = build_evidence_pack(PROFILE)
CLAIMS = [ClaimUsed(claim="SOC 2", evidence_id="E1")]


def draft(body=GOOD_BODY, subject="your soc 2 timeline", claims=None):
    return DraftLLM(subject=subject, body=body, claims_used=CLAIMS if claims is None else claims)


def fails(**kw):
    return validate_draft(draft(**kw), CONTACT, PACK, "Acme Ledger")


def has(failures, text):
    return any(text in f for f in failures)


def test_good_draft_passes():
    assert fails() == []


def test_wrong_greeting_name_rejected():
    assert has(fails(body=GOOD_BODY.replace("Hi Richard", "Hi Dinesh")), "differs from Hunter")


def test_word_count_bounds():
    assert has(fails(body="Hi Richard, SOC 2 Type II next?"), "words")
    assert has(fails(body=GOOD_BODY + " word" * 40), "words")


def test_url_and_banned_phrase_and_two_questions():
    assert has(fails(body=GOOD_BODY.replace("Would", "See https://sprinto.com. Would")), "URL")
    assert has(fails(body=GOOD_BODY.replace("Teams", "I hope this finds you well. Teams")), "banned")
    assert has(fails(body=GOOD_BODY.replace("I saw", "Quick question: I saw")), "banned")
    assert has(fails(body=GOOD_BODY.replace("Teams in", "Know the feeling? Teams in")), "question marks")


def test_unsupported_numbers_and_proper_nouns_rejected():
    assert has(fails(body=GOOD_BODY.replace("weeks of focus", "40% of focus")), "number '40'")
    assert has(fails(body=GOOD_BODY.replace("weeks of focus", "three weeks of focus")), "spelled number")
    assert has(fails(body=GOOD_BODY.replace("enterprise deals", "Initech deals")), "proper noun 'Initech'")


def test_sprinto_claims_outside_whitelist_rejected():
    bad = GOOD_BODY.replace(
        "Sprinto automates compliance for SOC 2, ISO 27001 and GDPR, with continuous monitoring and audit-ready evidence collection.",
        "Sprinto helps teams pass audits faster than anyone.",
    )
    assert has(fails(body=bad), "Sprinto claim outside the whitelist")
    assert has(fails(body=GOOD_BODY.replace("Would a short", "We cut audit time. Would a short")), "outside the whitelist")


def test_subject_rules_and_plain_text_and_citation():
    assert has(fails(subject="Your SOC 2 Timeline"), "lowercase")
    assert has(fails(subject="one"), "2 to 5")
    assert has(fails(subject="a very long subject line here ok"), "2 to 5")
    assert has(fails(body=GOOD_BODY.replace("Hi Richard,", "Hi Richard,\n**bold**")), "plain text")
    assert has(fails(claims=[]), "no hook cites")
    assert has(fails(claims=[ClaimUsed(claim="x", evidence_id="E99")]), "unknown id")


def test_pain_points_validation_and_fallback():
    ok = default_llm_responses()["pain_points"].pain_points
    assert validate_pain_points(ok, PACK) == []
    assert validate_pain_points(ok[:1], PACK)
    assert validate_pain_points([ok[0], PainPoint(pain="p", role_link="r", evidence_id="E99")], PACK)
    fb = fallback_pain_points(CONTACT, PACK)
    assert len(fb) == 2 and validate_pain_points(fb, PACK) == []


def test_invalid_llm_pain_points_fall_back_to_the_persona_library():
    bad = PainPointSet(pain_points=[PainPoint(pain="p", role_link="r", evidence_id="E99")])
    llm = FakeLLM({**default_llm_responses(), "pain_points": bad})
    out = build_draft(llm, smart_model="s", fast_model="f", profile=PROFILE, contact=CONTACT)
    assert out.pain_points_source == "persona_library" and len(out.pain_points) == 2


def test_regenerates_once_then_accepts():
    responses = default_llm_responses()
    responses["draft"] = [draft(body=GOOD_BODY.replace("Hi Richard", "Hi Dinesh")), draft()]
    llm = FakeLLM(responses)
    out = build_draft(llm, smart_model="s", fast_model="f", profile=PROFILE, contact=CONTACT)
    assert out.validation.ok and out.validation.attempts == 2
    assert out.validation.attempt_failures[0]
    assert "previous draft failed" in llm.calls[-1]["prompt"]
    assert [c["purpose"] for c in llm.calls] == ["pain_points", "draft", "draft"]


def test_still_failing_after_one_regeneration_ends_as_rejected_draft(ctx):
    responses = default_llm_responses()
    responses["draft"] = draft(body=GOOD_BODY.replace("Hi Richard", "Hi Dinesh"))
    ctx.llm = FakeLLM(responses)
    rec = run_one("example.com", ctx)
    assert rec.status == "stopped" and rec.stop_reason == "rejected_draft"
    assert [c["purpose"] for c in ctx.llm.calls].count("draft") == 2  # one regeneration, no more
    assert "send" not in [s.name for s in rec.stages]


def test_footer_hook_map_and_claims_are_built(ctx):
    rec = run_one("example.com", ctx)
    out = next(s for s in rec.stages if s.name == "draft").output
    body = out["draft"]["body"]
    assert out["core_body"] in body and "reply \"no\"" in body and "[Sender postal address]" in body
    assert len(out["pain_points"]) == 2 and all(p["evidence_id"] for p in out["pain_points"])
    ids = {h["evidence_id"] for h in out["hook_map"]}
    assert {"E1", "E2"} <= ids and all(h["quote"] for h in out["hook_map"])
    assert {c["evidence_id"] for c in out["claims_used"]} >= {"S1"}
    assert out["greets_by_first_name"]
    assert set(SPRINTO_WHITELIST) == {"S1", "S2"}
