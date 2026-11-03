"""`outreach run`: CLI tests with fakes. Nothing here touches the network."""

from __future__ import annotations

import json

from typer.testing import CliRunner

import outreach.cli as cli_mod
from outreach.cli import app


def test_run_cli_domains_file_prints_summary_table(ctx, settings, fake_sender, tmp_path, monkeypatch):
    domains = tmp_path / "domains.txt"
    domains.write_text("example.com\nexample.org\n", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "load_settings", lambda **kw: settings)
    monkeypatch.setattr(cli_mod, "build_context", lambda s, **kw: ctx)

    result = CliRunner().invoke(app, ["run", str(domains)])

    assert result.exit_code == 0, result.output
    assert "MODE: dry-run" in result.output
    assert "DRY RUN - Resend NOT called" in result.output
    assert "SUMMARY" in result.output
    assert "example.com" in result.output
    assert "example.org" in result.output
    assert "outcomes: qualified=2" in result.output
    assert result.output.strip().splitlines()[-1].startswith("batch=complete domains=2")
    assert fake_sender.calls == []
    summary = json.loads((settings.out_dir / "_batch" / "summary.json").read_text())
    assert len(summary["rows"]) == 2


# ---- Task 2: flags, exit codes and the Resend switch ----

from urllib.parse import urlparse  # noqa: E402

from conftest import SAMPLE_PAGE_TEXT, FakeLLM  # noqa: E402
from outreach.llm import LLMAuthError  # noqa: E402
from outreach.models import PageResult  # noqa: E402


class ThinOrOkFetcher:
    """Hosts in `thin` return a 30-character page, everything else the sample page."""

    def __init__(self, thin=()):
        self.thin = set(thin)
        self.calls: list[str] = []

    def fetch(self, url, site=None):
        self.calls.append(url)
        host = urlparse(url).hostname or ""
        thin = any(host == n or host.endswith("." + n) for n in self.thin)
        text = "x" * 30 if thin else SAMPLE_PAGE_TEXT
        return PageResult(url=url, status="ok", text=text, chars=len(text))


FETCHER_CLASSES = [ThinOrOkFetcher]


def _patch(monkeypatch, settings, ctx):
    seen: dict = {}

    def fake_load(**kw):
        seen["require"] = tuple(kw["require"])
        return settings

    def fake_build(s, **kw):
        seen["build"] = kw
        ctx.dry_run = kw["dry_run"]
        return ctx

    monkeypatch.setattr(cli_mod, "load_settings", fake_load)
    monkeypatch.setattr(cli_mod, "build_context", fake_build)
    return seen


def _file(tmp_path, *domains):
    f = tmp_path / "domains.txt"
    f.write_text("\n".join(domains) + "\n", encoding="utf-8")
    return str(f)


def test_run_cli_defaults_to_dry_run_and_never_sends(
    ctx, settings, fake_sender, tmp_path, monkeypatch
):
    seen = _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(app, ["run", _file(tmp_path, "example.com", "example.org")])

    assert result.exit_code == 0, result.output
    assert seen["build"] == {"hunter_fixture": True, "dry_run": True}
    assert set(seen["require"]) == {"GEMINI_API_KEY", "OWNER_EMAIL"}
    assert fake_sender.calls == []
    assert "MODE: dry-run (Resend will NOT be called)" in result.output


def test_run_cli_send_flag_calls_sender_once_per_completed_domain(
    ctx, settings, fake_sender, tmp_path, monkeypatch
):
    ctx.fetcher = ThinOrOkFetcher(thin={"thin.example"})
    seen = _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(
        app, ["run", _file(tmp_path, "a.example", "thin.example", "b.example"), "--send"]
    )

    assert result.exit_code == 0, result.output
    assert seen["build"]["dry_run"] is False
    assert "RESEND_API_KEY" in seen["require"]
    assert result.output.startswith("MODE: SEND")
    assert f"recipient forced to {settings.owner_email}" in result.output
    assert len(fake_sender.calls) == 2
    assert all(payload["to"] == [settings.owner_email] for payload, _ in fake_sender.calls)
    summary = json.loads((settings.out_dir / "_batch" / "summary.json").read_text())
    assert [(r["domain"], r["outcome"]) for r in summary["rows"]] == [
        ("a.example", "sent"),
        ("thin.example", "insufficient_data"),
        ("b.example", "sent"),
    ]
    assert summary["mode"] == "send"


def test_run_cli_live_hunter_flag_selects_real_client(ctx, settings, tmp_path, monkeypatch):
    seen = _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(app, ["run", _file(tmp_path, "example.com"), "--live-hunter"])

    assert result.exit_code == 0, result.output
    assert seen["build"]["hunter_fixture"] is False
    assert seen["build"]["dry_run"] is True
    assert "HUNTER_API_KEY" in seen["require"]
    assert "cache-first" in result.output and "budget" in result.output


def test_run_cli_aborted_batch_exits_three(ctx, settings, tmp_path, monkeypatch):
    ctx.llm = FakeLLM(raise_on={"extract": LLMAuthError("bad key")})
    _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(app, ["run", _file(tmp_path, "a.example", "b.example")])

    assert result.exit_code == 3, result.output
    assert "ABORTED" in result.output
    assert result.output.strip().splitlines()[-1].startswith("batch=aborted")
    summary = json.loads((settings.out_dir / "_batch" / "summary.json").read_text())
    assert summary["aborted"] is True
    assert len(summary["rows"]) == 2


def test_run_cli_abort_output_never_contains_the_key(ctx, settings, tmp_path, monkeypatch):
    from conftest import CANARY_ENV

    canary = CANARY_ENV["GEMINI_API_KEY"]
    ctx.llm = FakeLLM(raise_on={"extract": LLMAuthError(f"key {canary} rejected")})
    _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(app, ["run", _file(tmp_path, "a.example")])

    assert result.exit_code == 3
    assert "***" in result.output
    assert canary not in result.output


def test_run_cli_has_no_interactive_prompt(ctx, settings, tmp_path, monkeypatch):
    _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(app, ["run", _file(tmp_path, "example.com")], input="")
    assert result.exit_code == 0, result.output


def test_run_cli_missing_file_exits_two(tmp_path):
    result = CliRunner().invoke(app, ["run", str(tmp_path / "nope.txt")])
    assert result.exit_code == 2


def test_run_cli_cap_exits_two(ctx, settings, tmp_path, monkeypatch):
    _patch(monkeypatch, settings, ctx)
    domains = [f"d{i}.example" for i in range(26)]
    result = CliRunner().invoke(app, ["run", _file(tmp_path, *domains)])

    assert result.exit_code == 2
    assert "per-run cap is 25" in result.output


def test_run_cli_reports_invalid_lines_in_banner_and_table(ctx, settings, tmp_path, monkeypatch):
    _patch(monkeypatch, settings, ctx)
    result = CliRunner().invoke(app, ["run", _file(tmp_path, "example.com", "localhost")])

    assert result.exit_code == 0, result.output
    assert "invalid: 1" in result.output
    assert "localhost" in result.output
    assert "failed=1" in result.output
