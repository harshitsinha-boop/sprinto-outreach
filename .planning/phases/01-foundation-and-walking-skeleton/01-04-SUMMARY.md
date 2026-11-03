---
phase: 01-foundation-and-walking-skeleton
plan: 04
subsystem: live-proof
tags: [live-smoke, gemini, hunter, resend, skeleton, dry-run, secrets]
status: complete

requires:
  - phase: 01-foundation-and-walking-skeleton
    provides: "Plan 01-03 llm/fetch/hunter/smoke/cli, check_secrets.py, offline suite"
provides:
  - "Live proof that Gemini structured output (both models), Gemini function calling, Hunter account + Domain Search and a Resend self-send work with the owner's real keys"
  - "Live answer to Assumption A1: the function-response turn must use role=user (role=tool is rejected)"
  - "Warm .cache/ (LLM, pages, Hunter for linear.app) and out/linear.app/run.json so later phases start warm"
  - "Observed Hunter allowance: Free plan, 50 credits, reset 2026-12-03"
affects: [phase-2, phase-3, phase-4, phase-5, phase-6]

actuals:
  tokens: 1500
  tasks: 2
  commits: 1
plan_head_before: 1bea6373d0a47d9acdecbe48ee6f62e96d896c0a
plan_head_after: 0a004e51ac2170fd1aa473e609c1ba5305936edb

tech-stack:
  added: []
  patterns:
    - "Tool results go back to Gemini as a user-role Content carrying a function_response Part; the model turn is appended verbatim to keep thought signatures"

key-files:
  created: []
  modified:
    - src/outreach/smoke.py
    - tests/test_smoke.py

key-decisions:
  - "TOOL_RESULT_ROLE = \"user\": the live API returned 400 for role=tool and accepted role=user (Assumption A1); Phase 4's agent loop must send function responses as role=user"
  - "A2 (response_json_schema with Pydantic anyOf) and A4 (thinking_level) needed no flip: USE_RESPONSE_JSON_SCHEMA and SEND_THINKING_CONFIG stay True"
  - "HUNTER_MONTHLY_BUDGET in .env should be raised from 25 to 50 (the account allowance observed live); left unchanged because .env is owner-owned"

requirements-completed: [FND-04, FND-01, FND-02, SND-03]

coverage:
  - id: D1
    description: "Live smoke: gemini_structured on gemini-3.5-flash-lite and gemini-3.8-flash, gemini_tools, hunter_account, hunter (live, not from cache) and resend all PASS"
    requirement: FND-04
    verification:
      - kind: command
        ref: "out/smoke.log (6 PASS lines, no SKIPPED, no NOT LIVE)"
        status: pass
    human_judgment: false
  - id: D2
    description: "skeleton on the owner's SKELETON_DOMAIN prints the exact payload (from onboarding@resend.dev, to owner only, subject tagged with the Hunter contact, text) and never calls Resend; rerun makes llm_api_calls=0 and hunter_live_calls=0"
    requirement: SND-03
    verification:
      - kind: command
        ref: "out/skeleton.log (status=dry_run) and out/skeleton-rerun.log (llm_api_calls=0 llm_cache_hits=2 hunter_live_calls=0)"
        status: pass
    human_judgment: false
  - id: D3
    description: "With real keys in .env, no key value appears in tracked or untracked files, out/, .cache/ or git history; .env, out/ and .cache/ are untracked"
    requirement: FND-01
    verification:
      - kind: command
        ref: "scripts/check_secrets.py exit 0 (63 files scanned); git ls-files .env out .cache is empty"
        status: pass
    human_judgment: false
  - id: D4
    description: "The owner holds every key, the owner email, both model IDs and SKELETON_DOMAIN only in the local .env"
    requirement: FND-02
    verification:
      - kind: command
        ref: "load_settings() reports GEMINI_API_KEY, HUNTER_API_KEY, RESEND_API_KEY, OWNER_EMAIL, SKELETON_DOMAIN, both models, budget and from as set (.env); git check-ignore -q .env"
        status: pass
    human_judgment: false
  - id: D5
    description: "The smoke email actually arrives in the owner's inbox"
    requirement: FND-04
    human_judgment: true
    rationale: "Delivery is observable only in the owner's mailbox; Resend returning an id proves acceptance, not arrival. Owner-pending."
---

# Phase 1 Plan 4: Live proof Summary

**All four external services proven live with the owner's keys (one Gemini function-calling fallback to `role=user` applied), the skeleton prints the owner-addressed dry-run payload for linear.app with Resend untouched, a rerun makes zero LLM and Hunter calls, and the secret scan stays clean with real keys present.**

Duration: about 2 min of execution after the owner's `.env` was in place (start 2026-11-03T10:01:42Z). Tasks: 2 (Task 1 resolved by the orchestrator; Task 2 executed). Files changed: 2.

## Accomplishments

- Task 1 (checkpoint:human-action) was resolved before this run: the orchestrator wrote the gitignored, untracked `.env`. Verified read-only: `git check-ignore -q .env` passes, `git ls-files .env` is empty, `load_settings()` raises no ConfigError, and all nine variables report `set (.env)` by name only. No value was ever printed.
- Live smoke, run once (`out/smoke.log`), six PASS lines, nothing SKIPPED:
  - `PASS gemini_structured[gemini-3.5-flash-lite]` (company='Acme' is_saas=True)
  - `PASS gemini_structured[gemini-3.8-flash]` (company='Acme' is_saas=None)
  - `PASS gemini_tools` (`role=user`, args `['reason', 'url']`, a final text answer came back)
  - `PASS hunter_account` (plan=Free, remaining=50.0, reset_date=2026-12-03, WARNING remaining 50.0 != local budget 25)
  - `PASS hunter` (results=42, credits_used=1; live, no NOT LIVE flag)
  - `PASS resend id=01a1a0db-bce1-7892-80d2-f213f192aba1`
