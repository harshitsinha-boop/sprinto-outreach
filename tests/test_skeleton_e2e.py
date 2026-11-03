"""End-to-end tracer: one domain through six stages, offline, with fakes at the client seams."""

from __future__ import annotations

import io
import json

import httpx
import pytest
from typer.testing import CliRunner

import outreach.cli as cli_mod
from conftest import (
    CANARY_ENV,
    FIXTURE_DIR,
    SAMPLE_HTML,
    SAMPLE_PAGE_TEXT,
    FakeFetcher,
    FakeGenaiClient,
    FakeHunter,
    default_llm_responses,
    text_response,
)
from outreach.audit import RunStore
from outreach.cli import app, build_context
from outreach.config import ENV_MAP
from outreach.fetch import PageFetcher
from outreach.hunter import FixtureHunter, HunterClient
from outreach.llm import LLMClient
from outreach.skeleton import Context, run_one

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


# ---- Plan 01-03: real clients behind the seams, and the CLI ----


def _real_ctx(settings, genai_queue, page_html, page_counter, hunter_counter):
    """Real LLMClient, PageFetcher and HunterClient over fake transports, on shared cache dirs."""

    def page_handler(request: httpx.Request) -> httpx.Response:
        page_counter.append(str(request.url))
        return httpx.Response(200, content=page_html.encode(), headers={"content-type": "text/html"})

    def hunter_handler(request: httpx.Request) -> httpx.Response:
        hunter_counter.append(str(request.url))
        return httpx.Response(200, json=json.loads((FIXTURE_DIR / "hunter_domain_search.json").read_text()))

    llm = LLMClient(
        CANARY_ENV["GEMINI_API_KEY"],
        settings.cache_dir / "llm",
        client=FakeGenaiClient(genai_queue),
        sleep=lambda s: None,
    )
    fetcher = PageFetcher(
        settings.cache_dir / "pages", http=httpx.Client(transport=httpx.MockTransport(page_handler))
    )
    hunter = HunterClient(
        CANARY_ENV["HUNTER_API_KEY"],
        settings.cache_dir / "hunter",
        settings.hunter_monthly_budget,
        http=httpx.Client(transport=httpx.MockTransport(hunter_handler)),
    )
    return Context(
        settings=settings,
        llm=llm,
        hunter=hunter,
        fetcher=fetcher,
        store=RunStore(settings.out_dir),
        dry_run=True,
        sender=None,
        out=io.StringIO(),
    )


def test_rerun_makes_zero_gemini_and_hunter_calls(settings):
    responses = default_llm_responses()
    queue = [
        text_response(responses["extract"].model_dump_json()),
        text_response(responses["draft"].model_dump_json()),
    ]
    pages1, hunter1 = [], []
    ctx1 = _real_ctx(settings, queue, SAMPLE_HTML, pages1, hunter1)
    rec1 = run_one(DOMAIN, ctx1)
    assert rec1.status == "dry_run"
    assert ctx1.llm.stats.api_calls == 2
    assert ctx1.hunter.live_calls_this_process == 1
    assert len(pages1) >= 2 and len(hunter1) == 1

    # Second run: NEW client instances on the same cache dirs, nothing queued for Gemini,
    # and a site that now serves different HTML (it must never be fetched).
    pages2, hunter2 = [], []
    other_html = SAMPLE_HTML.replace("Acme Ledger", "Changed Name Co")
    ctx2 = _real_ctx(settings, [], other_html, pages2, hunter2)
    rec2 = run_one(DOMAIN, ctx2)
    assert rec2.status == "dry_run"
    assert ctx2.llm.stats.api_calls == 0
    assert ctx2.llm.stats.cache_hits == 2
    assert ctx2.hunter.live_calls_this_process == 0
    assert pages2 == [] and hunter2 == []
    assert ctx2.llm._c.models.calls == []
    assert rec2.counters["llm_api_calls"] == 0 and rec2.counters["hunter_live_calls"] == 0


