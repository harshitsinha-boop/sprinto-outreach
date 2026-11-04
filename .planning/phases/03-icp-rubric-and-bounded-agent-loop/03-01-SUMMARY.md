---
phase: 03-icp-rubric-and-bounded-agent-loop
plan: 01
subsystem: qualification
tags: [icp-rubric, tomllib, pydantic, interval-scoring, sha256, calibration]

requires:
  - phase: 02-runner-cli-and-real-scrape-extract
    provides: quote-validated CompanyProfile, usable-page gate, batch runner with outcome vocabulary
provides:
  - config/icp.toml rubric (icp.1) with gates, eight weighted signals, two penalties and thresholds 60 and 45
  - outreach.qualify pure interval scorer, verdict rules, breakdown renderer and rubric loader with sha256
  - Qualification contracts stored in run.json (ok stage output, or `result` inside a stopped stage)
  - stage_qualify replacing the placeholder score stage; zero Hunter calls for non-qualified companies
  - rubric version and sha256 in every run.json, summary.json and the printed summary
affects: [03-02 bounded research loop, phase 4 hunter, phase 6 decision log]

actuals:
  tokens: 20400
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Rubric as data: TOML parsed with stdlib tomllib, exact bytes hashed with sha256, validated by strict pydantic models"
    - "Interval scoring: unknown signal = 0 in score_min, full weight in score_max; penalties lower both"
    - "StopStage carries a typed output stored under result in the stopped stage"

key-files:
  created:
    - config/icp.toml
    - src/outreach/qualify.py
    - tests/test_qualify.py
    - tests/fixtures/icp_calibration.json
  modified:
    - src/outreach/models.py
    - src/outreach/stages.py
    - src/outreach/skeleton.py
    - src/outreach/runner.py
    - tests/conftest.py
    - tests/test_skeleton_e2e.py
    - tests/test_audit.py

key-decisions:
  - "Rubric file format and Qualification shape are the stable contract for plan 03-02 and Phase 6 (costly to change)"
  - "year_recency points use keys age_le_1, age_2, older and text_keyword uses points.match, so no number lives in Python"
  - "Rubric models forbid extra keys, so a typo in config/icp.toml is refused at load instead of silently ignored"
  - "Evidence lines in the breakdown are indented eight spaces under their four-space signal line"

requirements-completed: [QUA-01, QUA-02, QUA-03, QUA-05]

coverage:
  - id: D1
    description: "ICP rubric (gates, weighted signals summing to 100, penalties, thresholds 60 and 45, reference year) is data in config/icp.toml, validated and hashed at load"
    requirement: QUA-01
    verification:
      - kind: unit
        ref: "tests/test_qualify.py#test_rubric_validation_errors"
        status: pass
      - kind: unit
        ref: "tests/test_qualify.py#test_repo_rubric_thresholds_are_pinned"
        status: pass
    human_judgment: false
  - id: D2
    description: "Rubric sha256 and version appear in run.json, the qualify output, summary.json and the second summary line"
    requirement: QUA-01
    verification:
      - kind: integration
        ref: "tests/test_qualify.py#test_default_company_qualifies_through_run_one_with_rubric_hash"
        status: pass
      - kind: integration
        ref: "tests/test_qualify.py#test_summary_carries_rubric_identity"
        status: pass
      - kind: unit
        ref: "tests/test_qualify.py#test_rubric_hash_changes_with_file_bytes"
        status: pass
    human_judgment: false
  - id: D3
    description: "Pure deterministic scorer: no model-produced number, identical result for repeated or reordered evidence"
    requirement: QUA-02
    verification:
      - kind: unit
        ref: "tests/test_qualify.py#test_score_is_deterministic_and_order_independent"
        status: pass
      - kind: unit
        ref: "tests/test_qualify.py#test_keyword_groups_match_whole_words"
        status: pass
    human_judgment: false
  - id: D4
    description: "score_min/score_max interval with qualified, disqualified and loop/insufficient_data verdict rules, proven on a written 8-case calibration set"
    requirement: QUA-03
    verification:
      - kind: unit
        ref: "tests/test_qualify.py#test_calibration_cases"
        status: pass
      - kind: unit
        ref: "tests/test_qualify.py#test_unknown_counts_zero_in_min_and_full_in_max"
        status: pass
      - kind: unit
        ref: "tests/test_qualify.py#test_penalty_lowers_both_bounds_with_floor_zero"
        status: pass
    human_judgment: false
  - id: D5
    description: "Disqualified and insufficient-data companies stop at qualify, show their full breakdown under the progress line and make zero Hunter calls"
    requirement: QUA-05
    verification:
      - kind: integration
        ref: "tests/test_qualify.py#test_consumer_company_is_disqualified_with_zero_hunter_calls"
        status: pass
      - kind: integration
        ref: "tests/test_qualify.py#test_batch_prints_breakdowns_and_spends_hunter_only_on_qualified"
        status: pass
      - kind: unit
        ref: "tests/test_qualify.py#test_render_breakdown_strips_control_characters"
        status: pass
    human_judgment: false
  - id: D6
    description: "Whether the written rubric weights and thresholds are a defensible Sprinto ICP when run on the real demo domains with live Gemini"
    verification: []
    human_judgment: true
    rationale: "Weights are uncalibrated hypotheses; defensibility on real companies is a judgment no offline test asserts. Live demo-domain run is owner-pending"