- Warm-up `skeleton` run (`out/skeleton.log`): banner says Resend will NOT be called; payload `from` onboarding@resend.dev, `to` = the owner only, subject `[TEST -> Conor Muirhead <conor@linear.app>] Linear's design momentum`; last line `status=dry_run run_record=out/linear.app/run.json llm_api_calls=2 llm_cache_hits=0 hunter_live_calls=0`.
- Zero-calls rerun (`out/skeleton-rerun.log`): last line `status=dry_run ... llm_api_calls=0 llm_cache_hits=2 hunter_live_calls=0`, contains `DRY RUN - Resend NOT called`.
- `scripts/check_secrets.py`: `OK: no secrets found (63 files scanned)` with the real keys present. `git status --short` shows no `.env`, `out/` or `.cache/` entries. `pytest -q`: 153 passed.

## Live facts for later phases

| Item | Value |
|------|-------|
| SKELETON_DOMAIN used | linear.app (no `no_contact` or `insufficient_data` stop seen; first domain worked) |
| Tool-result role | `user` (answer to Assumption A1: `role=tool` was rejected with a 400, `role=user` accepted) |
| A2 (`response_json_schema` with Pydantic `anyOf`) | accepted as is; both structured checks passed, `USE_RESPONSE_JSON_SCHEMA` stays True |
| A4 (`thinking_level`) | accepted as is, `SEND_THINKING_CONFIG` stays True (tools check sends `LOW` on gemini-3.8-flash) |
| Hunter plan / remaining / reset_date | Free / 50.0 (read before the search) / 2026-12-03 |
| Hunter credits_used | 1 (header present: the search cache and `.cache/hunter/_usage.json` record `credits_used: 1.0`, `live_calls: 1`, month 2026-11); about 49 credits remain |
| Hunter allowance vs brief | The account shows 50, not 25. Set `HUNTER_MONTHLY_BUDGET=50` in `.env` to resolve the STATE.md "25 vs 50" blocker. The smoke WARNING fires until then. |
| Resend message id | `01a1a0db-bce1-7892-80d2-f213f192aba1` (sent to the owner address only, subject tagged `[TEST]`/`[SMOKE]`) |
| Gemini rate limits | Not observed: no 429 occurred across 7 calls on either model; limits are visible only inside AI Studio |

## Task Commits

1. Task 1: no commit (human action, resolved by the orchestrator; `.env` is gitignored)
2. Task 2: `0a004e5` fix(01-04): apply live A1 fallback (the only code change; logs and caches are gitignored)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Offline tests asserted the old `role=tool` default**
- **Found during:** Task 2, step 2 (after flipping `TOOL_RESULT_ROLE` to `"user"`)
- **Issue:** `tests/test_smoke.py` hard-coded `role=tool` in two tests (`test_function_calling_passes_and_keeps_thought_signature`, `test_function_calling_falls_back_to_user_role_on_400`); the plan's `files_modified` lists only `smoke.py` and `llm.py`, but the plan also requires `pytest` to stay green after a flip.
- **Fix:** The passing-path test now expects `role=user`. The fallback test pins `TOOL_RESULT_ROLE` back to `"tool"` with `monkeypatch` and passes `role="tool"` explicitly, so the 400-to-user fallback path stays covered.
- **Files modified:** tests/test_smoke.py
- **Commit:** `0a004e5`

**Total deviations:** 1 auto-fixed (1 blocking). **Impact:** none on scope; the test edit only follows the documented one-line flip.

### Process notes

- The first full smoke run both discovered the A1 answer and passed: `check_function_calling` falls back to `user` automatically on a 400, so no re-run was needed. After the flip I did not re-run `smoke` (it would send a second email); the flip is only the default of the first attempt, and the passing `role=user` path is the one that ran live.
- The owner's mailbox was not checked (see below).

## Authentication Gates

None during this run (the first pasted Gemini key was invalid and was replaced before execution, handled by the orchestrator).

## Owner-pending human check

- Inbox arrival of the smoke email from onboarding@resend.dev (subject contains `[SMOKE] sprinto-outreach`, Resend id above) at the owner's address. Check Spam and Promotions too. Resend accepted the message (id returned), which proves acceptance, not delivery. Mark this check to be harvested at end of phase.

## Observations (not defects of this plan)

- The skeleton's drafted body for linear.app reads generic and does not mention Sprinto or compliance ("streamline user feedback directly into their product roadmap"). That is the Phase 1 skeleton's placeholder prompt; hook quality and Sprinto-fit framing belong to Phase 5, but the live output is evidence for that phase's prompt work.

## Known Stubs

None.

## Threat Flags

None. T-01-17 to T-01-20 held: no key value printed or logged, `check_secrets.py` exit 0 with real keys, the Resend call went through `send_email` (owner recipient only), one Hunter search and one Resend send in total.

## Self-Check: PASSED

- FOUND: src/outreach/smoke.py, tests/test_smoke.py, out/smoke.log, out/skeleton.log, out/skeleton-rerun.log, .cache/hunter/linear.app.json
- FOUND commit: 0a004e5 (ancestor of HEAD)
- Plan verify commands: smoke.log check, skeleton rerun check, `check_secrets.py` and `pytest -q` all exit 0
