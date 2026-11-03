# Project Research Summary

**Project:** sprinto-outreach (automated cold-outreach pipeline for Sprinto)
**Domain:** Batch B2B outbound / AI SDR pipeline selling compliance automation (SOC 2, ISO 27001, GDPR)
**Researched:** 2026-11-03
**Confidence:** MEDIUM-HIGH

## Executive Summary

This is a linear, synchronous, per-domain Python CLI pipeline: scrape -> schema-validated LLM extraction -> deterministic weighted ICP score with a small bounded agent loop -> Hunter PoC lookup -> grounded pain points and email draft with a deterministic claim validator -> Resend send. Experts build this as a deterministic skeleton with an LLM used only for judgment (extraction, drafting), with no agent framework. The commercial tools (Clay, Apollo, Artisan, 11x) win on volume plumbing. None of that is in scope. What they under-deliver, and what this brief rewards, is defensibility: why this company, why this person, why this email. The product is the per-company decision log.

The ICP, from the brief, is SaaS companies, typically Series A-C, preparing for an audit or pressured by enterprise customers to certify. Research on G2 reviewer mix suggests the real sweet spot skews small (20-300 employees). Decisions locked by the user: Python, Gemini API, Resend (`from: onboarding@resend.dev`, `to:` hardcoded to the user's own email), Hunter, a weighted-score ICP, a CLI plus decision log, and a build time-boxed to 1.5 hours.

The recommended approach is one thin vertical slice first (one hardcoded domain reaching a dry-run send), then deepening in order of demo value. Evidence quotes with source URLs must be in the extraction schema from the start. That single decision enables the score breakdown, hook provenance and the hallucination validator, and is costly to retrofit. The main risks are fabricated data from empty or blocked scrapes, hallucinated email facts, Hunter quota burn (free tier), a runaway agent loop, Gemini 429s, and time overrun. Each has a concrete code-level mitigation below.

## Key Findings

### Recommended Stack

Plain Python 3.11+ (3.13 on this machine) in a venv, no database, no agent framework. Pin `google-genai>=2.34,<3`. Use pinned GA model IDs from `.env`, never `*-latest` or `*-preview`, and do not set `temperature/top_p/top_k` (deprecated on 3.6+). Files on disk (JSON cache, JSONL/JSON decision log) serve as both cache and demo artifact.

**Core technologies:**
- google-genai 2.34 with `gemini-3.8-flash` (agent loop, drafting; thinking `low`/`medium`, never `minimal`) and `gemini-3.5-flash-lite` (bulk extraction): official SDK. Fallback to a single model (`3.8-flash` everywhere) if time is short, and `gemini-3.6-flash` if rate limits bite.
- Pydantic 2.14: `model_json_schema()` into `response_json_schema`, `model_validate_json` as the validation gate; nullable fields mean "unknown stays unknown".
- httpx 0.28 + trafilatura 2.3 + beautifulsoup4/lxml: fetch with explicit timeouts and size caps, clean text, discover nav links. Jina Reader (`r.jina.ai`) as a zero-install fallback for JS-only sites. No Playwright by default.
- resend 2.50: official SDK, plain-text email, idempotency key; `typer` for the CLI (`--dry-run`, `--limit`); `python-dotenv`; `pytest` + `respx`.
- Hunter via httpx (one GET endpoint, no wrapper library). Prefer the `X-API-KEY` header so the key stays out of logged URLs.

### Expected Features

**Must have (table stakes):**
- Batch run over a domain file with per-domain error isolation and dry-run default
- Multi-page, failure-tolerant scrape; failures recorded as data (`page_unavailable`), never crashes
- Schema-validated extraction with nullable fields and `quote` + `source_url` per evidence item
- Weighted ICP rubric (hard gates, positives summing to 100, penalties, threshold 60) computed deterministically in Python
- Bounded agent loop (cap 3) with a logged reason per extra fetch
- Hunter PoC lookup with disk cache, title ranking by company-size band, and skip-and-log when no named contact
- Two grounded pain points per persona; personalized 50-90 word plain-text email with a deterministic validator
- Resend send with hardcoded recipient, and a per-company decision log (JSON + markdown)

**Should have (competitive):**
- Score interval (min with unknowns=0, max with unknowns=full weight) driving loop targeting: qualify if min >= 60, reject if max < 45, else loop
- Hook-to-evidence provenance map in the log
- Persona-specific hooks (founder / CTO / security / GRC) from a pain library
- Incumbent detection (Vanta, Drata, Secureframe etc. by brand-name string match) with a -25 penalty and hook branching
- Calibration summary table across the batch

**Defer (v2+):**
- Real-recipient sending with a verified domain, follow-up sequences, CRM/reply handling, multi-contact buying committees, paid signal sources, multi-framework expansion angle

**Anti-features:** web UI, LinkedIn scraping, LLM-judged free-form fit score, unbounded crawling, guessing emails, Hunter before qualification, invented social proof, A/B infra.

### Architecture Approach

Seven stage functions with typed Pydantic hand-offs. A single runner sequences the stages and is the only writer of `CompanyRun`, which is both the state object and the audit record and is flushed to `run.json` after every stage so a crash leaves a partial trail. Stages never call each other or touch the network directly, and receive clients, cache and audit through a `Context`. Expected stops (`GateStop`: disqualified, no_poc) are kept separate from real failures. Dry-run replaces only the final HTTP call. `to` is not a parameter of the send stage and is enforced against config inside `send()`.

**Major components:**
1. `runner.py` / `cli.py` — per-domain loop, failure isolation, gates, summary table, flags (`--send` required for a live send, `--live-hunter`, `--replay`)
2. `stages/` (scrape, extract, qualify, poc, pain, draft, send) — business logic; Python owns scraping, weighted math, gate, Hunter ranking, validation and recipient override
3. `llm.py` — sole Gemini importer (retry/backoff on 429/5xx, repair retry on validation failure, `finish_reason` and `None` text checks, usage logging)
4. `clients/` (http, hunter, resend), `cache.py`, `audit.py` — I/O, disk cache keyed by normalized domain, decision log rendered to `decision.md` from `run.json` by a pure renderer
5. `config/icp.yaml` + `prompts/*.md` — rubric, weights, threshold and title ranking as data, hashed into every log

**Reconciling the research files (be opinionated here):**
- Scoring: use the FEATURES rubric. The LLM extracts evidence-quoted facts, and Python applies the signal rules, penalties and thresholds. Do not have the LLM emit per-criterion 0-5 numbers, which makes the score less reproducible.
- Agent loop: a manual function-calling loop (AFC disabled, hard `for` cap of 3) whose only tool is `fetch_page(url, reason)`, with candidate URLs generated by code from same-registrable-domain links, a dedupe set, private-IP rejection, and a no-progress stop. Run the final verdict as a separate structured call, since tools plus `response_json_schema` in one request is a Gemini-3-only preview. If the function-calling round trip proves flaky in the first 10 minutes, fall back to the PITFALLS variant: the model returns structured next-action JSON and Python fetches.
- Skip the `search` tool; `fetch_url` plus guessed and discovered paths covers most of the value.

### Critical Pitfalls

1. **Empty or blocked scrape becomes invented evidence** — gate on minimum usable text (about 400 chars) and block signatures; unusable pages never reach the LLM; all-unusable means `INSUFFICIENT_DATA` and skip-and-log; follow footer/nav links to `trust.` subdomains and ATS pages rather than only guessing paths.
2. **Extraction schema forces fabrication** — nullable fields, tri-state presence enums instead of bool, and a post-check that each `evidence_quote` is a substring of the fetched page text (else null it). Store dates with signals.
3. **Hallucinated email facts or invented PoC names** — the draft uses a closed evidence pack and returns `claims_used`; a deterministic validator checks numbers, proper nouns, name, URLs and banned phrases (one regeneration, then reject); recipient name and title come verbatim from Hunter in code, never from the LLM.
4. **Hunter quota burn** — qualify before Hunter, cache raw responses forever by normalized domain (including zero results) and write the cache before any downstream step, one filtered query per domain with `limit=10`, a persistent budget counter, fixtures for development, and handling of 401/403/429/451.
5. **Runaway agent loop, Gemini 429s and time overrun** — code-enforced cap, per-company call and time budgets, `stop_reason` enum, sequential processing, LLM response cache, per-company try/except plus a batch circuit breaker, and a walking skeleton by about T+30 min.

Also: `.gitignore` and `.env.example` must be the first commit; enforce the `to:` guard inside `send()`; treat scraped text as untrusted (delimit it, give the LLM no side-effect tools, restrict fetches to same-domain URLs).

## Implications for Roadmap

Given the 1.5h time box, phases are thin vertical slices with minute budgets, not horizontal layers. Reach a dry-run send for one domain first, then deepen. The design follows ARCHITECTURE's build order, adjusted for the PITFALLS mapping.

### Phase 1: Foundation and Walking Skeleton
**Rationale:** Everything downstream needs config, secrets hygiene, the Gemini wrapper, the cache and the log. A one-domain end-to-end slice proves all four external APIs early.
**Delivers:** `.gitignore` + `.env.example` committed first; venv and pinned deps; `models.py`; `llm.py` (retry, repair retry, startup smoke test); `cache.py` (Hunter cache written immediately); `audit.py` + `CompanyRun`; then one hardcoded domain: scrape home/about -> extract -> simple score -> Hunter (cached or fixture) -> single draft -> dry-run payload printed. Include the first 10-minute live checks (Gemini structured call and function-calling round trip, one Hunter call plus `/v2/account`, one Resend self-send).
**Addresses:** dry-run default, schema with quote + source_url, decision-log skeleton, Hunter cache.
**Avoids:** Pitfalls 5, 7, 8, 10, 13, 16 (and 23).
**Budget:** about 30-35 min.

### Phase 2: Runner, CLI and Real Scrape/Extract
**Rationale:** Isolation and dry-run make every later slice cheap and safe to test. Scrape quality gates must exist before the rubric consumes the data.
**Delivers:** domains file loader with domain normalization; per-domain try/except with `GateStop` vs `failed`; summary table; `--dry-run` default and `--send` flag; multi-page scrape with robots.txt, usable-content gate, block signatures, optional Jina fallback; full nullable extraction with evidence-quote substring validation and untrusted-content delimiting.
**Implements:** runner, `stages/scrape.py`, `stages/extract.py`, `clients/http.py`.
**Avoids:** Pitfalls 1, 2, 11 (sanitise), 18, 22, 20 (dates).
**Budget:** about 15-20 min.

### Phase 3: ICP Rubric and Bounded Agent Loop
**Rationale:** The rubric and loop are the most visible demo pieces and need extracted unknowns to drive them. The pipeline is already shippable without the loop (`--no-agent` fallback), so build the rubric first.
**Delivers:** `icp.yaml` (gates G1-G3, signals A1-C3, penalties, thresholds 60/45); deterministic scorer producing score breakdown, `score_min`/`score_max` and ranked unknown signals; manual loop (cap 3, `reason` arg, same-domain candidate URLs, dedupe, no-progress stop, `stop_reason`); `INSUFFICIENT_DATA` as a distinct outcome; at least one rejected domain with a visible breakdown.
**Implements:** `stages/qualify.py`, `tools.py`.
**Avoids:** Pitfalls 6, 12, 11 (SSRF allowlist). Incumbent detection (P2 feature) fits here if time allows.
**Budget:** about 25 min.

### Phase 4: PoC Selection
**Rationale:** Deterministic and cheap; depends on headcount from extraction; must run only after qualification.
**Delivers:** one filtered Hunter query (`type=personal`, `required_field=full_name,position`, `seniority=senior,executive`, `limit=10`), local title ranking by size band (small/mid/large) with negative keywords and confidence/verification tie-breakers, top-3 candidates and rationale logged, `NO_NAMED_CONTACT` outcome, budget counter and `--live-hunter` flag, persona detection.
**Implements:** `stages/poc.py`, `clients/hunter.py`.
**Avoids:** Pitfalls 4, 5, 19.
**Budget:** about 10 min.

### Phase 5: Pain Points, Draft and Validator
**Rationale:** Needs both the evidence pack (Phase 2) and the persona (Phase 4). The validator is the most visible failure mode, and skipping it is never acceptable.
**Delivers:** persona pain library with two pains each grounded in an evidence ID; draft constrained to 50-90 words, plain text, one evidence-cited hook, one small CTA, with `claims_used`; deterministic validator (name equals Hunter, numbers/nouns in evidence or Sprinto whitelist, no URLs, banned phrases, one question); one regeneration then `DRAFT_REJECTED`; footer with sender identity, address placeholder and opt-out; `[TEST -> intended recipient]` subject prefix; Sprinto proof-point whitelist.
**Implements:** `stages/pain.py`, `stages/draft.py`.
**Avoids:** Pitfalls 3, 14, 15, 21, 20.
**Budget:** about 15 min.

### Phase 6: Send, Decision Log and Demo Hardening
**Rationale:** Last, but the `to:` guard is built and tested early (first live Resend send happens in Phase 1). Remaining time goes to rehearsal.
**Delivers:** `send()` with the `OWNER_EMAIL` assertion inside the function, `id` check, idempotency key, mapped Resend errors; `decision.md` renderer plus `show <domain>` viewer; run on 5-8 pre-chosen domains (2-3 fits, 2 non-fits, 1 unscrapeable, 1 no-Hunter-contact); committed sample output and `--replay` as demo insurance; README "how to run", known limits and compliance notes; secret grep before commit. Freeze features at about T+75.
**Avoids:** Pitfalls 9, 13, 16, 24, 17.
**Budget:** about 10-15 min plus rehearsal.

### Phase Ordering Rationale

- Dependencies are strictly linear: scrape -> extract -> score -> Hunter -> persona -> draft -> send. The one exception is the decision log, which is cross-cutting and built in Phase 1 and appended to by every later phase.
- Qualification gates Hunter, so disqualified domains cost zero credits. The Hunter cache lands in Phase 1, not Phase 4, because the first real call otherwise burns quota.
- Dry-run and isolation precede the agent loop because they make every later slice safe; the loop degrades gracefully if time runs short.
- If the clock runs out, cut in this order: Jina fallback, incumbent detection, separate pain stage (fold into draft but log separately), score-interval targeting (use a simple "if key signal unknown, fetch"). Never cut the validator, the `send()` guard, the decision log or one real send.

### Research Flags

Phases likely needing deeper research or a live check during planning:
- **Phase 1:** run the four live checks first (structured output on both models, function-calling round trip for `role` and `parameters_json_schema` naming, Hunter call with `X-Credits-Used`, Resend self-send). No live API calls were possible during research.
- **Phase 3:** the rubric weights and thresholds are untested hypotheses; calibrate on 10-20 domains (tune weights, not thresholds). Incumbent trust-center badge patterns are LOW confidence, so use brand-name string matching only.
- **Phase 4:** confirm Hunter filter params are accepted on the free plan and header auth works (the remaining 200k chars of the Hunter docs were not read).

Phases with standard patterns (skip research-phase):
- **Phase 2:** httpx, trafilatura and Pydantic extraction are well documented.
- **Phase 5:** prompt and validator design is covered in FEATURES section 5 and PITFALLS 3 and 14; no external research needed beyond the Sprinto whitelist.
- **Phase 6:** the Resend SDK and error behavior are verified against official docs.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions verified on PyPI; google-genai and resend installed and introspected. MEDIUM on Gemini free-tier RPM/RPD (visible only in AI Studio) and the Hunter credit allowance. No live calls made. |
| Features | MEDIUM | Tool landscape and cold-email benchmarks come from vendor blogs (directional). ICP weights and title ranking are reasoned synthesis, not Sprinto data. |
| Architecture | MEDIUM-HIGH | Pattern design is established practice (HIGH). Gemini AFC-disable behavior and Hunter field details verified only from snippets. |
| Pitfalls | MEDIUM-HIGH | Resend, Hunter and Gemini structured-output behavior verified against official docs. CAN-SPAM/GDPR and injection guidance are established practice, not re-verified. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Hunter free-tier quota conflict:** the brief says 25 searches/month; the Hunter pricing page says 50 credits/month, with each search costing 1 credit (repeats and zero-result calls cost 0). Plan around 25 as the working budget and design the demo set at 10 live domains or fewer. Resolve at build start by calling `GET /v2/account` and reading `X-Credits-Used` on the first real call; set the budget counter from the observed number.
- **Brief PDF could not be rendered by the researchers:** they worked from PROJECT.md only. The orchestrator read the brief separately; its ICP (SaaS, typically Series A-C, preparing for an audit or pressured by enterprise customers) matches the research.
- **Sprinto proof-point whitelist:** must be supplied or verified (for example the G2 rating claim) before the drafter may cite anything about Sprinto.
- **Gemini free-tier limits:** unknown until read in AI Studio; budget about 6-8 calls per qualified company and keep `GEMINI_MODEL_SMART` swappable.
- **Tool role and function declaration field naming** in the 2.34 SDK: settle with a single real call in Phase 1.
- **Funding and stage data** is often absent from a company's own site, so expect `unknown` for many domains; this is why interval scoring and the loop matter.
- **Weights and thresholds** are uncalibrated; fix the threshold before looking at the demo set's scores.

## Sources

### Primary (HIGH confidence)
- PyPI JSON API plus local install and introspection of google-genai 2.34.0 and resend 2.50.1 — versions, config classes, `Emails.send` signature
- aistudio.google.com docs (models, deprecations, changelog, pricing, structured output, rate limits) — model IDs and status, schema limits, 3.6+ sampling deprecation
- hunter.io/api-documentation/v2 — Domain Search params and response, free-plan `limit+offset<=10`, credit rules, error codes, `test-api-key`
- resend.com docs (send-with-python, API errors, 403 resend.dev page) — SDK usage, owner-only sandbox restriction, quotas, idempotency
- trafilatura docs — `extract` behavior

### Secondary (MEDIUM confidence)
- hunter.io/pricing — free plan 50 credits/month (conflicts with brief)
- python-genai README and issue tracker (AFC disable behavior, pin `<3.0.0`)
- G2 Sprinto/Vanta reviewer demographics; Sprinto positioning and case studies; SOC 2 buying-journey articles
- Trust-center landscape (SafeBase acquired by Drata; Vanta trust center powered by SafeBase)
- jina.ai/reader — rate limits and usage

### Tertiary (LOW confidence)
- Cold-email benchmarks (Instantly, Prospeo, SyncGTM, Belkins, Martal) — vendor-reported figures, directional only
- AI SDR tool comparison blogs and signal-based-selling content (Persana, Origami, TheirStack) — validate before citing in the demo
- Compliance/GRC persona content (Modern Inbound), CAN-SPAM/GDPR summaries, OWASP LLM01 guidance — established practice, not re-verified; not legal advice

---
*Research completed: 2026-11-03*
*Ready for roadmap: yes*
