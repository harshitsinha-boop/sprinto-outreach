"""End-to-end tracer: one domain through six stages, offline, with fakes at the client seams."""

from __future__ import annotations

import json

from conftest import CANARY_ENV, FakeFetcher, FakeHunter
from outreach.skeleton import run_one

DOMAIN = CANARY_ENV["SKELETON_DOMAIN"]
STAGE_ORDER = ["scrape", "extract", "score", "hunter", "draft", "send"]


def test_one_domain_runs_six_stages_to_dry_run(ctx, capsys):
    rec = run_one(DOMAIN, ctx)

    assert [s.name for s in rec.stages] == STAGE_ORDER
    assert all(s.status == "ok" for s in rec.stages)
    assert rec.status == "dry_run"
    assert rec.finished_at is not None

    on_disk = json.loads(ctx.store.path_for(DOMAIN).read_text())
    assert [s["name"] for s in on_disk["stages"]] == STAGE_ORDER
    assert on_disk["status"] == "dry_run"
    assert on_disk["models"] == {
        "fast": ctx.settings.gemini_model_fast,
        "smart": ctx.settings.gemini_model_smart,
    }
    assert on_disk["counters"]["llm_api_calls"] == 2


def test_dry_run_prints_exact_payload_and_never_calls_sender(ctx, fake_sender, capsys):
    rec = run_one(DOMAIN, ctx)

    out = capsys.readouterr().out
    header = "DRY RUN - Resend NOT called. Exact payload:\n"
    assert header in out
    printed = json.loads(out.split(header, 1)[1])

    send_stage = rec.stages[-1]
    assert send_stage.output["payload"] == printed
    assert send_stage.output["mode"] == "dry_run"
    assert set(printed) == {"from", "to", "subject", "text"}
    assert printed["to"] == ["owner@example.com"]
    assert "richard@piedpiper.com" in printed["subject"]
    assert fake_sender.calls == []


def test_short_page_stops_insufficient_data_before_llm(ctx, fake_llm):
    ctx.fetcher = FakeFetcher("too short to be a real page")

    rec = run_one(DOMAIN, ctx)

    assert rec.status == "stopped"
    assert rec.stop_reason == "insufficient_data"
    assert [s.name for s in rec.stages] == ["scrape"]
    assert rec.stages[0].status == "stopped"
    assert fake_llm.calls == []


def test_no_named_contact_stops_before_draft(ctx, fake_llm):
    ctx.hunter = FakeHunter(emails_override=[])

    rec = run_one(DOMAIN, ctx)

    assert rec.status == "stopped"
    assert rec.stop_reason == "no_contact"
    assert [s.name for s in rec.stages] == ["scrape", "extract", "score", "hunter"]
    assert [c["purpose"] for c in fake_llm.calls] == ["extract"]
