"""Send guards, decision.md, `show` and `--replay`. All offline."""

from __future__ import annotations

import io
import json

import httpx
from typer.testing import CliRunner

import outreach.cli as cli_mod
from conftest import (
    CANARY_ENV,
    FIXTURE_DIR,
    SAMPLE_HTML,
    FakeGenaiClient,
    FakeHunter,
    FakeSender,
    default_llm_responses,
    text_response,
)
from outreach.audit import RunStore
from outreach.cli import app
from outreach.decision import render_decision
from outreach.fetch import PageFetcher
from outreach.hunter import HunterClient
from outreach.llm import LLMClient
from outreach.skeleton import Context, run_one


def test_send_forces_owner_prefixes_subject_and_uses_idempotency_key(ctx, fake_sender):
    ctx.dry_run = False
    ctx.hunter = FakeHunter(
        emails_override=[
            {"value": "someone@else.com", "first_name": "Sam", "last_name": "Else", "position": "CTO",
             "confidence": 95, "seniority": "executive", "verification": {"status": "valid"}}
        ]
    )
    # the canned draft greets Richard; greet Sam so the validator passes
    responses = default_llm_responses()
    responses["draft"].body = responses["draft"].body.replace("Hi Richard", "Hi Sam")
    ctx.llm.responses = responses
    rec = run_one("example.com", ctx)
    assert rec.status == "sent", (rec.status, rec.stop_reason)
    payload, options = fake_sender.calls[0]
    assert payload["to"] == [CANARY_ENV["OWNER_EMAIL"]]
    assert payload["subject"].startswith("[TEST -> Sam Else <someone@else.com>] ")
    assert options["idempotency_key"].startswith("outreach-example.com-")


def test_missing_message_id_is_an_error(ctx):
    ctx.dry_run = False
    ctx.sender = FakeSender(response={})
    try:
        run_one("example.com", ctx)
    except Exception as exc:
        assert "message id" in str(exc)
    else:
        raise AssertionError("expected a send error")


def test_decision_md_is_written_and_explains_company_person_email(ctx):
    rec = run_one("example.com", ctx)
    path = ctx.store.path_for("example.com").parent / "decision.md"
    text = path.read_text()
    assert text == render_decision(rec)
    for needle in ("## 1. Why this company", "signal ", "## 2. Why this person", "Top candidates",
                   "## 3. Why this email", "Hook-to-evidence map", "| E1 |", "Validator: passed", "## 4. Send"):
        assert needle in text, needle


def test_decision_for_stopped_runs(ctx):
    ctx.hunter = FakeHunter(emails_override=[])
    text = render_decision(run_one("example.com", ctx))
    assert "(no_contact)" in text and "No contact" in text and "## 3. Why this email\nNot reached." in text


def test_show_command_prints_the_log(ctx, settings):
    run_one("example.com", ctx)
    result = CliRunner().invoke(app, ["show", "example.com", "--out-dir", str(settings.out_dir)])
    assert result.exit_code == 0 and "Decision log: example.com" in result.output
    missing = CliRunner().invoke(app, ["show", "nope.example", "--out-dir", str(settings.out_dir)])
    assert missing.exit_code == 1


def _real_ctx(settings, queue, calls):
    def page(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=SAMPLE_HTML.encode(), headers={"content-type": "text/html"})

    def hunter(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=json.loads((FIXTURE_DIR / "hunter_domain_search.json").read_text()))

    return Context(
        settings=settings,
        llm=LLMClient("k-not-used-1", settings.cache_dir / "llm", client=FakeGenaiClient(queue), sleep=lambda s: None),
        hunter=HunterClient("h-not-used-1", settings.cache_dir / "hunter", 25,
                            http=httpx.Client(transport=httpx.MockTransport(hunter))),
        fetcher=PageFetcher(settings.cache_dir / "pages", http=httpx.Client(transport=httpx.MockTransport(page))),
        store=RunStore(settings.out_dir),
        out=io.StringIO(),
    )


def test_replay_reproduces_a_run_from_caches_with_no_network(settings, tmp_path, monkeypatch):
    r = default_llm_responses()
    queue = [text_response(r[k].model_dump_json()) for k in ("extract", "pain_points", "draft")]
    calls: list[str] = []
    first = run_one("example.com", _real_ctx(settings, queue, calls))
    assert first.status == "dry_run" and calls

    domains = tmp_path / "d.txt"
    domains.write_text("example.com\n")
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    # any attempt to reach the network during replay would blow up here
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    result = CliRunner().invoke(app, ["run", str(domains), "--replay", "--live-hunter"])
    assert result.exit_code == 0, result.output
    assert "MODE: replay" in result.output and "qualified=1" in result.output


def test_replay_miss_is_a_failed_domain_not_a_live_call(settings, tmp_path, monkeypatch):
    domains = tmp_path / "d.txt"
    domains.write_text("uncached.example\n")
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    result = CliRunner().invoke(app, ["run", str(domains), "--replay"])
    assert result.exit_code == 0 and "failed=1" in result.output


def test_replay_refuses_send(settings, tmp_path, monkeypatch):
    domains = tmp_path / "d.txt"
    domains.write_text("example.com\n")
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    assert CliRunner().invoke(app, ["run", str(domains), "--replay", "--send"]).exit_code == 2


def test_demo_script_runs_offline_and_covers_every_outcome(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "demo.py"
    spec = importlib.util.spec_from_file_location("demo_script", path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    monkeypatch.setattr(demo, "OUT", tmp_path / "demo")
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert demo.main() == 0
    out = capsys.readouterr().out
    for outcome in ("qualified", "disqualified", "insufficient_data", "no_contact", "failed"):
        assert outcome in out
    assert (tmp_path / "demo" / "summary.txt").exists()
