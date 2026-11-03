---
phase: 01-foundation-and-walking-skeleton
plan: 02
subsystem: pipeline-core
tags: [python, pydantic, resend, run-record, dry-run, secret-hygiene, pytest, fakes]
status: complete

requires:
  - phase: 01-foundation-and-walking-skeleton
    provides: "Plan 01-01 Settings, load_settings, redact, check_secrets.py"
provides:
  - "outreach.models: pydantic contracts for pages, profile, score, contact, draft, send result, StageRecord and RunRecord"
  - "outreach.cache: atomic_write_json, read_json, normalize_domain"
  - "outreach.audit: RunStore with atomic per-stage flush, now_iso"
  - "outreach.send: SendError, build_payload, send_email (no recipient parameter, dry-run, redacted 403 mapping)"
  - "outreach.stages: six stage functions, StopStage, simple scorer, prompt builders, STAGES"
  - "outreach.skeleton: Context, LLMLike/HunterLike/FetcherLike Protocols, run_one"
  - "tests/conftest.py offline fakes (FakeLLM, FakeHunter, FakeFetcher, FakeSender, FakeModels, FakeGenaiClient) and response builders for Plan 01-03"
  - "tests/fixtures/hunter_domain_search.json captured live from the public test-api-key"
affects: [01-03, 01-04, phase-2, phase-3, phase-4, phase-5, phase-6]

actuals:
  tokens: 11400
  tasks: 2
  commits: 2
plan_head_before: 4b8e39b6ffff9b0c19b51d14cc08c090b20165a3
plan_head_after: 4c19912d608afd1c9bb76ee01ae7ad07e02bac65

tech-stack:
  added: []
  patterns:
    - "Every external call goes through ctx seams; stages and run_one never import an SDK"
    - "run.json written before stage 1 and after every stage via os.replace, never only in finally"
    - "One build_payload shared by dry-run and live; send_email has no recipient parameter"
    - "Single usability filter usable_pages applied at the build_extract_prompt call site"
    - "redact() on every stored stage error and every SendError message"

key-files:
  created:
    - src/outreach/models.py
    - src/outreach/cache.py
    - src/outreach/audit.py
    - src/outreach/send.py
    - src/outreach/stages.py
    - src/outreach/skeleton.py
    - tests/conftest.py
    - tests/fixtures/hunter_domain_search.json
    - tests/test_skeleton_e2e.py
    - tests/test_audit.py
    - tests/test_send.py
  modified: []

key-decisions:
  - "Hard-kill test uses a subprocess with os._exit(17) in the FakeLLM on_call hook, which proves the per-stage flush rather than a finally block"
  - "FakeLLM on_call hook signature is (purpose, call_dict); Plan 01-03 tests may reuse it"
  - "Subject tag format is '[TEST -> First Last <email>] '; the Hunter address is only ever in the subject, never in to"

requirements-completed: [LOG-01, SND-03, FND-01]

coverage:
  - id: D1
    description: "One domain flows scrape, extract, score, hunter, draft, send to status dry_run with run.json holding all six stages"
    requirement: LOG-01
    verification:
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_one_domain_runs_six_stages_to_dry_run"
        status: pass
  - id: D2
    description: "Dry run prints the exact owner-addressed payload and never calls the sender"
    requirement: SND-03
    verification:
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_dry_run_prints_exact_payload_and_never_calls_sender"
        status: pass
      - kind: unit
        ref: "tests/test_send.py (7 tests incl. signature has no `to`, live payload equals dry-run payload, 403 hint, missing id)"
        status: pass
  - id: D3
    description: "Partial trail survives a hard kill and a mid-run stage failure"
    requirement: LOG-01
    verification:
      - kind: integration
        ref: "tests/test_audit.py#test_hard_kill_leaves_partial_trail"
        status: pass
      - kind: unit
        ref: "tests/test_audit.py#test_per_stage_flush_snapshots, test_per_stage_failure_keeps_prior_stages"
        status: pass
  - id: D4
    description: "Canary key values never reach stdout, stderr, logs, run.json, .cache or repr(settings)"
    requirement: FND-01
    verification:
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_canary_never_leaks"
        status: pass
  - id: D5
    description: "Short pages never reach an LLM prompt; no usable page stops with insufficient_data; no named contact stops with no_contact"
    requirement: LOG-01
    verification:
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_short_page_stops_insufficient_data_before_llm, test_mixed_pages_short_page_excluded_from_extract_prompt, test_no_named_contact_stops_before_draft"
        status: pass
---

# Phase 1 Plan 2: Walking-skeleton tracer Summary

