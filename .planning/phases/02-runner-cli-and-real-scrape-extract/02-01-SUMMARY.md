---
phase: 02-runner-cli-and-real-scrape-extract
plan: 01
subsystem: batch-runner-and-cli
tags: [python, typer, batch, isolation, systemic-abort, dry-run, summary-table, pytest]
status: complete

requires:
  - phase: 01-foundation-and-walking-skeleton
    provides: "run_one (flushes run.json per stage, re-raises on failure), Context, build_context, send_email guard, RunStore, redact, offline fakes"
provides:
  - "outreach.models: OUTCOMES (closed seven-value vocabulary), Outcome, BatchRow, BatchSummary"
  - "outreach.runner: load_domains (file-order entries, rejected lines as failed BatchRows, 25-domain cap), outcome_for, run_batch (per-domain isolation, systemic abort), render_summary, write_summary (out/_batch/summary.json)"
  - "outreach.stages.DomainUnreachable: raised when no page is usable and every fetch failed at transport level"
  - "CLI: python -m outreach run DOMAINS_FILE [--send] [--live-hunter]; exit 0 complete, 2 input/config, 3 aborted"
affects: [02-02, 02-03, phase-3, phase-5, phase-6]

actuals:
  tokens: 7800
  tasks: 2
  commits: 3
plan_head_before: 90916890c0a5394bb7d1e936a827093103ab3424
plan_head_after: e16735dcc2081e8ae566fb9be68983dd98170083

tech-stack:
  added: []
  patterns:
    - "Per-domain try/except around run_one is the single isolation boundary; the outcome is read back from the already-flushed run.json"
    - "SYSTEMIC_ERRORS tuple (LLM auth/quota, Hunter auth/quota, SendError) aborts the batch; every later domain is listed as failed 'not run (batch aborted)'"
    - "Rejected input lines become failed BatchRows at their own file position and never reach run_one"
    - "Dry run is the default; dry_run=not send is the only switch that lets send_email reach Resend"
    - "Plain-text summary (not rich) so CliRunner output is stable"

key-files:
  created:
    - src/outreach/runner.py
    - tests/test_runner.py
    - tests/test_cli_run.py
  modified:
    - src/outreach/models.py
    - src/outreach/stages.py
    - src/outreach/cli.py

key-decisions:
  - "Hunter defaults to the offline fixture for `run` (no qualification gate until Phase 3; REQUIREMENTS rules out pre-qualification Hunter lookups); --live-hunter opts into the cache-first, budget-capped client"
  - "Per-domain failures are data in the table, so a batch with failed rows still exits 0; only a systemic abort exits 3"
  - "A hostname must have at least two valid labels and a non-numeric last label; this rejects IPv4, localhost, bracketed IPv6 and names with spaces before any fetch"
  - "Test-double fetchers use fetch(self, url, site=None) from the start so Plan 02-02's site= keyword does not break them"

requirements-completed: [RUN-01, RUN-02, RUN-03, RUN-04]

coverage:
  - id: D1
    description: "A domains file runs through `outreach run` with no prompts and ends in a printed and saved summary table listing every domain with one outcome"
    requirement: "RUN-01"
    verification:
      - kind: e2e
        ref: "tests/test_cli_run.py#test_run_cli_domains_file_prints_summary_table"
        status: pass
      - kind: e2e
        ref: "tests/test_cli_run.py#test_run_cli_has_no_interactive_prompt"
        status: pass
    human_judgment: false
  - id: D2
    description: "A dead or erroring domain is recorded as failed and the batch continues; systemic errors abort at once with a redacted reason and exit 3"
    requirement: "RUN-02"
    verification:
      - kind: unit
        ref: "tests/test_runner.py#test_unreachable_domain_is_failed_and_batch_continues"
        status: pass
      - kind: unit
        ref: "tests/test_runner.py#test_stage_exception_is_failed_and_batch_continues"
        status: pass
      - kind: unit
        ref: "tests/test_runner.py#test_systemic_error_aborts_batch"
        status: pass
      - kind: unit
        ref: "tests/test_runner.py#test_abort_reason_is_redacted"
        status: pass
      - kind: e2e
        ref: "tests/test_cli_run.py#test_run_cli_aborted_batch_exits_three"
        status: pass
    human_judgment: false
  - id: D3
    description: "Dry run is the default; only --send calls Resend, once per domain that reaches the send stage, always addressed to OWNER_EMAIL"
    requirement: "RUN-03"
    verification:
      - kind: e2e
        ref: "tests/test_cli_run.py#test_run_cli_defaults_to_dry_run_and_never_sends"
        status: pass
      - kind: e2e
        ref: "tests/test_cli_run.py#test_run_cli_send_flag_calls_sender_once_per_completed_domain"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every summary row carries one outcome from the closed set of seven, and the counts line always shows all seven; invalid and skipped lines appear at their file position"
    requirement: "RUN-04"
    verification:
      - kind: unit
        ref: "tests/test_runner.py#test_outcome_for_maps_all_seven_outcomes"
        status: pass
      - kind: unit
        ref: "tests/test_runner.py#test_render_summary_lists_every_domain_and_all_seven_counts"
        status: pass
      - kind: unit
        ref: "tests/test_runner.py#test_rejected_lines_keep_file_order_in_summary"
        status: pass
    human_judgment: false
  - id: D5
    description: "Input hygiene and cost bound: IP literals, localhost and malformed lines are rejected before any fetch; more than 25 valid domains is refused with exit 2"
    verification:
      - kind: unit
        ref: "tests/test_runner.py#test_invalid_domain_lines_are_failed_rows"
        status: pass
      - kind: e2e
        ref: "tests/test_cli_run.py#test_run_cli_cap_exits_two"
        status: pass
    human_judgment: false

