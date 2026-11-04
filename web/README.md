# Web runner (Phase 7)

Password-gated page plus Vercel Python functions. The browser drives the pipeline one stage per
request (`scrape, extract, qualify, poc, draft, send`) so every request stays under the 60 s limit.

## Environment variables (set on Vercel, names only)

Required: `APP_PASSWORD`, `GEMINI_API_KEY`, `HUNTER_API_KEY`, `RESEND_API_KEY`, `OWNER_EMAIL`.
Optional: `WEB_HUNTER_BUDGET` (live Hunter searches per instance, default 10), `GEMINI_MODEL_SMART`,
`GEMINI_MODEL_FAST`, `RESEND_FROM`.

If `APP_PASSWORD` is unset, every API call is refused with a "not configured" message.

## Behaviour and limits

- Every `/api/*` request needs the `x-app-password` header (constant-time compare). The static HTML
  shell is public but holds no secrets and does nothing without the password.
- Domain input is a bare public hostname only (no scheme, path, port, IPs, localhost, private TLDs).
- Limits: 5 runs per browser session (client), 10 requests/minute and 30 run starts/hour per IP and
  `WEB_HUNTER_BUDGET` live Hunter searches, all in memory per serverless instance (best effort).
- Mail goes only to `OWNER_EMAIL`. The send stage ignores any recipient in the request and sends
  only when the request has `"confirm_send": true`; otherwise it returns a dry-run preview.
- Cache and output directories are under `/tmp/outreach` (`OUTREACH_DATA_DIR`).

## Local trial (no keys)

    APP_PASSWORD=dev .venv/bin/python scripts/serve_web.py --fake   # http://127.0.0.1:8000/

Omit `--fake` to run the real pipeline with keys from your environment. Fake domains: `stop.<x>`
stops at qualify, `fail.<x>` fails at scrape.

## Layout

`web/index.html` UI, `api/run.py` and `api/health.py` Vercel functions, `api/_logic.py` shared
request logic (tests import it), `api/_fake.py` offline fake pipeline, `vercel.json`, `requirements.txt`.