**One domain runs through six real stage functions (scrape, extract, score, hunter, draft, send) behind injectable LLM/Hunter/fetcher/sender seams, rewrites `out/<domain>/run.json` atomically before stage 1 and after every stage, and prints an owner-addressed dry-run Resend payload without calling Resend, all proven offline with fakes.**

## Accomplishments

- Task 1 (commit de6e7dd, type tracer): models, atomic cache, `RunStore`, guarded `send_email`, the six stages, `run_one`, the offline fakes (including the SDK-level `FakeModels`/`FakeGenaiClient` and builders Plan 01-03 needs) and 4 e2e tests. The Hunter fixture was captured live with the public `test-api-key` (`data.domain == piedpiper.com`, `emails[0]` Richard Hendricks, CEO; assertion passed, so the research fallback was not needed).
- Tracer feedback gate: auto mode off, `human_verify_mode` end-of-phase, `<verify>` is automated-only, so the verify command was re-run after the commit (4 passed) and the run expanded to Task 2 with no checkpoint. No `gate="blocking-human"` was set on the task.
- Task 2 (commit 4c19912): `test_audit.py` (5 tests, including the `os._exit(17)` subprocess hard-kill), `test_send.py` (7 tests), and `test_canary_never_leaks` plus `test_mixed_pages_short_page_excluded_from_extract_prompt` appended to the e2e file.
- Mutation check: temporarily removing `redact()` from the failure path made `test_canary_never_leaks` fail, then the file was restored, so the canary test is not vacuous.

## Task Commits

1. Task 1 (tracer): `de6e7dd` feat(01-02): tracer - one domain through six stages to an owner-addressed dry-run payload
2. Task 2: `4c19912` test(01-02): prove per-stage trail survives a kill, send guard holds, canary keys never leak

## Verification

- `.venv/bin/python -m pytest -q`: 55 passed (37 from 01-01, 18 new)
- `tests/test_audit.py -k per_stage`: 2 passed; `-k hard_kill`: 1 passed; `tests/test_send.py -k dry_run`: 2 passed; `tests/test_send.py`: 7 passed
- `.venv/bin/python scripts/check_secrets.py`: OK, no secrets found (41 files scanned)
- `inspect.signature(send_email)` has no `to` parameter
- `stages.py` contains `STAGES = [`, `def usable_pages(` and `build_extract_prompt(usable_pages(`; `skeleton.py` has `ctx.store.flush(` before the loop and inside it; `send.py` uses `.get_secret_value()`

## Deviations from Plan

### Auto-fixed Issues

None - no bug surfaced; the Task 2 tests passed against the Task 1 implementation without a change to `audit.py`, `send.py` or `skeleton.py`.

### Process notes

**1. [TDD cadence] Task 2 tests passed on first run**
- Task 2 is `tdd="true"`, but the behavior it tests was implemented in Task 1 (a plan-mandated order), so there was no assertion-level RED to observe. Instead of a RED commit, the canary test was mutation-checked (redaction removed, test failed, file restored) to show the tests can fail.

**2. [Acceptance alignment] Extract call site**
- `stage_extract` first built its prompt from a local `good = usable_pages(...)`; it was changed to the literal `build_extract_prompt(usable_pages(prev["scrape"].pages))` the plan and acceptance criteria name. Behavior is identical; the change landed in the Task 2 commit.

**3. [Detail] Tracer verify re-run, no checkpoint**
- Per the tracer feedback gate for non-auto interactive mode with an automated-only `<verify>`, the command was re-run rather than returning a human checkpoint.

## Authentication Gates

None.

## Known Stubs

None. `HunterContact.source == "fixture"` and the FakeHunter are test seams; the real `HunterClient`, `LLMClient` and `PageFetcher` arrive in Plan 01-03 behind the same Protocols, as planned.

## Threat Flags

None. No new network endpoints or trust-boundary surface beyond the plan's threat model; T-01-05 to T-01-09 are mitigated and each has a covering test (`test_send_email_signature_has_no_to_parameter`, `test_canary_never_leaks`, `test_mixed_pages_short_page_excluded_from_extract_prompt`, `test_hard_kill_leaves_partial_trail`, `check_secrets.py`).

## Self-Check: PASSED

- FOUND: src/outreach/models.py, cache.py, audit.py, send.py, stages.py, skeleton.py; tests/conftest.py, tests/fixtures/hunter_domain_search.json, tests/test_skeleton_e2e.py, tests/test_audit.py, tests/test_send.py
- FOUND commits: de6e7dd, 4c19912 (both ancestors of HEAD)