duration: 22min
completed: 2026-11-03
---

# Phase 2 Plan 01: Runner CLI and Batch Semantics Summary

**`python -m outreach run domains.txt` runs every domain through the real six-stage pipeline in file order, isolates per-domain failures, aborts on systemic ones with a redacted reason (exit 3), stays a dry run unless `--send` is passed, and prints and saves a seven-outcome summary table.**

## Performance

- **Duration:** about 22 min
- **Tasks:** 2 of 2 (Task 1 tracer, Task 2 TDD)
- **Files:** 3 created, 3 modified
- **Suite:** 153 tests at start, 183 at end, all offline; `scripts/check_secrets.py` clean

## Accomplishments

- Tracer: a domains file goes through the new `run` command, `run_batch` and the unchanged `run_one` to a printed table and `out/_batch/summary.json`, proven with the Phase 1 fakes.
- Isolation: an exception in one domain is read back from its flushed `run.json` and recorded as `failed`; the next domain still runs.
- `DomainUnreachable` in `stage_scrape`: when no page is usable and every fetch is a transport error (status `error`), the domain ends `failed` with `failed_stage=scrape`; thin or blocked pages stay `insufficient_data`.
- Systemic abort over `LLMAuthError`, `LLMQuotaError`, `HunterAuthError`, `HunterQuotaError`, `SendError`: later domains are never fetched, are listed as failed `not run (batch aborted)`, the reason passes through `redact()`, `summary.json` is still written, exit code is 3.
- `--send` is the only path to `dry_run=False`; the banner states the mode before any domain runs; `--live-hunter` adds `HUNTER_API_KEY` to the required settings and selects the cache-first client.
- Input hygiene: rejected lines become failed rows at their file position and never run; a 25-domain cap (exit 2).

## Task Commits

1. **Task 1 (tracer): domains file to summary table** - `61f9e94` (feat)
2. **Task 2 RED: failing tests for batch semantics** - `f309859` (test)
3. **Task 2 GREEN: isolation, systemic abort, flags, hygiene** - `e16735d` (feat)

## Tracer gate

Tracer verified end-to-end (CLI tracer test plus full suite re-run) before expansion; no checkpoint was required in the default `end-of-phase` mode with an automated-only `<verify>`.

## Deviations from Plan

None - plan executed exactly as written.

One small addition inside plan scope: `metavar="DOMAINS_FILE"` on the Typer argument, because Typer otherwise renders the placeholder as `{domains_file}` and the acceptance criterion greps for `DOMAINS_FILE`. Three extra tests beyond the named ones: `test_systemic_errors_are_the_five_documented_types`, `test_run_cli_abort_output_never_contains_the_key` (CLI-level redaction) and `test_run_cli_reports_invalid_lines_in_banner_and_table` (the `invalid: N` banner part).

**Total deviations:** 0 auto-fixed. **Impact:** none.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths or file access beyond the plan's threat model (T-02-01 to T-02-05 mitigated and tested; T-02-06 and T-02-07 accepted as planned).

## Owner-pending items

- The optional live check (a real site plus a dead `.invalid` domain through `outreach run`) belongs to Plan 02-03 Task 2's human-check. It was not run here: this plan made no live network call, never opened `.env`, and spent no Gemini, Hunter or Resend call. Recorded as owner-pending.

## Next Phase Readiness

Plans 02-02 and 02-03 can deepen scrape and extract behind the unchanged runner. Local test fetchers already accept `fetch(url, site=None)`. Note for 02-02: the `FakeFetcher` in `tests/conftest.py` still has `fetch(self, url)` and must gain `site=None` when `FetcherLike.fetch` changes (the plan's grep gate covers only the two new test files).

## Self-Check: PASSED

- Files exist: `src/outreach/runner.py`, `tests/test_runner.py`, `tests/test_cli_run.py` (FOUND)
- Commits `61f9e94`, `f309859`, `e16735d` are ancestors of HEAD (FOUND)
- `.venv/bin/python -m pytest -q`: 183 passed; `scripts/check_secrets.py`: OK
- All task acceptance criteria re-run and passing (`--help` shows `DOMAINS_FILE`, `--send`, `--live-hunter`; `grep` gates return the expected counts; every local `def fetch(` accepts `site=None`)
