---
phase: 02-runner-cli-and-real-scrape-extract
verified: 2026-11-03T11:30:00Z
status: passed
score: 5/5 must-haves verified
covered_files:
  - .planning/phases/02-runner-cli-and-real-scrape-extract/02-01-PLAN.md
  - .planning/phases/02-runner-cli-and-real-scrape-extract/02-01-SUMMARY.md
  - .planning/phases/02-runner-cli-and-real-scrape-extract/02-02-PLAN.md
  - .planning/phases/02-runner-cli-and-real-scrape-extract/02-02-SUMMARY.md
  - .planning/phases/02-runner-cli-and-real-scrape-extract/02-03-PLAN.md
  - .planning/phases/02-runner-cli-and-real-scrape-extract/02-03-SUMMARY.md
  - src/outreach/cli.py
  - src/outreach/extract.py
  - src/outreach/fetch.py
  - src/outreach/models.py
  - src/outreach/pagegate.py
  - src/outreach/runner.py
  - src/outreach/scrape.py
  - src/outreach/stages.py
covered_digest: "v4:sha256:d81a9771c4b393dc3cc1a428796d034be925ba5008cdd4a3ccda932eb8b0669d"
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: Runner, CLI and Real Scrape/Extract Verification Report

**Phase Goal:** User runs one command on a file of domains and each domain is safely scraped and turned into schema-validated, evidence-quoted company data, with one bad domain never stopping the batch.
**Verified:** 2026-11-03
**Status:** passed
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | One command on a domains file, no prompts, dry-run default, `--send` required to send | VERIFIED | `cli.py` `run` takes `DOMAINS_FILE`, `--send` (default False) and `--live-hunter`. `build_context(dry_run=not send, sender=None)`. The Hunter client is the offline fixture unless `--live-hunter`. `send.py` `send_email` has no recipient parameter and only calls Resend when `dry_run` is False. `outreach run --help` shows exactly this. Tests: `test_run_cli_defaults_to_dry_run_and_never_sends`, `..._send_flag_calls_sender_once_per_completed_domain`, `..._has_no_interactive_prompt`. |
| 2 | A dead or timed-out domain is recorded failed and the batch continues. A systemic failure (bad key) aborts the batch at once | VERIFIED | `runner.run_batch` catches `Exception` per domain (the isolation boundary) and maps it to a `failed` row. `SYSTEMIC_ERRORS = (LLMAuthError, LLMQuotaError, HunterAuthError, HunterQuotaError, SendError)` sets `aborted=True`, redacts the reason, lists the remaining domains as `failed` "not run (batch aborted)", and the CLI exits 3. `llm.py` raises `LLMAuthError` for 401/403 and 400 "api key", and `LLMQuotaError` for 429 after retries or an over-long retryDelay. `stages.stage_scrape` raises `DomainUnreachable` when every fetch is a transport error, so a dead domain is a plain failure and not a stop. Tests: `test_unreachable_domain_is_failed_and_batch_continues`, `test_systemic_error_aborts_batch` (parametrized over all 5 types, asserts the later domains never fetch), `test_abort_reason_is_redacted`, `test_run_cli_aborted_batch_exits_three`. Live: `not-a-real-domain-xyz.invalid` -> `failed (DomainUnreachable ... gaierror)` and the batch completed (`out/_batch/summary.json`, `aborted:false`). |
| 3 | The end-of-run summary table lists every domain with an outcome from the full 7-value set | VERIFIED | `models.OUTCOMES` is the 7 values (qualified, disqualified, insufficient_data, no_contact, rejected_draft, sent, failed). `runner.outcome_for` maps every `RunRecord` to one of them (an unknown stop reason becomes `failed`). `render_summary` prints the domain/outcome/detail table plus a count of all 7 outcomes, and `write_summary` writes `out/_batch/summary.json`. Rejected lines stay in file order as `failed`. Tests: `test_outcome_for_maps_all_seven_outcomes`, `test_render_summary_lists_every_domain_and_all_seven_counts`, `test_rejected_lines_keep_file_order_in_summary`. Live summary lists both domains with all 7 counts. Note: `disqualified` and `rejected_draft` cannot occur yet because the producing stages are Phase 3 and 5. The vocabulary and mapping exist, which is what this criterion asks for. |
| 4 | Homepage plus about, careers, security/trust, pricing and customers fetched with timeouts, size caps and robots.txt respected. A thin or blocked page is unavailable and never reaches the LLM | VERIFIED | `scrape.scrape_domain` covers the 6 `PAGE_KINDS`: nav-harvested links first, then fixed paths, with caps of 3 attempts per kind, 14 fetches and 60 s per domain. `fetch.PageFetcher` has a 10 s read / 5 s connect timeout, a 1.5 MB streamed body cap, an 8000-char text cap and a 20 s deadline. It parses robots.txt per RFC 9309 (a 5xx or transport error blocks the host), checks every redirect hop against the same-site rule, refuses private addresses (SSRF), strips hidden text, and keeps a 1 s politeness gap. `pagegate.page_gate` marks empty, blocked or <400-char text unavailable. `stages.usable_pages` re-applies the gate at the extract call site, so no unusable page reaches the LLM. Tests: 40+ in `test_fetch.py` and `test_scrape.py`, including `test_blocked_page_never_reaches_llm_through_run_batch` and `test_only_usable_pages_reach_extract_prompt`. Live: linear.app fetched all 6 kinds (6 fetches, none skipped). |
| 5 | Extracted data validates against the schema with unknowns null. Every evidence item has a quote and source URL that is a verbatim substring of the fetched text. Planted instructions do not change the output | VERIFIED | `models.CompanyProfile` has no field defaults, so the LLM must state null or []. `extract.validate_profile` keeps an item only if its `source_url` maps to a fetched page and its quote (at least 8 chars, whitespace-normalised) is a substring of the exact `prompt_text` the model saw. Everything else is dropped with a reason code, and `as_of` is cleared if it is not on the page. Injection defence: instruction-like lines are stripped before prompting, `<page` tags are escaped, attributes are escaped, the system prompt marks page text as untrusted, and no tools are passed (`test_extract_call_passes_no_tools` checks the `cfg.tools is None` config). `test_injected_page_yields_same_validated_profile_as_clean_page` feeds an obedient fake LLM that echoes the planted facts and shows the output equals the clean-page output, with the planted quotes dropped. Live: the linear.app run kept 6 of 7 evidence items. One hallucinated `name` quote was dropped as `quote_not_on_page` and became null, and every kept quote cites a fetched page. |

