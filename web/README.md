# Web runner (Phase 7)

Free-to-use page plus Vercel Python functions. The browser drives the pipeline one stage per
request (`scrape, extract, qualify, poc, draft, send`) so every request stays under the 60 s limit.

## Environment variables (set on Vercel, names only)

Required: `GEMINI_API_KEY`, `HUNTER_API_KEY`, `RESEND_API_KEY`, `OWNER_EMAIL`. Until these are all set the
API answers 503 "not configured" and the page shows a "not configured yet" notice.
Optional: `APP_PASSWORD` (see below), `WEB_HUNTER_BUDGET` (live Hunter searches per instance, default 10),
`WEB_MAX_SENDS_PER_HOUR` (live sends per instance per hour, default 5), `GEMINI_MODEL_SMART`,
`GEMINI_MODEL_FAST`, `RESEND_FROM`.

## Behaviour and limits

- Public by default: with `APP_PASSWORD` unset anyone with the link can use it. If `APP_PASSWORD` is set,
  every `/api/run` call needs the `x-app-password` header (constant-time compare) and the page shows a
  password box. `/api/health` is always public and returns only `{ok, configured, auth_required}`.
- Domain input is a bare public hostname only (no scheme, path, port, IPs, localhost, private TLDs).
- Abuse limits, all in memory per serverless instance (best effort, old entries pruned): 3 "Run pipeline" presses (each up to 5 domains) per
  browser session (client), 40 requests/minute (a batch of 5 domains needs about 30) and 20 run starts/hour per IP, `WEB_HUNTER_BUDGET` live
  Hunter searches, and `WEB_MAX_SENDS_PER_HOUR` live sends (beyond that the send stage returns the
  dry-run preview with a clear message).
- Mail goes only to `OWNER_EMAIL`. The send stage ignores any recipient in the request and sends
  only when the request has `"confirm_send": true`; otherwise it returns a dry-run preview.
- Cache and output directories are under `/tmp/outreach` (`OUTREACH_DATA_DIR`).

## Local trial (no keys)

    .venv/bin/python scripts/serve_web.py --fake   # http://127.0.0.1:8000/

Omit `--fake` to run the real pipeline with keys from your environment. Fake domains: `stop.<x>`
stops at qualify, `fail.<x>` fails at scrape.

## Layout

`web/index.html`, `web/app.css`, `web/app.js` (vanilla, no build; tokens from `design-system/sprinto-outreach/MASTER.md`),
`api/run.py`, `api/health.py`, `api/rubric.py` Vercel functions (`GET /api/rubric` is public and returns the
parsed `config/icp.toml` plus its sha256), `api/_logic.py` shared request logic (tests import it),
`api/_fake.py` offline fake pipeline, `vercel.json`, `requirements.txt`.