duration: 7min
completed: 2026-11-04
status: complete
plan_head_before: 8def8e03c1397beb8cff5c63083e6a9fd5f5b60e
plan_head_after: 8be7796db495b0e6d7bccbef3dcaa56744019a9b
---

# Phase 3 Plan 1: ICP Rubric Qualification Summary

**TOML ICP rubric hashed into every run, scored by a pure Python min/max interval scorer, with disqualified and insufficient-data companies stopped before Hunter and their full breakdown printed**

## Performance

- **Duration:** about 7 min of wall clock (clock-derived from the phase plan commit to final task commit)
- **Completed:** 2026-11-04T04:20Z
- **Tasks:** 3 (tracer, TDD calibration, TDD visible verdicts)
- **Files modified:** 11 (4 created, 7 modified), 2001 insertions

## Accomplishments

- `config/icp.toml` (icp.1) holds the whole policy: two gates, eight signals (weights 10/10/10/25/15/15/10/5 summing to 100), two penalties, thresholds qualify_min 60 and reject_max 45, reference year 2026. Nothing about weights or thresholds is in Python.
- `outreach.qualify.load_rubric` reads the file bytes once, hashes exactly those bytes and refuses a malformed rubric by name (bad TOML or schema, weights not 100, signal maximum differing from weight, qualify_min not above reject_max, duplicate ids, non-page kind).
- `score_profile` is pure and order independent. Every signal is known or unknown; score_min counts unknown as 0 and score_max counts it at full weight, penalties lowering both. `initial_verdict` and `final_verdict` implement qualified / disqualified / loop and insufficient_data.
- `stage_qualify` replaced the placeholder four-signal score. Anything but qualified raises `StopStage` carrying the typed Qualification, stored under `result` in the stopped stage of run.json. Hunter is never reached.
- Rubric version and sha256 are written into `RunRecord.rubric` before stage 1 (also for domains that stop at scrape), into each Qualification, `out/_batch/summary.json`, and line 2 of the printed summary (`rubric icp.1 sha256=<12 hex>`).
- `render_breakdown` prints every gate, signal (points, status, basis, quote and url) and penalty under each domain's progress line, stripping control characters from every page-derived string.
- A calibration set of 8 cases written before any demo domain was scored (3 fits, 3 rejects, 2 gray band) passed on the first run with the expected verdicts and intervals; no expected number was edited.

## Task Commits

1. **Task 1: Tracer, rubric file, hashed loader, interval scorer and qualify stage in run_one** - `084c994` (feat)
2. **Task 2: Calibration set, determinism and rubric validation** - `0ab44d4` (test)
3. **Task 3: Printed breakdown, rubric line in summary, batch zero-Hunter guarantee** - `8be7796` (feat)

**Plan metadata:** the docs commit following this SUMMARY (docs: complete plan)

The tracer gate was satisfied by re-running the tracer verify (full suite plus the two tracer tests) before expansion; it passed, so tasks 2 and 3 proceeded.

