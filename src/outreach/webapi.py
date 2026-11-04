"""Stateless, JSON-in / JSON-out wrapper over the pipeline stages, one stage per call.

A web client (the Vercel app) drives the pipeline with `run_stage(stage, state, settings=...)`:
`state` starts as `{"domain": "<d>"}` and accumulates every stage's serialised output, so each
HTTP call carries everything the next stage needs and nothing lives in the process.

The signature is a contract with the web app. Extend it only with optional keyword arguments.

All cache and output directories live under a base directory. On Vercel (env `VERCEL`) or when
`OUTREACH_DATA_DIR` is set, that is a temp directory, because the filesystem is read-only
except for `/tmp`. The `llm`, `fetcher`, `hunter` and `sender` keywords are the offline seams
used by tests; by default the real, guarded clients are built.
"""

from __future__ import annotations

import io
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from outreach import stages as stages_mod
from outreach.audit import RunStore
from outreach.cache import normalize_domain
from outreach.config import Settings, redact
from outreach.stages import STAGE_FUNCS, STAGE_MODELS, StopStage

STAGE_ORDER = ("scrape", "extract", "qualify", "poc", "draft", "send")
DATA_DIR_ENV = "OUTREACH_DATA_DIR"


def default_data_dir() -> Path | None:
    """The base for caches and outputs when the filesystem is not the repo: `OUTREACH_DATA_DIR`
    if set, else the system temp dir when running on Vercel, else None (keep the settings)."""
    explicit = os.environ.get(DATA_DIR_ENV)
    if explicit:
        return Path(explicit)
    if os.environ.get("VERCEL"):
        return Path(tempfile.gettempdir()) / "outreach"
    return None


def _scoped_settings(settings: Settings, data_dir: Path | None) -> Settings:
    base = Path(data_dir) if data_dir is not None else default_data_dir()
    if base is None:
        return settings
    return settings.model_copy(update={"cache_dir": base / ".cache", "out_dir": base / "out"})


def _display(stage: str, out: BaseModel) -> dict:
    """The JSON-safe stage output the UI shows. Scrape drops page bodies (they stay in state)."""
    data = out.model_dump(mode="json")
    if stage == "scrape":
        data["pages"] = [
            {k: p.get(k) for k in ("url", "status", "kind", "chars", "reason", "error", "from_cache")}
            for p in data.get("pages", [])
        ]
    return data


def _result(stage, status, state, *, detail="", stop_reason=None, result=None) -> dict:
    return {
        "stage": stage,
        "status": status,
        "stop_reason": stop_reason,
        "detail": detail,
        "result": result,
        "state": state,
    }


def _build_context(
    settings: Settings,
    *,
    send: bool,
    live_hunter: bool,
    llm: Any,
    fetcher: Any,
    hunter: Any,
    sender: Callable | None,
    out: io.StringIO,
):
    from outreach.cli import build_context
    from outreach.hunter import FixtureHunter
    from outreach.skeleton import Context

    base = build_context(settings, hunter_fixture=not live_hunter, dry_run=not send, out=out)
    return Context(
        settings=settings,
        llm=llm if llm is not None else base.llm,
        hunter=hunter if hunter is not None else (base.hunter if live_hunter else FixtureHunter()),
        fetcher=fetcher if fetcher is not None else base.fetcher,
        store=RunStore(settings.out_dir),
        dry_run=not send,
        sender=sender,
        out=out,
    )


def run_stage(
    stage: str,
    state: dict,
    *,
    settings: Settings,
    send: bool = False,
    live_hunter: bool = False,
    data_dir: Path | None = None,
    llm: Any = None,
    fetcher: Any = None,
    hunter: Any = None,
    sender: Callable | None = None,
    override_insufficient: bool = False,
) -> dict:
    """Run one stage. Never raises: every outcome is `ok`, `stopped` (an expected, logged stop
    such as disqualified or no_contact) or `failed` (an exception, message redacted)."""
    state = dict(state or {})
    if stage not in STAGE_FUNCS:
        return _result(stage, "failed", state, detail=f"unknown stage {stage!r}; use one of {STAGE_ORDER}")
    try:
        domain = normalize_domain(str(state.get("domain") or ""))
    except ValueError:
        return _result(stage, "failed", state, detail="state.domain is missing or empty")
    state["domain"] = domain

    settings = _scoped_settings(settings, data_dir)
    prev: dict = {}
    for earlier in STAGE_ORDER[: STAGE_ORDER.index(stage)]:
        if earlier not in state:
            return _result(stage, "failed", state, detail=f"missing prior stage output: {earlier}")
        try:
            prev[earlier] = STAGE_MODELS[earlier].model_validate(state[earlier])
        except Exception as exc:  # a state the client mangled
            return _result(stage, "failed", state, detail=f"state[{earlier!r}] is invalid: {type(exc).__name__}")

    out = io.StringIO()
    try:
        ctx = _build_context(
            settings,
            send=send,
            live_hunter=live_hunter,
            llm=llm,
            fetcher=fetcher,
            hunter=hunter,
            sender=sender,
            out=out,
        )
        output = STAGE_FUNCS[stage](ctx, domain, prev)
    except StopStage as stop:
        if (
            stage == "qualify"
            and override_insufficient is True
            and stop.reason == "insufficient_data"
            and stop.output is not None
            and getattr(stop.output, "verdict", None) == "insufficient_data"
        ):
            return _manual_override(stage, state, stop.output, settings)
        result = _display(stage, stop.output) if stop.output is not None else None
        new_state = {**state, "stopped_at": stage, "stop_reason": stop.reason}
        if stop.output is not None:
            new_state[f"{stage}_result"] = stop.output.model_dump(mode="json")
        return _result(
            stage,
            "stopped",
            new_state,
            detail=redact(stop.detail, settings),
            stop_reason=stop.reason,
            result=result,
        )
    except Exception as exc:
        return _result(
            stage, "failed", state, detail=redact(f"{type(exc).__name__}: {exc}", settings)
        )

    new_state = {k: v for k, v in state.items() if k not in ("stopped_at", "stop_reason")}
    new_state[stage] = output.model_dump(mode="json")
    detail = "dry-run: Resend not called" if stage == "send" and not send else ""
    if stage == "send" and out.getvalue():
        new_state["send_log"] = redact(out.getvalue(), settings)
    return _result(stage, "ok", new_state, detail=detail, result=_display(stage, output))


def _manual_override(stage: str, state: dict, q, settings: Settings) -> dict:
    """Proceed past the gray band on explicit user request. Only `insufficient_data` reaches here:
    a `disqualified` verdict (reject threshold or failed hard gate) never does. The Qualification
    keeps its true verdict and full breakdown; the override is recorded beside it."""
    note = (
        f"manual override: score {q.score.score_min}..{q.score.score_max} in the unknown band; "
        "continuing (qualified by manual override, not by the rubric)"
    )
    new_state = {k: v for k, v in state.items() if k not in ("stopped_at", "stop_reason")}
    new_state[stage] = q.model_dump(mode="json")
    new_state["override"] = "insufficient_data"
    result = _display(stage, q)
    result["override"] = "insufficient_data"
    result["override_note"] = note
    return _result(stage, "ok", new_state, detail=redact(note, settings), result=result)


__all__ = ["run_stage", "STAGE_ORDER", "default_data_dir", "stages_mod"]
