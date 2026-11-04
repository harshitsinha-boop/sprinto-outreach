"""webapi.run_stage: one stage per call, JSON state in and out, offline seams only."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import FakeFetcher, FakeHunter, FakeLLM, FakeSender
from outreach.webapi import STAGE_ORDER, default_data_dir, run_stage


def _drive(settings, *, upto="send", send=False, **seams):
    state = {"domain": "example.com"}
    results = []
    for stage in STAGE_ORDER[: STAGE_ORDER.index(upto) + 1]:
        # the state crosses a JSON boundary between every call, as it does over HTTP
        state = json.loads(json.dumps(state))
        r = run_stage(stage, state, settings=settings, send=send, **seams)
        results.append(r)
        state = r["state"]
        if r["status"] != "ok":
            break
    return results


def _seams(**kw):
    return {
        "llm": kw.get("llm") or FakeLLM(),
        "fetcher": kw.get("fetcher") or FakeFetcher(),
        "hunter": kw.get("hunter") or FakeHunter(),
        "sender": kw.get("sender") or FakeSender(),
    }


def test_full_dry_run_one_stage_per_call(settings):
    results = _drive(settings, **_seams())
    assert [r["stage"] for r in results] == list(STAGE_ORDER)
    assert all(r["status"] == "ok" for r in results), [(r["stage"], r["detail"]) for r in results]
    last = results[-1]
    assert last["result"]["mode"] == "dry_run"
    assert last["state"]["send"]["payload"]["to"] == [settings.owner_email]
    assert set(STAGE_ORDER) <= set(last["state"])
    json.dumps(last)  # fully JSON-safe


def test_scrape_result_has_no_page_bodies_but_state_keeps_them(settings):
    r = run_stage("scrape", {"domain": "example.com"}, settings=settings, **_seams())
    assert all("text" not in p for p in r["result"]["pages"])
    assert r["state"]["scrape"]["pages"][0]["text"]


def test_stopped_is_not_failed(settings):
    seams = _seams(hunter=FakeHunter(emails_override=[]))
    results = _drive(settings, **seams)
    last = results[-1]
    assert (last["stage"], last["status"], last["stop_reason"]) == ("poc", "stopped", "no_contact")
    assert last["state"]["stop_reason"] == "no_contact"
    assert "poc" not in last["state"]


def test_exception_is_failed_and_redacted(settings):
    secret = settings.gemini_api_key.get_secret_value()
    llm = FakeLLM(raise_on={"extract": RuntimeError(f"boom {secret}")})
    results = _drive(settings, **_seams(llm=llm))
    last = results[-1]
    assert (last["stage"], last["status"]) == ("extract", "failed")
    assert secret not in json.dumps(last)
    assert "***" in last["detail"]


def test_missing_prior_stage_and_unknown_stage_fail_cleanly(settings):
    r = run_stage("draft", {"domain": "example.com"}, settings=settings, **_seams())
    assert r["status"] == "failed" and "missing prior stage" in r["detail"]
    assert run_stage("nope", {"domain": "example.com"}, settings=settings)["status"] == "failed"
    assert run_stage("scrape", {}, settings=settings)["status"] == "failed"


def test_send_uses_owner_recipient_and_idempotency_key(settings):
    sender = FakeSender()
    results = _drive(settings, send=True, **_seams(sender=sender))
    assert results[-1]["status"] == "ok" and results[-1]["result"]["id"] == "fake-msg-123"
    payload, options = sender.calls[0]
    assert payload["to"] == [settings.owner_email]
    assert options["idempotency_key"].startswith("outreach-example.com-")


def test_dirs_move_under_data_dir_on_vercel(settings, monkeypatch, tmp_path):
    monkeypatch.delenv("OUTREACH_DATA_DIR", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert default_data_dir() is None
    monkeypatch.setenv("VERCEL", "1")
    assert default_data_dir() is not None and "outreach" in str(default_data_dir())
    monkeypatch.setenv("OUTREACH_DATA_DIR", str(tmp_path / "d"))
    assert default_data_dir() == Path(tmp_path / "d")