## Files Created/Modified

- `config/icp.toml` - the rubric
- `src/outreach/qualify.py` - rubric models and loader, scorer, verdicts, `render_breakdown`, `qualification_from_record`
- `src/outreach/models.py` - SignalScore, GateResult, PenaltyHit, RubricScore, Qualification; `RunRecord.rubric`, `BatchSummary.rubric`
- `src/outreach/stages.py` - `stage_qualify`, `StopStage(output=)`, placeholder scorer removed
- `src/outreach/skeleton.py` - `Context.rubric` (defaulted), rubric identity in run_one, stopped-stage `result`
- `src/outreach/runner.py` - breakdown under each progress line, rubric in summary and `render_summary`
- `tests/test_qualify.py` - 40 tests; `tests/fixtures/icp_calibration.json` - 8 calibration cases
- `tests/conftest.py`, `tests/test_skeleton_e2e.py`, `tests/test_audit.py` - see deviations

## Decisions Made

- year_recency and text_keyword read their points from the rubric (`age_le_1`/`age_2`/`older`, `match`) so every number stays in the data file.
- Rubric models use `extra="forbid"`: a misspelled key in icp.toml fails the load rather than being ignored.
- `count` follows the plan literally (list length, no de-duplication by customer name). See Issues.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Canned extract response cited example.com for every domain**
- **Found during:** Task 1 (full-suite run after the stage swap)
- **Issue:** 8 existing multi-domain tests in test_runner.py and test_cli_run.py (domains such as example.org, a.example) failed. The conftest default extract response cites `https://example.com/`; for any other domain Phase 2's validator correctly drops every item (its source page was never given), leaving an empty profile that the real rubric now scores insufficient_data. The old placeholder score hid this because it only needed presence. The plan said existing dry_run tests must keep passing and named only the stage rename in two files.
- **Fix:** `FakeLLM.generate_structured` now retargets the canned extract response's `https://example.com/` to the first `<page url=...>` in the prompt when example.com is not one of the given pages. No production code or test assertion changed.
- **Files modified:** tests/conftest.py
- **Verification:** full suite green (281 then 319 tests); the extract and injection tests that rely on example.com are untouched because the retarget only fires when example.com is absent from the prompt.
- **Committed in:** 084c994 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking, test infrastructure only)
**Impact on plan:** No scope creep; it keeps the plan's own constraint (existing tests pass) true.

## Issues Encountered

- Residual prompt-injection surface (T-03-01 note for the verifier): `enterprise_customers` scores by list length, so a model that repeats one named customer three times would earn the 15-point tier. Phase 2's validator checks that each quote is on the page, not that names are distinct. The damage is capped at that signal's weight and the evidence is printed, but de-duplicating by normalised customer name in the scorer is a cheap hardening to consider with the rubric version bump.
- The default conftest scrape gives only the home page as usable (duplicate texts are demoted), which is why the default company's funding_stage and recent_funding stay unknown (score 80..100). Plan 03-02's research loop will be what resolves such unknowns.

## Known Stubs

None. No placeholder values flow to output; `.planning/WINDOWS.md` entries not needed.

## Owner-Pending Checks

- Live run of the rubric on the real demo domains with real Gemini (does the breakdown read as defensible, are 60/45 sensible on real pages). Not run, by instruction: no live network or key use in this execution. Phase 3 verification should schedule it with the owner.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 03-02 can add the bounded research loop: `qualify(...)` already records `initial_verdict` and `initial_score` separately from the final `score`, each signal rule has `target_kinds` for candidate URLs, and `StopStage(output=)` plus `qualification_from_record` carry whatever it adds. Suite: 319 tests green, `scripts/check_secrets.py` clean.

## Self-Check: PASSED

Created files exist (config/icp.toml, src/outreach/qualify.py, tests/test_qualify.py, tests/fixtures/icp_calibration.json); commits 084c994, 0ab44d4 and 8be7796 are ancestors of HEAD; full suite 319 passed; secrets scan clean; Gemini SDK imported only in llm.py and smoke.py.

---
*Phase: 03-icp-rubric-and-bounded-agent-loop*
*Completed: 2026-11-04*
