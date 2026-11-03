"""Batch runner: a file of domains through `run_one`, one outcome per domain.

Never imports an SDK. Every domain goes through the unchanged six-stage `run_one`;
this module only loads the domains, maps each finished record to a closed outcome and
renders the summary table.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from outreach.audit import now_iso
from outreach.cache import atomic_write_json, normalize_domain
from outreach.config import redact
from outreach.models import OUTCOMES, BatchRow, BatchSummary, RunRecord
from outreach.skeleton import Context, run_one

STOP_OUTCOMES = frozenset({"insufficient_data", "no_contact", "disqualified", "rejected_draft"})
DETAIL_MAX = 200
TABLE_DETAIL_MAX = 80


def load_domains(path: Path | str) -> list[str | BatchRow]:
    """Domains in file order. Blank lines and `#` comments are skipped; duplicates keep
    their first occurrence."""
    entries: list[str | BatchRow] = []
    seen: set[str] = set()
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            domain = normalize_domain(line)
        except ValueError:
            continue
        if domain in seen:
            continue
        seen.add(domain)
        entries.append(domain)
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
            summary.rows.append(entry)  # a rejected line: never runs, keeps its position
            row = entry
        else:
            domain = entry
            try:
                rec = run_one(domain, ctx)
                outcome, detail = outcome_for(rec)
            except Exception as exc:  # the per-domain isolation boundary
                rec = ctx.store.load(domain)
                if rec is not None:
                    outcome, detail = outcome_for(rec)
                else:
                    outcome = "failed"
                    detail = redact(f"{type(exc).__name__}: {exc}", ctx.settings)
            row = BatchRow(
                domain=domain,
                outcome=outcome,
                detail=detail[:DETAIL_MAX],
                run_record=str(ctx.store.path_for(domain)),
            )
            summary.rows.append(row)
        if progress is not None:
            progress.write(f"[{i}/{total}] {row.domain} -> {row.outcome}\n")
            progress.flush()
    _finish(summary)
    return summary


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
