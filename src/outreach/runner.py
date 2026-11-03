"""Batch runner: a file of domains through `run_one`, one outcome per domain.

Never imports an SDK. Every domain goes through the unchanged six-stage `run_one`;
this module only loads the domains, maps each finished record to a closed outcome and
renders the summary table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TextIO

from outreach.audit import now_iso
from outreach.cache import atomic_write_json, normalize_domain
from outreach.config import redact
from outreach.hunter import HunterAuthError, HunterQuotaError
from outreach.llm import LLMAuthError, LLMQuotaError
from outreach.models import OUTCOMES, BatchRow, BatchSummary, RunRecord
from outreach.send import SendError
from outreach.skeleton import Context, run_one

# Each of these means every later domain would fail the same way: a bad key, an exhausted
# daily or monthly quota, or a send path that is misconfigured for every domain. Carrying on
# would only burn calls, so the batch aborts at once.
SYSTEMIC_ERRORS = (LLMAuthError, LLMQuotaError, HunterAuthError, HunterQuotaError, SendError)

# A cost bound for a batch that has no qualification gate yet (every domain costs up to two
# Gemini calls).
MAX_BATCH_DOMAINS = 25
NOT_RUN_DETAIL = "not run (batch aborted)"
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class BatchInputError(Exception):
    """The domains file cannot be run as given (too many domains)."""


def _is_hostname(host: str) -> bool:
    """A public-looking DNS name: at least two valid labels, last label not all digits.
    Rejects IPv4 literals, `localhost`, bracketed IPv6 and anything containing spaces."""
    if len(host) > 253:
        return False
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
        return False
    return not labels[-1].isdigit()

STOP_OUTCOMES = frozenset({"insufficient_data", "no_contact", "disqualified", "rejected_draft"})
DETAIL_MAX = 200
TABLE_DETAIL_MAX = 80


def load_domains(path: Path | str) -> list[str | BatchRow]:
    """Entries in file order. A valid domain is a string; a rejected line is a failed BatchRow
    at its own position, so the summary keeps file order. Blank lines and `#` comments are
    skipped and duplicates keep their first occurrence. More than MAX_BATCH_DOMAINS domain
    strings raises BatchInputError."""
    entries: list[str | BatchRow] = []
    seen: set[str] = set()
    count = 0
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            domain = normalize_domain(line)
        except ValueError:
            domain = ""
        if not _is_hostname(domain):
            entries.append(
                BatchRow(domain=line, outcome="failed", detail=f"invalid domain on line {number}")
            )
            continue
        if domain in seen:
            continue
        seen.add(domain)
        entries.append(domain)
        count += 1
    if count > MAX_BATCH_DOMAINS:
        raise BatchInputError(
            f"{count} domains in the file; the per-run cap is {MAX_BATCH_DOMAINS}"
        )
    return entries


def _stage(rec: RunRecord, status: str):
    for sr in reversed(rec.stages):
        if sr.status == status:
            return sr
    return None


def outcome_for(rec: RunRecord) -> tuple[str, str]:
    """Map a finished RunRecord to (outcome, detail). The outcome is always in OUTCOMES."""
    if rec.status == "dry_run":
        return "qualified", "dry-run: email drafted, Resend not called"
    if rec.status == "sent":
        send = next((s for s in rec.stages if s.name == "send"), None)
        msg_id = (send.output or {}).get("id") if send else None
        return "sent", f"message id {msg_id}"
    if rec.status == "stopped":
        reason = rec.stop_reason or ""
        if reason in STOP_OUTCOMES:
            stopped = _stage(rec, "stopped")
            detail = ((stopped.output or {}).get("detail") if stopped else "") or reason
            return reason, detail
        return "failed", f"unknown stop reason {reason}"
    if rec.status == "failed":
        failed = _stage(rec, "failed")
        return "failed", f"{rec.failed_stage}: {failed.error if failed else ''}"
    return "failed", "run did not finish"


def run_batch(
    entries: list[str | BatchRow],
    ctx: Context,
    *,
    hunter_label: str = "fixture",
    progress: TextIO | None = None,
) -> BatchSummary:
    summary = BatchSummary(
        mode="dry_run" if ctx.dry_run else "send",
        hunter=hunter_label,
        started_at=now_iso(),
    )
    total = len(entries)
    for i, entry in enumerate(entries, start=1):
        if isinstance(entry, BatchRow):
            row = entry  # a rejected line: never runs, keeps its position
        else:
            domain = entry
            systemic: Exception | None = None
            try:
                outcome, detail = outcome_for(run_one(domain, ctx))
            except Exception as exc:  # the per-domain isolation boundary
                outcome, detail = _outcome_after_exception(domain, exc, ctx)
                if isinstance(exc, SYSTEMIC_ERRORS):
                    systemic = exc
            row = BatchRow(
                domain=domain,
                outcome=outcome,
                detail=detail[:DETAIL_MAX],
                run_record=str(ctx.store.path_for(domain)),
            )
            if systemic is not None:
                summary.rows.append(row)
                _progress(progress, i, total, row)
                summary.aborted = True
                summary.abort_reason = redact(
                    f"systemic failure {type(systemic).__name__} on {domain}: {systemic}",
                    ctx.settings,
                )
                _skip_remaining(summary, entries[i:], i, total, progress)
                break
        summary.rows.append(row)
        _progress(progress, i, total, row)
    _finish(summary)
    return summary


def _outcome_after_exception(domain: str, exc: Exception, ctx: Context) -> tuple[str, str]:
    rec = ctx.store.load(domain)  # run_one flushed the failed record before re-raising
    if rec is not None:
        return outcome_for(rec)
    return "failed", redact(f"{type(exc).__name__}: {exc}", ctx.settings)


def _skip_remaining(
    summary: BatchSummary,
    remaining: list[str | BatchRow],
    done: int,
    total: int,
    progress: TextIO | None,
) -> None:
    """After an abort: nothing runs; every later domain is listed as failed, in file order."""
    for offset, entry in enumerate(remaining, start=1):
        row = (
            entry
            if isinstance(entry, BatchRow)
            else BatchRow(domain=entry, outcome="failed", detail=NOT_RUN_DETAIL, run_record=None)
        )
        summary.rows.append(row)
        _progress(progress, done + offset, total, row)


def _progress(progress: TextIO | None, i: int, total: int, row: BatchRow) -> None:
    if progress is not None:
        progress.write(f"[{i}/{total}] {row.domain} -> {row.outcome}\n")
        progress.flush()


def _finish(summary: BatchSummary) -> None:
    summary.counts = {o: 0 for o in OUTCOMES}
    for row in summary.rows:
        summary.counts[row.outcome] += 1
    summary.finished_at = now_iso()


def render_summary(summary: BatchSummary) -> str:
    header = ("domain", "outcome", "detail")
    body = [(r.domain, r.outcome, r.detail[:TABLE_DETAIL_MAX]) for r in summary.rows]
    widths = [max(len(header[c]), *(len(row[c]) for row in body)) if body else len(header[c]) for c in range(3)]

    def fmt(cells: tuple[str, str, str]) -> str:
        return "  ".join(cell.ljust(widths[c]) for c, cell in enumerate(cells)).rstrip()

    lines = [f"SUMMARY mode={summary.mode} hunter={summary.hunter}", fmt(header)]
    lines.extend(fmt(row) for row in body)
    lines.append("outcomes: " + " ".join(f"{o}={summary.counts.get(o, 0)}" for o in OUTCOMES))
    if summary.aborted:
        lines.append(f"ABORTED: {summary.abort_reason}")
    return "\n".join(lines)


def write_summary(summary: BatchSummary, out_dir: Path | str) -> Path:
    """out/_batch/summary.json; the underscore directory cannot collide with a hostname."""
    path = Path(out_dir) / "_batch" / "summary.json"
    atomic_write_json(path, summary.model_dump(mode="json"))
    return path
