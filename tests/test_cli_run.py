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
