"""Batch runner: loader, per-domain outcome mapping and summary rendering. All offline."""

from __future__ import annotations

import json

from outreach.models import OUTCOMES
from outreach.runner import load_domains, render_summary, run_batch


def test_load_domains_normalises_dedupes_and_skips_comments(tmp_path):
    f = tmp_path / "domains.txt"
    f.write_text(
        "# demo set\n"
        "\n"
        "https://WWW.Example.com/about\n"
        "example.com\n"
        "acme.io   # trailing comment\n",
        encoding="utf-8",
    )
    assert load_domains(f) == ["example.com", "acme.io"]


def test_run_batch_runs_every_domain_in_order_and_maps_outcomes(ctx):
    summary = run_batch(["example.com", "example.org"], ctx)

    assert [r.domain for r in summary.rows] == ["example.com", "example.org"]
    assert [r.outcome for r in summary.rows] == ["qualified", "qualified"]
    assert set(summary.counts) == set(OUTCOMES)
    assert summary.counts["qualified"] == 2
    assert summary.mode == "dry_run"
    assert summary.aborted is False
    for row in summary.rows:
        assert row.run_record is not None
        assert json.loads(open(row.run_record).read())["domain"] == row.domain


def test_render_summary_lists_every_domain_and_all_seven_counts(ctx):
    summary = run_batch(["example.com", "example.org"], ctx)
    text = render_summary(summary)

    assert text.splitlines()[0] == "SUMMARY mode=dry_run hunter=fixture"
    assert "example.com" in text
    assert "example.org" in text
    assert (
        "outcomes: qualified=2 disqualified=0 insufficient_data=0 no_contact=0 "
        "rejected_draft=0 sent=0 failed=0"
    ) in text