**Score:** 5/5 truths verified (0 behavior-unverified).

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| RUN-01 | One command on a domains file, no decisions between steps | SATISFIED | `outreach run DOMAINS_FILE`; no prompt anywhere (test checks it); live run executed end to end |
| RUN-02 | One domain's failure is recorded and the batch continues; a systemic failure aborts | SATISFIED | `runner.run_batch` and `SYSTEMIC_ERRORS`; tests and the live `.invalid` run |
| RUN-03 | Dry-run by default; `--send` needed to send | SATISFIED | `cli.run` `--send` default False; `send_email` guarded; tests |
| RUN-04 | Summary table with the 7 outcomes | SATISFIED | `OUTCOMES`, `outcome_for`, `render_summary`, `write_summary` |
| SCR-01 | Homepage + about/careers/security/pricing/customers, with timeouts, caps, robots.txt | SATISFIED | `scrape.py`, `fetch.py`; linear.app got all 6 kinds live |
| SCR-02 | Thin or blocked pages unavailable and never passed to the LLM | SATISFIED | `pagegate.py`, `stages.usable_pages`; tests |
| EXT-01 | Schema-validated company data (offering, B2B, stage, headcount, compliance, hiring, enterprise customers) | SATISFIED | `CompanyProfile` and `extract_profile`; live linear.app profile |
| EXT-02 | All fields nullable; every evidence item has quote + source URL checked as a substring | SATISFIED | `validate_profile`, `DroppedEvidence`; live drop of the bad `name` quote |
| EXT-03 | Scraped text untrusted, delimited, no side-effect tools | SATISFIED | `EXTRACT_SYSTEM`, `escape_page_tags`, `strip_instruction_lines`, no tools; tests |

No orphaned requirements: REQUIREMENTS.md maps exactly these 9 IDs to Phase 2, and all 9 are claimed by plans.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite (run once) | `.venv/bin/python -m pytest -q` | 279 passed in 3.65s | PASS |
| Secrets scan | `.venv/bin/python scripts/check_secrets.py` | OK: no secrets found (93 files scanned) | PASS |
| CLI surface | `.venv/bin/python -m outreach run --help` | Shows `DOMAINS_FILE`, `--send`, `--live-hunter` and the exit-code contract | PASS |
| Live dry run (orchestrator-run, not re-run) | `outreach run out/live-domains.txt` | linear.app -> `no_contact` (scrape and extract ok, stopped at the fixture Hunter by design). `.invalid` -> `failed` (DomainUnreachable). Batch complete, `aborted:false`. I re-read `out/linear.app/run.json` and `out/_batch/summary.json` and they match this. | PASS |

### Probe Execution

No phase-declared probes. Step 7c: SKIPPED.

### Anti-Patterns Found

None blocking. No TBD/FIXME/XXX/TODO/HACK markers in `src/outreach/*.py`. No stubs: every module is substantive and wired (`cli.run` -> `run_batch` -> `run_one` -> `stages` -> `scrape_domain`/`PageFetcher` and `extract_profile` -> `LLMClient`).

### Advisory observations (non-blocking)

- Live linear.app's "about" page resolved to a changelog URL (`/changelog/2026-09-14-loops-for-product-management`). The nav-link harvest matched a keyword loosely, so page-kind targeting is heuristic. It stays on the same site and passes the gate, so SCR-01 holds, but harvest precision could be tightened in a later phase.
- Prompt-injection resistance of the real Gemini model is shown only through an obedient fake LLM plus deterministic layers (line stripping, tag escaping, quote validation, no tools). The deterministic layers are what guarantee the criterion, so this is not a gap, and no live injection test was run.

### Human Verification Required

None.

### Gaps Summary

No gaps. The runner, safe scraper and evidence-validated extractor exist, are wired end to end, and are exercised by passing tests and by the live dry run. All 5 success criteria and all 9 requirement IDs are satisfied.

---

_Verified: 2026-11-03_
_Verifier: Claude (gsd-verifier)_
