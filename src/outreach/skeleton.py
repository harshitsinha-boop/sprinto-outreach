"""Walking-skeleton orchestration: one domain through six stages behind injectable seams.

`run_one` never imports an SDK. The run record is flushed before stage 1 and after
EVERY stage (LOG-01), never only in a `finally` block, so a hard kill leaves a valid
partial trail.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TextIO

from pydantic import BaseModel

from outreach import stages as stages_mod
from outreach.audit import RunStore, now_iso
from outreach.cache import normalize_domain
from outreach.config import Settings, redact
from outreach.models import PageResult, RunRecord, StageRecord, ToolReply, ToolResult, ToolSpec
from outreach.qualify import LoadedRubric, load_rubric
from outreach.stages import StopStage


class ToolSessionLike(Protocol):
    def send(self, prompt: str) -> ToolReply: ...

    def respond(self, results: list[ToolResult]) -> ToolReply: ...


class LLMLike(Protocol):
    stats: object  # exposes integer `api_calls` and `cache_hits`

    def generate_structured(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        purpose: str,
        thinking_level: str | None = None,
        prompt_version: str = "1",
        max_output_tokens: int = 4096,
    ) -> BaseModel: ...

    def start_tool_session(
        self,
        *,
        model: str,
        system: str,
        tool: ToolSpec,
        purpose: str,
        thinking_level: str | None = None,
        prompt_version: str = "1",
        max_output_tokens: int = 1024,
    ) -> ToolSessionLike: ...


class HunterLike(Protocol):
    live_calls_this_process: int

    def domain_search(self, domain: str) -> dict:
        """Keys: domain, response (raw Hunter JSON), from_cache (bool), source (live|cache|fixture)."""
        ...

    def account(self) -> dict:
        """Keys: plan, reset_date, remaining."""
        ...


class FetcherLike(Protocol):
    def fetch(self, url: str, site: str | None = None) -> PageResult: ...


@dataclass
class Context:
    settings: Settings
    llm: LLMLike
    hunter: HunterLike
    fetcher: FetcherLike
    store: RunStore
    dry_run: bool = True
    sender: Callable | None = None
    out: TextIO | None = None
    rubric: LoadedRubric = field(default_factory=load_rubric)


def _refresh_counters(rec: RunRecord, ctx: Context) -> None:
    stats = getattr(ctx.llm, "stats", None)
    if stats is not None:
        rec.counters["llm_api_calls"] = int(getattr(stats, "api_calls", 0))
        rec.counters["llm_cache_hits"] = int(getattr(stats, "cache_hits", 0))
    rec.counters["hunter_live_calls"] = int(getattr(ctx.hunter, "live_calls_this_process", 0))


def run_one(domain: str, ctx: Context) -> RunRecord:
    domain = normalize_domain(domain)
    rec = RunRecord(
        domain=domain,
        status="running",
        started_at=now_iso(),
        models={"fast": ctx.settings.gemini_model_fast, "smart": ctx.settings.gemini_model_smart},
    )
    rec.rubric = {
        "version": ctx.rubric.rubric.version,
        "sha256": ctx.rubric.sha256,
        "file": ctx.rubric.path.name,
    }
    ctx.store.flush(rec)  # the trail exists before stage 1, naming the rubric it runs under

    prev: dict = {}
    for name, fn in stages_mod.STAGES:
        sr = StageRecord(name=name, status="ok", started_at=now_iso())
        try:
            out = fn(ctx, domain, prev)
            prev[name] = out
            sr.output = out.model_dump(mode="json")
        except StopStage as stop:
            sr.status = "stopped"
            sr.output = {"reason": stop.reason, "detail": redact(stop.detail, ctx.settings)}
            if stop.output is not None:
                sr.output["result"] = stop.output.model_dump(mode="json")
            sr.finished_at = now_iso()
            rec.stages.append(sr)
            rec.status = "stopped"
            rec.stop_reason = stop.reason
            rec.finished_at = sr.finished_at
            _refresh_counters(rec, ctx)
            ctx.store.flush(rec)
            return rec
        except Exception as exc:
            sr.status = "failed"
            sr.error = redact(f"{type(exc).__name__}: {exc}", ctx.settings)
            sr.finished_at = now_iso()
            rec.stages.append(sr)
            rec.status = "failed"
            rec.failed_stage = name
            rec.finished_at = sr.finished_at
            _refresh_counters(rec, ctx)
            ctx.store.flush(rec)
            raise  # Phase 2 swallows per domain; Phase 1 surfaces it
        sr.finished_at = now_iso()
        rec.stages.append(sr)
        _refresh_counters(rec, ctx)
        ctx.store.flush(rec)  # LOG-01: after EVERY stage

    rec.status = "dry_run" if ctx.dry_run else "sent"
    rec.finished_at = now_iso()
    ctx.store.flush(rec)
    return rec
