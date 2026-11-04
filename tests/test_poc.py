"""Deterministic PoC ranking, no_contact and the Hunter budget guards. Offline only."""

from __future__ import annotations

import httpx
import pytest

from conftest import CANARY_ENV, FakeHunter, default_llm_responses
from outreach import hunter as hunter_mod
from outreach.hunter import HunterClient, HunterQuotaError
from outreach.models import HeadcountFact
from outreach.poc import select_contact, size_band, title_category
from outreach.skeleton import run_one


def person(first, position, *, conf=95, status="valid", seniority="senior", **extra):
    return {
        "value": f"{first.lower()}@example.com",
        "first_name": first,
        "last_name": "Test",
        "position": position,
        "confidence": conf,
        "seniority": seniority,
        "verification": {"status": status},
        **extra,
    }


def result(*emails):
    return {"domain": "example.com", "response": {"data": {"emails": list(emails)}}, "source": "fixture"}


def profile(band):
    p = default_llm_responses()["extract"]
    p.headcount = HeadcountFact(value=band, quote="q", source_url="u") if band else None
    return p


def test_title_categories():
    assert title_category("Co-founder and CTO") == "cofounder_cto"
    assert title_category("Chief Information Security Officer") == "security_lead"
    assert title_category("Head of Engineering") == "eng_lead"
    assert title_category("Director of IT") == "it_lead"
    assert title_category("Barista") is None


def test_size_band_defaults_to_mid_and_says_so():
    assert size_band(profile("11-50"))[0] == "small"
    assert size_band(profile("1001+"))[0] == "large"
    band, basis = size_band(profile(None))
    assert band == "mid" and "unknown" in basis


def test_small_company_prefers_cto_but_security_lead_outranks_at_any_size():
    emails = [person("Ceo", "CEO", seniority="executive"), person("Cto", "CTO")]
    assert select_contact(result(*emails), profile("11-50")).contact.first_name == "Cto"
    emails.append(person("Sec", "Head of Security"))
    assert select_contact(result(*emails), profile("11-50")).contact.first_name == "Sec"


def test_mid_prefers_engineering_lead_over_cto_and_large_prefers_compliance_over_eng():
    emails = [person("Cto", "CTO"), person("Eng", "VP Engineering")]
    assert select_contact(result(*emails), profile("51-200")).contact.first_name == "Eng"
    emails = [person("Eng", "VP Engineering"), person("Grc", "Head of GRC")]
    assert select_contact(result(*emails), profile("501-1000")).contact.first_name == "Grc"


def test_negative_keywords_and_unranked_titles_are_excluded_so_no_contact():
    emails = [person("Mark", "Head of Marketing"), person("Sal", "VP Sales"), person("Zed", "Chief Happiness Officer")]
    assert select_contact(result(*emails), profile("51-200")) is None
    assert select_contact(result(), profile("51-200")) is None


def test_confidence_and_tiebreakers_are_deterministic():
    low = person("Low", "CTO", conf=40, status="unknown")
    good = person("Good", "CTO", conf=90, status="valid")
    out = select_contact(result(low, good), profile("11-50"))
    assert out.contact.first_name == "Good"
    # equal scores: linkedin breaks the tie, then the order is stable across input order
    a = person("Aaa", "CTO", linkedin="https://l/a")
    b = person("Bbb", "CTO")
    assert select_contact(result(a, b), profile("11-50")).contact.first_name == "Aaa"
    assert select_contact(result(b, a), profile("11-50")).contact.first_name == "Aaa"
    # a lone low-confidence candidate is still chosen but flagged
    only = select_contact(result(low), profile("11-50"))
    assert only.risks


def test_log_has_top_three_and_a_reason_and_name_title_are_verbatim():
    emails = [person(n, t) for n, t in [("A", "CTO"), ("B", "CEO"), ("C", "VP Engineering"), ("D", "COO")]]
    out = select_contact(result(*emails), profile("11-50"))
    assert len(out.top_candidates) == 3 and out.candidates_seen == 4
    assert "top title match" in out.reason
    assert out.contact.position == "CTO" and out.contact.first_name == "A"


def test_stage_logs_candidates_and_no_contact_drafts_nothing(ctx):
    rec = run_one("example.com", ctx)
    poc = next(s for s in rec.stages if s.name == "poc").output
    assert poc["top_candidates"] and poc["reason"]
    ctx.hunter = FakeHunter(emails_override=[])
    rec = run_one("example.com", ctx)
    assert rec.status == "stopped" and rec.stop_reason == "no_contact"
    assert [s.name for s in rec.stages][-1] == "stopped" or rec.stages[-1].name == "poc"
    assert "draft" not in [s.name for s in rec.stages]


def _client(tmp_path, budget, instance_counter):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"emails": []}})))
    return HunterClient(CANARY_ENV["HUNTER_API_KEY"], tmp_path, budget, http=http, month=lambda: "2099-01", instance_counter=instance_counter)


def test_empty_response_is_cached_and_never_re_fetched(tmp_path):
    c = _client(tmp_path, 5, False)
    c.domain_search("empty.example")
    again = c.domain_search("empty.example")
    assert again["from_cache"] and c.live_calls_this_process == 1


def test_persistent_counter_refuses_beyond_budget(tmp_path):
    c = _client(tmp_path, 1, False)
    c.domain_search("a.example")
    with pytest.raises(HunterQuotaError):
        c.domain_search("b.example")


def test_per_instance_counter_is_a_second_brake(tmp_path, monkeypatch):
    monkeypatch.setattr(hunter_mod, "_INSTANCE_LIVE_CALLS", {})
    first = _client(tmp_path / "one", 1, True)
    first.domain_search("a.example")
    fresh_disk = _client(tmp_path / "two", 1, True)  # a cold /tmp, same warm process
    with pytest.raises(HunterQuotaError, match="per-instance"):
        fresh_disk.domain_search("b.example")
