---
phase: "03"
slug: "icp-rubric-and-bounded-agent-loop"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-11-04"
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.2.0, plus respx 0.23, httpx.MockTransport and the offline fakes in `tests/conftest.py` (FakeLLM with tool sessions from Plan 03-02, FakeFetcher, FakeHunter, FakeGenaiClient) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `pythonpath = ["src"]`, `testpaths = ["tests"]`) |
| **Quick run command** | `.venv/bin/python -m pytest -q -x` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~8 seconds (279 tests at HEAD run in about 6.5 s; no test sleeps or touches the network) |

All tests are offline. The conftest autouse fixture replaces DNS resolution and the politeness sleep. Scoring tests use the repo rubric `config/icp.toml`, or tmp copies of it for the validation-error and hash cases. Loop tests script the model's function calls through FakeLLM's `tool_script`, or through FakeGenaiClient queues for the wrapper and re-run tests. No test reads `.env` or prints a key.

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -q -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q` and `.venv/bin/python scripts/check_secrets.py`
- **Before `/gsd-verify-work`:** The full suite must be green and the secret scan clean
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | QUA-01, QUA-02, QUA-03, QUA-05 | T-03-01 / T-03-02 / T-03-03 | Score computed in Python from validated evidence; rubric sha256 in run.json; a consumer company stops at qualify with zero Hunter calls | e2e (run_one tracer) | `.venv/bin/python -m pytest tests/test_qualify.py -q` | ❌ created by task | ⬜ pending |
| 03-01-02 | 01 | 1 | QUA-02, QUA-03, QUA-01 | T-03-05 / T-03-07 | Calibration verdicts fixed before demo scores; deterministic, order-independent scoring; malformed rubric refused at load; thresholds pinned at 60/45 | unit (TDD, calibration fixture) | `.venv/bin/python -m pytest tests/test_qualify.py -q` | ❌ created by task | ⬜ pending |
| 03-01-03 | 01 | 1 | QUA-05, QUA-01 | T-03-03 / T-03-04 / T-03-06 | Full breakdown printed under each domain, control characters stripped; only qualified domains reach Hunter in a mixed batch; rubric line in the summary | unit + batch e2e | `.venv/bin/python -m pytest tests/test_qualify.py tests/test_runner.py tests/test_cli_run.py -q` | ✅ exists (extended) | ⬜ pending |
| 03-02-01 | 02 | 2 | QUA-04 | T-03-08 / T-03-09 / T-03-11 | One model-chosen, reason-logged, same-domain candidate fetch, re-extracted with quote validation and re-scored in Python, takes a gray-band company to qualified | e2e (run_one tracer) | `.venv/bin/python -m pytest tests/test_agent.py -q` | ❌ created by task | ⬜ pending |
| 03-02-02 | 02 | 2 | QUA-04, QUA-05 | T-03-08 / T-03-09 / T-03-10 / T-03-12 | Off-domain, metadata-IP and non-candidate URLs refused and never fetched; at most 3 turns and 3 fetches; every stop reason reachable; no page text reaches the loop model; unresolved company makes zero Hunter calls | unit + run_one e2e (TDD) | `.venv/bin/python -m pytest tests/test_agent.py tests/test_qualify.py -q` | ✅ exists (extended) | ⬜ pending |
| 03-02-03 | 02 | 2 | QUA-04 | T-03-10 / T-03-13 | Tools and response_json_schema never in one request; function-response role from smoke.TOOL_RESULT_ROLE; thought signatures verbatim; AFC disabled and checked; cached turns make a re-run free | unit (respx wire, FakeGenaiClient) + re-run e2e | `.venv/bin/python -m pytest tests/test_llm.py tests/test_agent.py -q` | ✅ exists (extended) | ⬜ pending |

Every task also runs `.venv/bin/python -m pytest -q` (the whole suite) as a second `<automated>` gate, and each plan's last task runs `.venv/bin/python scripts/check_secrets.py`.

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Requirement Coverage

| Requirement | Plan / Task | Proving tests |
|-------------|-------------|---------------|
| QUA-01 rubric as data, hash logged with every run | 03-01 T1, T2, T3 | `test_default_company_qualifies_through_run_one_with_rubric_hash`, `test_rubric_hash_changes_with_file_bytes`, `test_rubric_validation_errors`, `test_summary_carries_rubric_identity` |
| QUA-02 LLM extracts, Python scores, same evidence gives the same score | 03-01 T1, T2 | `test_score_is_deterministic_and_order_independent`, `test_calibration_cases` |
| QUA-03 min/max interval drives qualify, reject or loop | 03-01 T2, 03-02 T1 | `test_calibration_cases` (fits, rejects, gray band), `test_unknown_counts_zero_in_min_and_full_in_max`, `test_gray_band_company_researches_one_page_and_qualifies` |
| QUA-04 bounded loop: at most 3 iterations, same-domain only, reason per fetch, stop_reason enum | 03-02 T1, T2, T3 | `test_loop_stops_at_three_iterations`, `test_off_domain_and_metadata_urls_are_refused_and_never_fetched`, `test_same_site_url_not_offered_is_refused`, `test_missing_reason_is_refused`, `test_tool_config_never_mixes_schema_and_tools`, `test_tool_session_wire_role_user_and_verbatim_signature` |
| QUA-05 disqualified or insufficient-data shows breakdown and costs no Hunter credit | 03-01 T1, T3, 03-02 T2 | `test_consumer_company_is_disqualified_with_zero_hunter_calls`, `test_batch_prints_breakdowns_and_spends_hunter_only_on_qualified`, `test_unresolved_loop_company_makes_zero_hunter_calls` |

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. pytest, respx and the conftest fakes are in place from Phases 1 and 2. Each task writes its own tests first (TDD or tracer), and Plan 03-02 Task 1 extends FakeLLM with tool sessions before any loop test depends on it.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The live Gemini function-calling loop on a real site (role "user", the real model choosing a candidate with a reason) and a free second run | QUA-04 | Needs the owner's live Gemini key and network access; the offline suite proves the same shapes against recorded responses | Optional, at most once: Plan 03-02 Task 3 `<human-check>` (a dry run with the fixture Hunter, a second run, then `scripts/check_secrets.py`) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
