<!-- GSD:project-start source:PROJECT.md -->

## Project

**Sprinto Cold Outreach Pipeline**

An automated pipeline that takes a list of company domains and, with no human decisions in between, decides whether each is a fit for Sprinto (compliance automation: SOC 2, ISO 27001, GDPR), finds the right decision-maker, and writes and sends a personalised cold email. Built for Mesa PGP Cohort 4, Term 2, AI Case 2 ("Cold Outreach, at Scale"), replacing a Growth Lead's manual 15-20 min/company research and writing.

**Core Value:** For a qualified company, a personalised email addressed to a real named person with a specific, evidence-based hook lands in the inbox, and every decision behind it (why this company, why this person, why this email) can be defended from a logged trail.

### Constraints

- **Tech stack**: Python; Gemini API for all LLM steps; Resend API for sending; Hunter.io Domain Search for PoC — user decisions
- **Timeline**: 1.5h build — keep scope to a thin end-to-end slice first, then deepen
- **Dependencies**: Hunter free tier is 25 searches/month — cache results and support dry-run
- **Safety**: `to:` is hardcoded to the user's own email; keys live in a local `.env`, never committed
- **Reliability**: Agent loop needs a hard iteration cap and a logged reason for each extra fetch

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ (3.13 on this machine) | Runtime | `google-genai` 2.34.0 requires >=3.11. Local `python3` is 3.13.7, so no install work. |
| google-genai | `>=2.34,<3` (latest 2.34.0) | Gemini SDK: structured output + function calling | The only official Python SDK (`from google import genai`). Old `google-generativeai` is the legacy package, do not use it. SDK README says pin `<3.0.0` because the next major removes automatic function calling from `Models.generate_content` and some Live methods. We use manual function calling, so we are unaffected, but pin anyway. HIGH |
| Gemini `gemini-3.8-flash` | model ID | Agent loop (tool calls), pain-point reasoning, email drafting | GA since 2026-09-02. Supports structured outputs, function calling, thinking (low/medium/high), 1,048,576 input tokens, 65,536 output. Free tier priced "Free" on the pricing page. Best reasoning in the Flash line. HIGH (model page) |
| Gemini `gemini-3.5-flash-lite` | model ID | Bulk JSON extraction from scraped pages (Step 2) | GA since 2026-07-21. Google positions it for "high-volume automation": extraction, routing, classification. Default thinking is `minimal`, which is what extraction wants. Cheapest ($0.30/$2.50 per 1M paid) and free-tier available. HIGH for ID/status, MEDIUM for fit (see fallback) |
| Pydantic | 2.14.2 | Schemas for company data, ICP score, Hunter contact, email draft, decision log | Gemini accepts `Model.model_json_schema()` directly as `response_json_schema`, and `Model.model_validate_json(resp.text)` is the validation gate ("unknown stays unknown" via `X \| None`). HIGH |
| httpx | 0.28.1 | Site fetching + Hunter Domain Search calls | Sync client with timeouts, redirects, connection reuse, `HTTPTransport(retries=2)`. One HTTP lib for scraper and Hunter, no Hunter SDK needed. HIGH |
| trafilatura | 2.3.1 | HTML to clean main-text/markdown | Purpose-built boilerplate stripping. Pass the HTML you already fetched with httpx: `trafilatura.extract(html, url=url, output_format="markdown", include_links=False, favor_recall=True)`. Returns `None` on failure, so always have a fallback. HIGH |
| beautifulsoup4 + lxml | 4.15.0 + 6.1.3 | Fallback text extraction, link discovery (about/careers/security/pricing/blog paths), `<title>`/meta | trafilatura is not a link discoverer (its docs say `include_links` only keeps links inside extracted content). Use BS4 for finding candidate sub-page URLs from the homepage nav and as the `get_text()` fallback when trafilatura returns `None`. HIGH |
| resend | 2.50.1 | Send email | Official SDK. `resend.api_key = ...; resend.Emails.send({...}, {"idempotency_key": ...})`. Raises `resend.exceptions.ResendError` subclasses (`ValidationError`, `RateLimitError`, `InvalidApiKeyError`); missing required arg raises plain `ValueError`. HIGH |
| typer | 0.27.3 | CLI (`run domains.txt --dry-run --limit N`) | Type-hint driven, ships rich output, `--dry-run` flag is one line. Faster to write than argparse for a multi-flag CLI; the 1.5h budget favours it. HIGH |
| python-dotenv | 1.2.4 | Load `.env` (GEMINI_API_KEY, HUNTER_API_KEY, RESEND_API_KEY, RECIPIENT_EMAIL) | Minimal. `genai.Client()` reads `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) from the environment automatically once `load_dotenv()` ran. HIGH |
| pytest | 9.2.0 | Tests | Standard. HIGH |

### Database / Caching

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| JSON files under `.cache/hunter/<domain>.json` | stdlib `json`, `pathlib` | Hunter response cache (protects the free-tier quota) | One file per domain, raw response stored verbatim, trivially inspectable, survives reruns, zero dependencies. Write the cache before any downstream step so a crash later never costs a second Hunter credit. HIGH |
| JSONL `out/decisions.jsonl` (+ per-company `out/<domain>/*.json`) | stdlib | Per-company decision log: qualification, PoC choice, email rationale, every agent-loop fetch with its reason | Append-only, one line per event, easy to `jq`/print in the demo. HIGH |
| Optional: scrape cache `.cache/pages/<sha1(url)>.html` | stdlib | Avoid re-fetching pages during iteration on prompts | Saves minutes of wall-clock while tuning prompts in the 1.5h window. HIGH |

### Infrastructure

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| venv + pip + `requirements.txt` | pip 25.x | Env management | `uv` is not installed on this machine; `python3 -m venv` works and avoids setup time. |
| `.env` + `.gitignore` | n/a | Secrets | Brief requires keys never committed. Commit a `.env.example`. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rich | 15.0.0 (pulled in by typer) | Pretty console table of decision trail for the demo | Always (comes free with typer). |
| tenacity | 9.2.1 | Retry with backoff for Hunter/Resend calls | Optional. Gemini retries are built into the SDK (`HttpOptions(retry_options=HttpRetryOptions(attempts=3))`), and httpx transport retries cover fetches. Add tenacity only for Hunter 429/5xx if time allows. |
| respx | 0.23.1 | Mock httpx calls in tests (Hunter, scraping) | When writing tests for the Hunter wrapper and scraper. Alternative: `pytest-httpx` 0.36.2. Pick one; respx is the lighter fit. |
| tldextract | 5.4.0 | Normalise domains (strip `www.`, schemes, paths) | Optional; a 5-line `urllib.parse` normaliser is enough for the demo list. Skip unless input is messy. |
| playwright | 1.64.1 | Headless browser for JS-heavy sites | Do NOT install by default (200MB+ browser download, async complexity). Only if the Jina fallback below is rejected. |
| pydantic-settings | 2.16.2 | Typed config | Skip. Needs Python >=3.11 and adds nothing over `os.environ` + dotenv for four keys. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest | Unit tests for pure logic (scoring, Hunter title ranking, email hallucination validator, URL normalisation) | Test the deterministic parts. Mock LLM with a fake `client.models.generate_content`. Hunter supports `api_key=test-api-key` which returns a fixed dummy response without spending credits. |
| `--dry-run` flag | Run everything except the Resend call (and optionally skip Hunter, using cache/fixtures) | Print the exact payload that would be sent. |

## Verified API Details

### Gemini (google-genai 2.34.0, introspected after install)

- Client: `client = genai.Client()` reads `GEMINI_API_KEY`/`GOOGLE_API_KEY`.
- Use `client.models.generate_content(...)`. The SDK 2.34.0 also exposes `client.interactions` (the docs site is now written around the Interactions API), but `generate_content` is fully present with `response_json_schema`, `response_schema`, `.parsed`, `thinking_config`, `tools`, `tool_config`, `automatic_function_calling`, and `http_options.retry_options`. Choose `generate_content`: far more examples, stateless, and every step is easy to log. Re-check if you see deprecation warnings.
- Structured output (current docs use `response_json_schema`):
- Function calling for the bounded agent loop: manual loop, AFC disabled, so you control the iteration cap and log a reason per call.
- Gemini 3.6+ note: `temperature`, `top_p`, `top_k` are deprecated, currently ignored and will 400 on future models. Do NOT set them. Control determinism with explicit system-instruction rules.
- Thinking: `gemini-3.8-flash` supports low/medium/high and errors on `minimal`. `gemini-3.5-flash-lite` defaults to `minimal`; raise to `medium` if it ever takes the agent-loop role.
- Pricing: both are "Free" tier on the pricing page (usage may be used to improve Google products: acceptable for public company websites, but do not put real prospect PII beyond Hunter results in prompts you care about). Free-tier RPM/RPD limits are only shown inside AI Studio (not in fetchable docs). Process domains sequentially, set retries, and keep one fallback model in config.

### Hunter Domain Search (official API docs)

- `GET https://api.hunter.io/v2/domain-search`. Auth: `api_key` query param, or `X-API-KEY` header (prefer header, keeps key out of logs/URLs), or Bearer.
- Params: `domain` (or `company`; domain wins), `limit` (default 10, max 100), `offset`, `type` (`personal`|`generic`), `seniority` (`junior`,`senior`,`executive`, comma-separated), `department` (comma-separated, e.g. `executive,it,management,sales`), `required_field` (`full_name`,`position`,`phone_number`), `decision_maker`, `verification_status`, `provenance`, `job_titles`.
- Response: `data.{domain, organization, pattern, accept_all, webmail, disposable, linked_domains, emails[]}`; each email has `value, type, confidence, first_name, last_name, position, position_raw, seniority, department, decision_maker, linkedin, twitter, phone_number, verification{date,status}, sources[]`; `meta.{results, limit, offset, params}`. No match returns 200 with empty `emails`, `meta.results = 0`. Errors: 400 `wrong_params|invalid_*|pagination_error`, 401, 429, 451.
- Free plan: `limit + offset` must be <= 10 (else `pagination_error`). So always send `limit=10, offset=0` and rank locally. Free plan rate: irrelevant at this volume (15 rps/500 rpm limit is plan-wide).
- Credits: Hunter's pricing page now says the free plan has 50 credits/month, the API doc says "a search costs 1 credit", and a repeat of the same search in the same billing period costs 0 and a call with zero results costs 0. The brief's "25 searches/month" may be an older figure or a different account state. Treat 25 as the working budget. Read `X-Credits-Used` on the first real call, and call `GET /v2/account` (`requests.credits.remaining` or `requests.searches.remaining`) once at startup and print it.
- Recommended call: `type=personal`, `required_field=full_name,position`, `seniority=senior,executive` (or `department=executive,it,management`), `limit=10`; then rank locally by title regex (CISO / Head of Security / CTO / VP Eng / CEO-founder for small companies / Head of Compliance / COO) and `confidence`, dropping `verification.status` of `invalid`. Skip generic `info@` unless nothing else exists, and log that fallback.
- Use `api_key=test-api-key` in tests and fixtures: fixed dummy response, no credits.

### Resend (official docs + 403 error page)

- `pip install resend`; `resend.api_key = os.environ["RESEND_API_KEY"]`; `resend.Emails.send({"from": "Name <onboarding@resend.dev>", "to": [OWN_EMAIL], "subject": ..., "text": ..., "html": ..., "reply_to": ...}, {"idempotency_key": f"outreach/{domain}/{date}"})`. Returns dict with `id`. Params use snake_case (`reply_to`). Idempotency keys: <=256 chars, 24h expiry. Rate limit 10 req/s per team.
- `onboarding@resend.dev` is a test-only sender. Sending to anyone other than the email on your Resend account returns HTTP 403 `validation_error`: "You can only send testing emails to your own email address". Resend docs also say not to use it in production. This matches the brief's hardcoded-recipient rule, so: read `RECIPIENT_EMAIL` from `.env`, assert at startup that it is a single address, and never take `to` from Hunter data. Catch the 403 and print a clear message ("recipient must equal your Resend signup email").
- Send plain `text` (plus optional minimal `html`): cold emails read better as plain text and it sidesteps HTML templating. Put the real prospect name/email in the body or a header line so the demo shows who it WOULD have gone to (e.g. subject prefix `[To: Jane Doe <jane@acme.com>]` in dry-run/demo mode).
- Test recipients `delivered@resend.dev`, `bounced@resend.dev` exist, but test emails count against your quota.

### Scraping design (decision, not a library list)

- Fetch with httpx: `follow_redirects=True`, `timeout=httpx.Timeout(10.0, connect=5.0)`, realistic descriptive `User-Agent`, `http2` off (no extra dep), cap response size (e.g. 1.5 MB, truncate text to ~12k chars per page before LLM). Wrap every fetch so it returns `PageResult(url, status, text|None, error|None)`; failures are data, not exceptions ("tolerating failures").
- Page discovery: try fixed paths first (`/`, `/about`, `/company`, `/careers`, `/jobs`, `/security`, `/trust`, `/pricing`, `/blog`), then harvest nav links from the homepage with BS4 whose href/text matches those keywords. Cap at ~6 pages/company.
- robots.txt: stdlib `urllib.robotparser.RobotFileParser` (fetch robots.txt via httpx with the same UA so it respects the timeout, then `parse()` lines; `RobotFileParser.read()` has no timeout control). Honor disallow for the public marketing paths, and log "skipped by robots". No extra dependency. It is a courtesy and a defensible talking point in the demo.
- JS-heavy sites (SPA shells where trafilatura returns `None` or < ~300 chars): fall back to Jina Reader, `GET https://r.jina.ai/<url>` (no key needed for basic use, ~20 req/min without key, renders JS in a headless browser by default, ~seconds latency, `Accept: application/json` available). Free, zero install, one httpx call. Log that the fallback was used. Playwright is the heavier alternative if Jina is unacceptable for the demo.
- Do not use Gemini's built-in URL Context tool as the scraper: fetches become opaque (harder to log "why this page"), and combining it with function calling is a Gemini-3 preview feature. Keep fetching in your own code so the decision log is complete.

## Installation

# Core

# Dev

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `gemini-3.8-flash` (agent, drafting) | `gemini-3.6-flash` (GA 2026-07-21, same price tier) | If 3.8 free-tier RPM/RPD is too tight during the demo, set `GEMINI_MODEL_SMART=gemini-3.6-flash`. |
| `gemini-3.5-flash-lite` (extraction) | Use `gemini-3.8-flash` for every step | If extraction quality on messy pages is poor or if you want one model to debug. Costs only latency. Simplest single-model variant for a 1.5h build. |
| `generate_content` | Interactions API (`client.interactions.create`) | Docs are migrating to it and it is in the 2.34 SDK, but examples are fewer and state lives server-side (`previous_interaction_id`), which hurts a fully-logged loop. Revisit after the build. |
| Manual function-calling loop | SDK automatic function calling (pass Python callables as `tools`) | Faster to write, but loses the hard iteration cap per step and per-call reason logging, and AFC on `generate_content` is slated for removal in the next major. |
| httpx + trafilatura + BS4 | Firecrawl / Playwright | Firecrawl needs another key and quota; Playwright adds a browser download and async. Use only if many targets are SPAs and Jina is blocked. |
| Typer | argparse | argparse has zero deps and is fine if only 2-3 flags are needed. |
| JSON-file cache | `diskcache` 5.6.3 (SQLite-backed), stdlib `sqlite3` | diskcache is fine but unmaintained since 2023 and the cache must be human-inspectable for the demo. Use sqlite only if you need queries across runs. |
| Plain `os.environ` + dotenv | pydantic-settings | Worth it only if config grows past ~8 keys. |
| Hunter via httpx | `pyhunter` or other wrappers | Third-party, stale, and one GET endpoint does not justify a dependency. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `google-generativeai` (legacy SDK) | Superseded by `google-genai`; older tutorials still show it. | `google-genai` |
| `gemini-2.0-flash*`, `gemini-2.5-flash`, `gemini-2.5-pro` | 2.0 is shut down; 2.5 Flash/Pro are deprecated and auto-route to `3.5-flash-lite` / `3.8-flash` on 2026-12-01 (behaviour changes under you). Many tutorials still use them. | `gemini-3.8-flash` / `gemini-3.5-flash-lite` |
| `gemini-flash-latest` and other `*-latest` aliases | Alias targets move (changelog shows it was re-pointed to a preview model in Jan 2026), which breaks repeatability. | Pinned model IDs from `.env` |
| `*-preview` model IDs (`gemini-3-flash-preview`, `gemini-3.1-pro-preview`) | Preview IDs get shut down on short notice (`gemini-3-pro-preview`, `gemini-3.1-flash-lite-preview` already did). | GA IDs above |
| `temperature` / `top_p` / `top_k` in config | Deprecated on 3.6+ (ignored now, 400 on future models). | System-instruction rules + schema validation + retry-on-validation-failure |
| `thinking_level="minimal"` on `gemini-3.8-flash` | Returns an error. | `low` for extraction, `medium` for the agent loop |
| `response_schema` with raw `dict` of old OpenAPI subset | The current docs standardise on JSON Schema via `response_json_schema`. | `response_json_schema=Model.model_json_schema()` |
| Trusting schema constraints (`maxLength`, `uniqueItems`) | Silently stripped by Gemini's constrained decoding. | Pydantic validation after parsing |
| `requests` + BeautifulSoup only, no timeouts | Hangs on slow sites, kills the demo run. | httpx with explicit timeouts |
| `RobotFileParser.read()` directly | No timeout, uses urllib default UA. | Fetch robots.txt with httpx and `parse()` |
| Sending to Hunter-found addresses | Brief hardcodes `to:`; `onboarding@resend.dev` 403s for other recipients anyway, and cold-emailing real people is out of scope. | `RECIPIENT_EMAIL` from `.env` only |
| Hunter searches without a cache | 25-50 credits/month total. | File cache keyed by normalised domain, checked first |
| Selenium, Scrapy | Heavy frameworks for ~6 pages/company. | httpx + trafilatura |
| `langchain` / `crewai` / agent frameworks | Hide the loop, add dependency churn, and the brief wants a bounded, logged loop you can defend. | A 30-line manual loop |

## Stack Patterns by Variant

- Retry through `https://r.jina.ai/<url>` once, mark `fetched_via: "jina"` in the log.
- Because it renders JS with no install and no extra key.
- Rely on SDK `retry_options` (attempts=3), process domains sequentially, switch `GEMINI_MODEL_SMART` to `gemini-3.6-flash`, and cache extraction JSON per domain so reruns are free.
- Because RPM/RPD per model are only visible in AI Studio.
- Log "no named PoC", optionally fall back to the best `generic` contact and mark the email as non-personalised, or skip the company. Zero-result searches cost no credit.
- Because the brief requires a named person: a generic inbox cannot satisfy it.
- One model (`gemini-3.8-flash`) for every step, no flash-lite, no Jina, no tenacity, no respx. Add them in the deepen phase.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| google-genai 2.34.0 | Python >=3.11 | Pin `<3.0.0` (SDK's own advice). Imports pydantic v2 types, so pydantic 2.14.2 is fine (installed together in a clean venv without conflict). |
| resend 2.50.1 | Python >=3.7 (any) | `Emails.send(params, options)` takes TypedDicts; plain dicts work. Verified signature by introspection. |
| trafilatura 2.3.1 | Python >=3.10, lxml | Install lxml explicitly; BS4 uses it as parser too. |
| typer 0.27.3 | Python >=3.10, rich | rich is bundled. |
| pydantic-settings 2.16.2 | Python >=3.11 | Only relevant if you add it. |
| pytest 9.2.0 | Python >=3.10 | Fine on 3.13. |

## Gaps / Needs a live check in the first 10 minutes of the build

## Sources

- PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`), queried 2026-11-03: google-genai 2.34.0, pydantic 2.14.2, resend 2.50.1, httpx 0.28.1, trafilatura 2.3.1, beautifulsoup4 4.15.0, lxml 6.1.3, typer 0.27.3, python-dotenv 1.2.4, pytest 9.2.0, respx 0.23.1, tenacity 9.2.1, playwright 1.64.1, diskcache 5.6.3 — HIGH
- Installed google-genai 2.34.0 and resend 2.50.1 in a clean venv and introspected `GenerateContentConfig`, `ThinkingConfig`, `HttpRetryOptions`, `AutomaticFunctionCallingConfig`, `FunctionCallingConfigMode`, `Emails.send` signature, exception classes — HIGH
- https://aistudio.google.com/docs/models (redirect from ai.google.dev/gemini-api/docs/models) — model IDs and statuses — HIGH (official)
- https://aistudio.google.com/docs/models/gemini-3.8-flash — capabilities, thinking levels, context — HIGH
- https://aistudio.google.com/docs/deprecations — shutdown dates (2.5 Flash/Pro: 2026-12-01; 2.0: shut down) — HIGH
- https://aistudio.google.com/docs/changelog — GA dates for 3.8/3.6/3.5-flash-lite — HIGH
- https://aistudio.google.com/docs/whats-new-gemini-3.6 — sampling parameter deprecation, thinking levels — HIGH
- https://aistudio.google.com/docs/pricing — free tier per model, paid prices — HIGH (page truncated at 100k chars; rate limits not shown)
- https://aistudio.google.com/docs/structured-output — supported/stripped schema keywords — HIGH
- https://aistudio.google.com/docs/function-calling — Interactions-API examples; used only for tool_choice modes and confirmation that SDKs handle thought signatures — MEDIUM (docs show Interactions API, not generate_content)
- https://github.com/googleapis/python-genai README — `response_json_schema`, AFC disable, `maximum_remote_calls`, pin `<3.0.0` — HIGH
- https://hunter.io/api-documentation/v2 (Domain Search, Account) — params, response fields, errors, free `limit+offset<=10`, `test-api-key`, credit cost notes — HIGH (official), conflict noted on credit allowance
- https://hunter.io/pricing — Free plan 50 credits/month, search 1 credit — MEDIUM (conflicts with brief's 25)
- https://resend.com/docs/send-with-python — SDK usage, errors, idempotency — HIGH
- https://resend.com/docs/knowledge-base/403-error-resend-dev-domain and https://resend.com/docs/api-reference/errors — 403 "You can only send testing emails to your own email address" — HIGH
- https://jina.ai/reader/ — r.jina.ai usage and rate limits — MEDIUM
- https://trafilatura.readthedocs.io/en/latest/usage-python.html — `extract` params, `None` return behavior — HIGH

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-fast` for a trivial task inline, with no subagents and no PLAN.md
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
