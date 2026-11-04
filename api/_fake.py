"""Offline fake pipeline with the same signature as outreach.webapi.run_stage.

Used by `scripts/serve_web.py --fake` so the UI can be tried with no keys and no network.
A domain starting with `stop.` stops at qualify; one starting with `fail.` fails at scrape.
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


def fake_run_stage(stage, state, *, settings, send=False, live_hunter=False):
    domain = state.get("domain", "example.com")
    time.sleep(DELAY)
    state = {**state, "done": [*state.get("done", []), stage]}

    def out(status="ok", result=None, detail="", reason=None):
        return {"stage": stage, "status": status, "stop_reason": reason, "detail": detail,
                "result": result, "state": state}

    if stage == "scrape":
        if domain.startswith("fail."):
            return out("failed", None, "could not fetch any page", "fetch_failed")
        return out(result={"usable": 4}, detail="4 usable pages")
    if stage == "extract":
        return out(result={"profile": {"name": "Acme Ledger"}}, detail="12 evidenced facts kept")
    if stage == "qualify":
        if domain.startswith("stop."):
            return out("stopped", {"verdict": "disqualified", "reason": "fails the B2B gate"},
                       "disqualified", "disqualified")
        q = {"verdict": "qualified", "reason": "SOC 2 in progress and hiring a security engineer",
             "score": {"score_min": 62, "score_max": 62, "signals": [
                 {"id": "soc2_in_progress", "label": "SOC 2 in progress", "weight": 30, "status": "known",
                  "points_min": 30, "points_max": 30, "basis": "States it is working toward SOC 2 Type II",
                  "evidence": [{"quote": "working toward SOC 2 Type II", "source_url": f"https://{domain}/security"}]},
                 {"id": "hiring_security", "label": "Hiring security", "weight": 32, "status": "known",
                  "points_min": 32, "points_max": 32, "basis": "Open Security Engineer role",
                  "evidence": [{"quote": "hiring a Security Engineer", "source_url": f"https://{domain}/careers"}]}],
                 "gates": [], "penalties": []}}
        return out(result=q, detail="qualified (score 62)")
    if stage == "poc":
        return out(result={"first_name": "Jane", "last_name": "Doe", "position": "CTO",
                           "email": f"jane@{domain}", "confidence": 94,
                           "source": "live" if live_hunter else "cache"}, detail="found a CTO")
    if stage == "draft":
        return out(result={"draft": {"subject": f"SOC 2 at {domain}",
                                     "body": "Hi Jane,\n\nSaw you are working toward SOC 2 Type II and hiring a Security Engineer. Happy to share how teams shorten that path.\n\nBest,\nA"},
                           "hook": "SOC 2 Type II in progress (acme.com/security)"}, detail="draft passed checks")
    payload = {"from": settings.resend_from, "to": [settings.owner_email],
               "subject": "[TEST] SOC 2 at " + domain, "text": "Hi Jane, ..."}
    return out(result={"mode": "sent" if send else "dry_run", "payload": payload,
                       "id": "fake-id" if send else None},
               detail="sent to owner" if send else "dry run, nothing sent")
