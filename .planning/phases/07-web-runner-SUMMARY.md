# Phase 7: Web runner Summary

Password-gated static page plus Vercel Python functions; the browser drives the pipeline one stage per request via `outreach.webapi.run_stage`.

## Delivered
- `web/index.html`: no-build UI (password gate in sessionStorage, 5 runs/session, per-stage progress, send confirmation checkbox + "Send the email to <owner>" button, decision log, exact email). `web/README.md` lists env var names.
- `api/run.py`, `api/health.py` (Vercel handlers), `api/_logic.py` (all request logic: hmac auth, 503 when APP_PASSWORD unset, domain validation, per-IP 10/min and 30 runs/hour, Hunter live budget WEB_HUNTER_BUDGET default 10 on poc only, confirm_send must be boolean true else dry-run, owner-only recipient, redact(), no traces), `api/_fake.py`.
- `vercel.json` (maxDuration 60, includeFiles src+config, outputDirectory web), `requirements.txt` (runtime pins from the lock), `.vercelignore`.
- `scripts/serve_web.py [--fake]` local dev server; `tests/test_web_api.py` (32 offline tests). Full suite 389 passed; check_secrets clean.

## Notes
- Static HTML is public (no secrets); every /api call needs the password. /api/health also requires it and reports env var presence as booleans.
- Rate limits and Hunter budget are per serverless instance, in memory (best effort).
- Not deployed; no keys used. Verified against the real `webapi.run_stage` for the validation path only (no live calls).
