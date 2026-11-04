"""Offline fake pipeline with the same signature as outreach.webapi.run_stage.

Used by `scripts/serve_web.py --fake` so the UI can be tried with no keys and no network.
A domain starting with `stop.` stops at qualify (disqualified), `gray.` stops as insufficient_data unless overridden; one starting with `fail.` fails at scrape.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

DELAY = 0.4

FAKE_SETTINGS = SimpleNamespace(
    owner_email="owner@example.com",
    resend_from="onboarding@resend.dev",
    secret_values=lambda: [],
)


def fake_settings():
    return FAKE_SETTINGS


def fake_run_stage(stage, state, *, settings, send=False, live_hunter=False, override_insufficient=False):
    domain = state.get("domain", "example.com")
    time.sleep(DELAY)
    state = {**state, "done": [*state.get("done", []), stage]}

    def out(status="ok", result=None, detail="", reason=None):
        return {"stage": stage, "status": status, "stop_reason": reason, "detail": detail,
                "result": result, "state": state}

    if stage == "scrape":
        if domain.startswith("fail."):
            return out("failed", None, "could not fetch any page", "fetch_failed")
        pages = [{"url": f"https://{domain}/{k}", "status": "ok", "kind": k, "chars": 3000, "reason": None,
                  "error": None, "from_cache": False} for k in ("home", "about", "security", "careers")]
        return out(result={"pages": pages, "usable": 4, "kinds_found": ["home", "about", "security", "careers"]},
                   detail="4 usable pages")
    if stage == "extract":
        ev = lambda v, q, k: {"value": v, "quote": q, "source_url": f"https://{domain}/{k}"}  # noqa: E731
        profile = {"name": ev("Acme Ledger", "Acme Ledger is a B2B SaaS platform", "home"),
                   "offering": ev("AP automation", "automates accounts payable", "home"),
                   "is_b2b": ev(True, "for finance teams", "home"), "stage": None, "headcount": None,
                   "compliance_mentions": [{"framework": "SOC 2 Type II", "status": "in_progress", "as_of": None,
                                            "quote": "working toward SOC 2 Type II", "source_url": f"https://{domain}/security"}],
                   "hiring_signals": [{"role": "Security Engineer", "quote": "hiring a Security Engineer", "source_url": f"https://{domain}/careers"}],
                   "enterprise_customers": []}
        return out(result={"profile": profile, "evidence_total": 6, "evidence_kept": 5, "evidence_dropped": [],
                           "injection_suspected_pages": []}, detail="5 evidenced facts kept")
    if stage == "qualify":
        if domain.startswith("stop."):
            return out("stopped", {"verdict": "disqualified", "reason": "fails the B2B gate"},
                       "disqualified", "disqualified")
        gray = domain.startswith("gray.")
        q = {"verdict": "insufficient_data" if gray else "qualified", "reason": "SOC 2 in progress and hiring a security engineer",
             "score": {"score_min": 62, "score_max": 62, "signals": [
                 {"id": "soc2_in_progress", "label": "SOC 2 in progress", "weight": 30, "status": "known",
                  "points_min": 30, "points_max": 30, "basis": "States it is working toward SOC 2 Type II",
                  "evidence": [{"quote": "working toward SOC 2 Type II", "source_url": f"https://{domain}/security"}]},
                 {"id": "hiring_security", "label": "Hiring security", "weight": 32, "status": "known",
                  "points_min": 32, "points_max": 32, "basis": "Open Security Engineer role",
                  "evidence": [{"quote": "hiring a Security Engineer", "source_url": f"https://{domain}/careers"}]}],
                 "gates": [{"id": "G1_b2b", "label": "Sells to businesses", "status": "pass", "basis": "B2B", "evidence": []}],
                 "penalties": []},
             "thresholds": {"qualify_min": 60, "reject_max": 45}, "rubric_version": "icp.1", "rubric_sha256": "fake",
             "research": {"stop_reason": "resolved", "fetches": 1, "steps": [
                 {"iteration": 1, "tool": "fetch_page", "url": f"https://{domain}/customers",
                  "reason": "customers page may name enterprise logos", "outcome": "fetched",
                  "score_min": 62, "score_max": 62}]}}
        if gray and override_insufficient is True:
            state = {**state, "override": "insufficient_data"}
            q["override"] = "insufficient_data"
            q["override_note"] = "manual override: score 45..60 in the unknown band; continuing"
            return out(result=q, detail=q["override_note"])
        if gray:
            q["score"]["score_min"], q["score"]["score_max"] = 45, 60
            return out("stopped", q, "score 45..60 is in the unknown band", "insufficient_data")
        return out(result=q, detail="qualified (score 62)")
    if stage == "poc":
        c = {"first_name": "Jane", "last_name": "Doe", "position": "CTO", "email": f"jane@{domain}",
             "confidence": 94, "source": "live" if live_hunter else "cache"}
        cands = [{**c, "category": "engineering", "score": 9.5, "notes": ["CTO fits a mid-size band"], "eligible": True},
                 {"first_name": "Sam", "last_name": "Lee", "position": "Head of Ops", "email": f"sam@{domain}",
                  "category": "operations", "score": 6.0, "notes": ["not security-owning"], "eligible": True}]
        return out(result={"contact": c, "band": "mid", "band_basis": "about 80 people", "reason": "CTO owns security at this size",
                           "top_candidates": cands, "candidates_seen": 7, "risks": []}, detail="found a CTO")
    if stage == "draft":
        core = ("Hi Jane, I saw Acme Ledger is working toward SOC 2 Type II and hiring a Security Engineer, "
                "which usually means enterprise customers are asking for audit evidence before you have a "
                "dedicated compliance owner. Sprinto automates compliance for SOC 2, ISO 27001 and GDPR with "
                "continuous monitoring, so your engineers are not collecting screenshots by hand. Worth a short "
                "chat this month about how teams shorten the path to the report?")
        ev = [{"id": "E1", "kind": "compliance", "fact": "SOC 2 Type II in progress", "quote": "working toward SOC 2 Type II",
               "source_url": f"https://{domain}/security"},
              {"id": "E2", "kind": "hiring", "fact": "Security Engineer", "quote": "hiring a Security Engineer",
               "source_url": f"https://{domain}/careers"}]
        return out(result={"draft": {"subject": f"SOC 2 at {domain}", "body": core + "\n\nUnsubscribe: reply STOP."},
                           "greets_by_first_name": True, "core_body": core,
                           "claims_used": [{"claim": "working toward SOC 2 Type II", "evidence_id": "E1"},
                                           {"claim": "hiring a Security Engineer", "evidence_id": "E2"},
                                           {"claim": "automates compliance", "evidence_id": "S1"}],
                           "pain_points": [{"pain": "Audit evidence requested by enterprise buyers", "role_link": "A CTO owns the security roadmap", "evidence_id": "E1"},
                                           {"pain": "No dedicated compliance owner", "role_link": "Engineers absorb the work", "evidence_id": "E2"}],
                           "pain_points_source": "gemini", "evidence_pack": ev,
                           "hook_map": [{"claim": h["fact"], "evidence_id": h["id"], "quote": h["quote"], "source_url": h["source_url"]} for h in ev],
                           "validation": {"ok": True, "failures": [], "attempts": 1}}, detail="draft passed checks")
    payload = {"from": settings.resend_from, "to": [settings.owner_email],
               "subject": "[TEST] SOC 2 at " + domain, "text": "Hi Jane, ..."}
    return out(result={"mode": "sent" if send else "dry_run", "payload": payload,
                       "id": "fake-id" if send else None},
               detail="sent to owner" if send else "dry run, nothing sent")