def test_build_context_wires_real_clients(settings):
    ctx = build_context(settings)
    assert isinstance(ctx.llm, LLMClient)
    assert isinstance(ctx.fetcher, PageFetcher)
    assert isinstance(ctx.hunter, HunterClient)
    assert ctx.dry_run is True and ctx.sender is None
    assert ctx.llm.cache_dir == settings.cache_dir / "llm"
    assert ctx.hunter.dir == settings.cache_dir / "hunter"

    fixture_ctx = build_context(settings, hunter_fixture=True)
    assert isinstance(fixture_ctx.hunter, FixtureHunter)
    assert fixture_ctx.dry_run is True and fixture_ctx.sender is None


def test_skeleton_cli_prints_payload_and_exits_zero(ctx, settings, fake_sender, monkeypatch):
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    monkeypatch.setattr(cli_mod, "build_context", lambda s, **kw: ctx)

    result = CliRunner().invoke(app, ["skeleton"])

    assert result.exit_code == 0, result.output
    assert "MODE: dry-run (Resend will NOT be called)" in result.output
    assert "DRY RUN - Resend NOT called" in result.output
    last = result.output.strip().splitlines()[-1]
    assert last.startswith("status=dry_run run_record=")
    assert last.endswith("llm_api_calls=2 llm_cache_hits=0 hunter_live_calls=0")
    assert fake_sender.calls == []


def test_skeleton_cli_missing_config_names_variables_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env anywhere near
    for name in ENV_MAP:
        monkeypatch.delenv(name, raising=False)

    result = CliRunner().invoke(app, ["skeleton"])

    assert result.exit_code == 2
    assert "GEMINI_API_KEY" in result.output
    assert "HUNTER_API_KEY" in result.output


def test_fixture_hunter_on_other_domain_stops_no_contact(ctx, fake_llm, fake_sender, capsys):
    ctx.hunter = FixtureHunter()

    rec = run_one(DOMAIN, ctx)  # example.com is not the fixture's domain

    assert rec.status == "stopped" and rec.stop_reason == "no_contact"
    assert [c["purpose"] for c in fake_llm.calls] == ["extract"]  # no draft call
    assert "DRY RUN" not in capsys.readouterr().out
    assert fake_sender.calls == []


def test_skeleton_cli_stopped_run_exits_two_with_reason(ctx, settings, monkeypatch):
    ctx.hunter = FixtureHunter()
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    monkeypatch.setattr(cli_mod, "build_context", lambda s, **kw: ctx)

    result = CliRunner().invoke(app, ["skeleton", "--hunter-fixture"])

    assert result.exit_code == 2
    assert "stop_reason=no_contact" in result.output
    assert result.output.strip().splitlines()[-1].startswith("status=stopped ")
    assert "contact only for piedpiper.com" in result.output


def test_skeleton_cli_failure_is_redacted_and_exits_one(ctx, settings, monkeypatch):
    from conftest import FakeLLM

    ctx.llm = FakeLLM(raise_on={"extract": RuntimeError("boom " + CANARY_ENV["GEMINI_API_KEY"])})
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    monkeypatch.setattr(cli_mod, "build_context", lambda s, **kw: ctx)

    result = CliRunner().invoke(app, ["skeleton"])

    assert result.exit_code == 1
    assert "FAILED: RuntimeError: boom ***" in result.output
    assert CANARY_ENV["GEMINI_API_KEY"] not in result.output
    assert "run_record=" in result.output


def test_skeleton_cli_requires_a_domain(ctx, settings, monkeypatch):
    no_domain = settings.model_copy(update={"skeleton_domain": None})
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: no_domain)

    result = CliRunner().invoke(app, ["skeleton"])

    assert result.exit_code == 2
    assert "pass --domain or set SKELETON_DOMAIN" in result.output


def test_smoke_cli_rejects_unknown_check():
    result = CliRunner().invoke(app, ["smoke", "--only", "bogus"])
    assert result.exit_code == 2
