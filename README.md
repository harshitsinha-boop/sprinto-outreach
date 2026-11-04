# Sprinto cold outreach pipeline

Give it a list of company domains. With no human decision in between it decides whether each
company fits Sprinto (compliance automation for SOC 2, ISO 27001 and GDPR), finds one named
decision-maker, writes a short evidence-cited email, and sends it to **your own inbox** for
review. Every decision (why this company, why this person, why this email) is written to a
readable log.

Pipeline, per domain: `scrape` -> `extract` -> `qualify` -> `poc` -> `draft` -> `send`.

- **scrape**: homepage plus about, careers, security/trust, pricing and customers pages
  (robots.txt respected, size and time caps, same-site only, blocked or thin pages dropped).
- **extract**: Gemini turns page text into a `CompanyProfile`. Every fact carries a quote that
  must be a verbatim substring of the fetched page, or it is dropped.
- **qualify**: a hashed rubric (`config/icp.toml`) is scored in Python, never by the LLM, as a
  min and max score (unknowns at 0 and at full weight). A gray-band company gets a bounded
  research loop (at most 3 same-domain fetches, each with a logged reason).
- **poc**: one Hunter Domain Search per qualified company, cached forever (empty results too).
  The contact is chosen by deterministic title ranking for the company's size band. Name and
  title come verbatim from Hunter. Nobody suitable means `no_contact` and no email.
- **draft**: two pain points (each tied to the person's role and an evidence id), then a 50-90
  word plain-text email. A deterministic validator rejects drafts with the wrong name, a URL,
  a banned phrase, more than one question, a number or proper noun outside the evidence, or a
  Sprinto claim outside the two whitelisted ones. One regeneration, then `rejected_draft`.
- **send**: Resend, `to` forced to `OWNER_EMAIL` inside the send function, subject prefixed
  `[TEST -> Name <email>]`, an idempotency key, and a returned message id is required.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in GEMINI_API_KEY, HUNTER_API_KEY, RESEND_API_KEY, OWNER_EMAIL

.venv/bin/python -m outreach smoke                 # prove the live integrations once
.venv/bin/python -m outreach run domains.txt       # dry run: prints the exact payloads
.venv/bin/python -m outreach run domains.txt --live-hunter   # spend Hunter credits (cached)
.venv/bin/python -m outreach run domains.txt --live-hunter --send   # really send, to OWNER_EMAIL only
.venv/bin/python -m outreach run domains.txt --replay        # caches only: no network, no send
.venv/bin/python -m outreach show example.com      # the readable decision log for one domain
```

`domains.txt` is one domain per line (`#` comments allowed, at most 25 per run). Defaults are
safe: **dry run, and the offline Hunter fixture**. `--send` and `--live-hunter` are explicit.

Outputs per domain, under `out/<domain>/`: `run.json` (written after every stage, so a crash
leaves a partial trail) and `decision.md`. A batch summary is at `out/_batch/summary.json`.
Outcomes: `qualified`, `disqualified`, `insufficient_data`, `no_contact`, `rejected_draft`,
`sent`, `failed`. Exit codes: 0 done, 2 input or config error, 3 aborted by a systemic failure
(bad API key, exhausted quota).

### Offline demo

```bash
.venv/bin/python scripts/demo.py     # six fixture domains, no network, no keys
```

Saves the summary table, every decision log and the dry-run payloads in `docs/demo/`: two fits,
a B2C non-fit, an unscrapeable site, an unreachable site and a qualified company with no
Hunter contact.

### Tests

```bash
.venv/bin/python -m pytest -q                 # fully offline, fakes and mocked HTTP only
.venv/bin/python scripts/check_secrets.py     # no key-shaped strings in the repo
```

## Web app on Vercel

`web/` and `api/` hold a password-gated runner that drives the same pipeline one stage per HTTP
call through `outreach.webapi.run_stage(stage, state, settings=...)`: JSON state in, JSON state
out, nothing kept in the process. On Vercel the only writable path is `/tmp`, so caches and
outputs go under a temp directory (set `OUTREACH_DATA_DIR` to override). The Hunter monthly
budget is also counted per warm instance. Secrets live in Vercel environment variables only.

## Known limits

- **Hunter free tier is 25 searches a month.** Results are cached, the local counter
  (`HUNTER_MONTHLY_BUDGET`) refuses calls beyond it, and a cold Vercel instance forgets its
  `/tmp` cache, so repeated web runs can re-spend credits. Check `/v2/account` before raising it.
- **The recipient is always you.** `onboarding@resend.dev` only delivers to the Resend account
  owner. Real-recipient sending needs a verified domain (out of scope).
- **JS-heavy or bot-protected sites** return thin pages and end as `insufficient_data`; there
  is no headless browser.
- **No headcount?** The mid size band is used and the log says so.
- **Title ranking and the rubric weights are hypotheses** (see `.planning/research/`), not
  Sprinto buyer data. Tune weights in `config/icp.toml`, not the thresholds.
- **Hunter coverage is partial.** A company with no suitable named person is skipped, on
  purpose: a wrong name is worse than no email.
- The validator is conservative. It can reject a good draft (for example a proper noun that
  is not in the evidence); that shows as `rejected_draft` with the reasons in `decision.md`.

## Cold-email compliance notes

- Every email ends with a footer: sender identity, a **postal address placeholder** and an
  opt-out line. The identity and address are placeholders (`[Sender name]`, `[Sender postal
  address]` in `src/outreach/draft.py`); fill them in before any real campaign. CAN-SPAM
  needs a valid physical address and a working opt-out; honour opt-outs within 10 business days.
- GDPR, UK PECR and CASL are stricter for EU, UK and Canadian recipients: B2B cold email there
  needs a legitimate-interest basis or consent. Do not run EU or Canadian lists without review.
- Hunter returns professional addresses only. Skip anyone who asks not to be contacted
  (Hunter returns 451 for those; it is surfaced, never retried).
- No tracking pixels, no links, no attachments, no fake "re:" subjects, no fabricated claims.
  Sprinto claims are limited to a whitelist: "Sprinto automates compliance for SOC 2, ISO 27001
  and GDPR" and "continuous monitoring and audit-ready evidence collection".
- Keys live only in `.env` or the host's environment, are redacted from every log and error,
  and `scripts/check_secrets.py` guards the repo.
