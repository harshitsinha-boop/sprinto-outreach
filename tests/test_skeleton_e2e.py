"""End-to-end tracer: one domain through six stages, offline, with fakes at the client seams."""

from __future__ import annotations

import json

import pytest

from conftest import CANARY_ENV, SAMPLE_PAGE_TEXT, FakeFetcher, FakeHunter
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


def test_canary_never_leaks(ctx, settings, capsys, caplog):
    import logging

    from conftest import FakeLLM

    canaries = [CANARY_ENV[k] for k in ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY")]
    ctx.llm = FakeLLM(raise_on={"extract": RuntimeError("boom " + CANARY_ENV["GEMINI_API_KEY"])})

    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError):
        run_one(DOMAIN, ctx)
    captured = capsys.readouterr()

    # The failure really was recorded (so the scan below is not vacuous) and redacted.
    data = json.loads(ctx.store.path_for(DOMAIN).read_text())
    assert data["status"] == "failed" and data["failed_stage"] == "extract"
    assert "boom" in data["stages"][-1]["error"] and "***" in data["stages"][-1]["error"]

    haystacks = {
        "stdout": captured.out,
        "stderr": captured.err,
        "caplog": caplog.text,
        "repr(settings)": repr(settings),
        "str(settings)": str(settings),
    }
    for root in (settings.out_dir, settings.cache_dir):
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    haystacks[str(path)] = path.read_bytes().decode("utf-8", errors="replace")
    assert any(name.endswith("run.json") for name in haystacks)
    for canary in canaries:
        for name, text in haystacks.items():
            assert canary not in text, f"canary leaked into {name}"


def test_mixed_pages_short_page_excluded_from_extract_prompt(ctx, fake_llm):
    short = ("short about text " * 4)[:50]
    assert len(short) == 50
    ctx.fetcher = FakeFetcher(
        by_url={"https://example.com/": SAMPLE_PAGE_TEXT, "https://example.com/about": short}
    )

    rec = run_one(DOMAIN, ctx)

    assert rec.status == "dry_run"
    assert rec.stages[0].output["usable"] == 1
    extract_call = next(c for c in fake_llm.calls if c["purpose"] == "extract")
    assert '<page url="https://example.com/">' in extract_call["prompt"]
    assert "https://example.com/about" not in extract_call["prompt"]
    assert short not in extract_call["prompt"]
