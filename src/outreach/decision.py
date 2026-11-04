"""The readable decision log (LOG-02): `decision.md` rendered from a run record alone.

Pure function of `run.json`: why the company qualified (score breakdown), why this person
(ranked candidates and the reason), why this email (pain points, hook-to-evidence map, validator
verdict) and what happened at send. No network, no cache, no clock.
"""

from __future__ import annotations

import re

from outreach.models import RunRecord
from outreach.qualify import qualification_from_record, render_breakdown

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _stage(rec: RunRecord, name: str):
    return next((s for s in rec.stages if s.name == name), None)


def _out(rec: RunRecord, name: str) -> dict | None:
    s = _stage(rec, name)
    return s.output if s is not None and s.status == "ok" else None


def _cell(text: object) -> str:
    return str(text if text is not None else "-").replace("|", "/").replace("\n", " ")


def _company_section(rec: RunRecord) -> list[str]:
    lines = ["## 1. Why this company"]
    q = qualification_from_record(rec)
    if q is None:
        stopped = _stage(rec, "scrape") if _stage(rec, "qualify") is None else None
        why = (stopped.output or {}).get("detail") if stopped and stopped.status == "stopped" else None
        failed = next((s for s in rec.stages if s.status == "failed"), None)
        lines.append(why or (f"Run failed at `{failed.name}`: {failed.error}" if failed else "Not reached."))
        return lines + [""]
    lines.append(f"**Verdict: {q.verdict}** - {q.reason}")
    lines.append(f"Score {q.score.score_min} to {q.score.score_max} (expected {q.score.score_expected}) against threshold "
                 f"{q.thresholds}; rubric {q.rubric_version} (sha256 {q.rubric_sha256[:12]}).")
    if q.decided_with_unknowns:
        lines.append(f"Decided with unknown signals: {', '.join(q.decided_with_unknowns)}.")
    lines += ["", "```", _ANSI.sub("", render_breakdown(q)), "```", ""]
    return lines


def _person_section(rec: RunRecord) -> list[str]:
    lines = ["## 2. Why this person"]
    poc = _out(rec, "poc")
    stopped = _stage(rec, "poc")
    if poc is None:
        if stopped is not None and stopped.status == "stopped":
            return lines + [f"No contact: {(stopped.output or {}).get('detail', '')}", ""]
        return lines + ["Not reached (the company did not qualify, so Hunter was never called).", ""]
    c = poc["contact"]
    lines.append(f"**{c['first_name']} {c.get('last_name') or ''}, {c['position']}** <{c['email']}> "
                 f"(Hunter confidence {c.get('confidence')}, source {c['source']}).")
    lines.append(f"Size band: {poc['band']} ({poc['band_basis']}). {poc['reason']}.")
    if poc.get("risks"):
        lines.append("Risks: " + "; ".join(poc["risks"]))
    lines += ["", f"Top candidates ({poc['candidates_seen']} seen):", "",
              "| # | Name | Title | Category | Score | Notes |", "|---|---|---|---|---|---|"]
    for i, cand in enumerate(poc["top_candidates"], start=1):
        name = f"{cand.get('first_name') or ''} {cand.get('last_name') or ''}".strip()
        lines.append(f"| {i} | {_cell(name)} | {_cell(cand.get('position'))} | {_cell(cand.get('category'))} "
                     f"| {cand.get('score')} | {_cell('; '.join(cand.get('notes', [])))} |")
    return lines + [""]


def _email_section(rec: RunRecord) -> list[str]:
    lines = ["## 3. Why this email"]
    draft = _out(rec, "draft")
    stopped = _stage(rec, "draft")
    result = None
    if draft is None and stopped is not None and stopped.status == "stopped":
        result = (stopped.output or {}).get("result")
        lines.append(f"**Rejected draft**: {(stopped.output or {}).get('detail', '')}")
        draft = result
    if draft is None:
        return lines + ["Not reached.", ""]
    lines.append("Pain points (" + (draft.get("pain_points_source") or "n/a") + "):")
    for p in draft.get("pain_points", []):
        lines.append(f"- {p['pain']} (role: {p['role_link']}; evidence {p['evidence_id']})")
    lines += ["", f"Subject: `{draft['draft']['subject']}`", "", "```", draft["draft"]["body"], "```", "",
              "Hook-to-evidence map:", "", "| Claim in the email | Evidence | Quote | Source |", "|---|---|---|---|"]
    for h in draft.get("hook_map", []):
        lines.append(f"| {_cell(h['claim'])} | {h['evidence_id']} | \"{_cell(h['quote'])}\" | {_cell(h['source_url'])} |")
    sprinto = [c for c in draft.get("claims_used", []) if str(c["evidence_id"]).startswith("S")]
    for c in sprinto:
        lines.append(f"| {_cell(c['claim'])} | {c['evidence_id']} (Sprinto whitelist) | - | - |")
    v = draft.get("validation") or {}
    lines += ["", f"Validator: {'passed' if v.get('ok') else 'FAILED'} after {v.get('attempts', '?')} attempt(s)."]
    for n, failed in enumerate(v.get("attempt_failures", []), start=1):
        if failed:
            lines.append(f"- attempt {n} failures: " + "; ".join(failed))
    return lines + [""]


def _send_section(rec: RunRecord) -> list[str]:
    send = _out(rec, "send")
    if send is None:
        return []
    p = send["payload"]
    msg = "dry-run, Resend not called" if send["mode"] == "dry_run" else f"sent, message id {send.get('id')}"
    return ["## 4. Send", f"{msg}. From {p['from']} to {', '.join(p['to'])} (forced to the owner address).",
            f"Subject: `{p['subject']}`", ""]


def render_decision(rec: RunRecord) -> str:
    head = [f"# Decision log: {rec.domain}", "",
            f"Status: **{rec.status}**" + (f" ({rec.stop_reason})" if rec.stop_reason else ""),
            f"Started {rec.started_at}; rubric {rec.rubric.get('version', '?')}; models {rec.models}.", ""]
    return "\n".join(head + _company_section(rec) + _person_section(rec) + _email_section(rec) + _send_section(rec)).rstrip() + "\n"
