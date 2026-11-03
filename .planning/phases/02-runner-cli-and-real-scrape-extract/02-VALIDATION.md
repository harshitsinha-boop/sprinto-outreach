---
phase: "02"
slug: "runner-cli-and-real-scrape-extract"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-11-03"
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.2.0 (plus httpx.MockTransport and the offline fakes in `tests/conftest.py`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `pythonpath = ["src"]`, `testpaths = ["tests"]`) |
| **Quick run command** | `.venv/bin/python -m pytest -q -x` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~5 seconds (153 tests at HEAD run in about 3 s; no test sleeps or touches the network) |

All tests are offline. From Plan 02-02 on, an autouse conftest fixture replaces the system DNS resolver with a fixed public address and sets the politeness interval to zero, so no test performs a real lookup or sleeps. The only live check in this phase is optional, runs through the CLI, and is listed under Manual-Only Verifications.

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -q -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q` and `.venv/bin/python scripts/check_secrets.py`
- **Before `/gsd-verify-work`:** Full suite must be green and the secret scan clean
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | RUN-01, RUN-04 | T-02-01 / T-02-04 | Default run is a dry run; every domain gets a row from the closed outcome set | e2e (CLI tracer) + unit | `.venv/bin/python -m pytest tests/test_cli_run.py::test_run_cli_domains_file_prints_summary_table tests/test_runner.py -q` | ❌ created by task (TDD) | ⬜ pending |
| 02-01-02 | 01 | 1 | RUN-02, RUN-03, RUN-04 | T-02-01 / T-02-02 / T-02-03 / T-02-05 | Only `--send` calls Resend; systemic errors abort with a redacted reason; IP literals and localhost rejected; 25-domain cap | unit + CLI | `.venv/bin/python -m pytest tests/test_runner.py tests/test_cli_run.py -q` | ❌ created by task (TDD) | ⬜ pending |
| 02-02-01 | 02 | 2 | SCR-01, SCR-02 | T-02-08 / T-02-09 / T-02-10 / T-02-11 / T-02-12 | No request to non-public addresses or off-site redirect targets; robots.txt honoured; hidden text stripped; thin or blocked pages unavailable | unit (MockTransport) | `.venv/bin/python -m pytest tests/test_fetch.py -q` | ✅ exists (extended) | ⬜ pending |
| 02-02-02 | 02 | 2 | SCR-01, SCR-02, RUN-02 | T-02-10 / T-02-12 / T-02-14 | Six page kinds within caps; blocked pages never reach the LLM through `run_batch`; dead domain stays failed | unit + batch e2e | `.venv/bin/python -m pytest tests/test_scrape.py tests/test_skeleton_e2e.py -q` | ❌ created by task (TDD) | ⬜ pending |
| 02-03-01 | 03 | 3 | EXT-01, EXT-02 | T-02-16 / T-02-18 | Only quotes found verbatim on the cited page are kept; unknown facts stay null; every drop logged | unit + run_one e2e | `.venv/bin/python -m pytest tests/test_extract.py -q` | ❌ created by task (TDD) | ⬜ pending |
| 02-03-02 | 03 | 3 | EXT-02, EXT-03 | T-02-15 / T-02-17 / T-02-19 | Page tags escaped, instruction lines removed, no tools, planted instructions leave the validated profile unchanged | unit + run_one e2e | `.venv/bin/python -m pytest tests/test_extract.py tests/test_llm.py tests/test_skeleton_e2e.py -q` | ❌ created by task (TDD) | ⬜ pending |

Every task also runs `.venv/bin/python -m pytest -q` (whole suite) as a second `<automated>` gate, and each plan's last task runs `.venv/bin/python scripts/check_secrets.py`.

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Requirement Coverage

| Requirement | Plan / Task | Proving tests |
|-------------|-------------|---------------|
| RUN-01 | 02-01 T1, T2 | `test_run_cli_domains_file_prints_summary_table`, `test_run_cli_has_no_interactive_prompt` |
| RUN-02 | 02-01 T2, 02-02 T2 | `test_unreachable_domain_is_failed_and_batch_continues`, `test_stage_exception_is_failed_and_batch_continues`, `test_systemic_error_aborts_batch`, `test_dead_domain_is_failed_through_run_batch` |
| RUN-03 | 02-01 T2 | `test_run_cli_defaults_to_dry_run_and_never_sends`, `test_run_cli_send_flag_calls_sender_once_per_completed_domain` |
| RUN-04 | 02-01 T1, T2 | `test_render_summary_lists_every_domain_and_all_seven_counts`, `test_outcome_for_maps_all_seven_outcomes`, `test_rejected_lines_keep_file_order_in_summary` |
| SCR-01 | 02-02 T1, T2 | `test_robots_disallowed_path_is_unavailable_without_request`, `test_fetch_deadline_stops_slow_body`, `test_legacy_unversioned_cache_entry_is_ignored`, `test_scrape_fetches_home_and_five_page_kinds` |
| SCR-02 | 02-02 T1, T2 | `test_challenge_page_is_unavailable_blocked`, `test_thin_page_is_unavailable_too_short`, `test_thin_page_chars_is_extracted_length_and_text_none`, `test_blocked_page_never_reaches_llm_through_run_batch` |
| EXT-01 | 02-03 T1 | `test_company_profile_schema_requires_every_field_and_has_no_defaults`, `test_unknown_facts_stay_null_through_run_one` |
| EXT-02 | 02-03 T1, T2 | `test_quote_on_other_page_is_dropped`, `test_scalar_with_bad_quote_becomes_null`, `test_quote_from_removed_line_is_instruction_like_text` |
| EXT-03 | 02-03 T2 | `test_page_closing_tag_breakout_is_escaped`, `test_extract_call_passes_no_tools`, `test_ordinary_copy_is_not_flagged_as_instructions`, `test_planted_instruction_lines_are_flagged`, `test_injected_page_yields_same_validated_profile_as_clean_page`, `test_planted_instructions_do_not_change_extracted_profile` |

Cross-plan guard: from Plan 02-02 on, every test-double fetcher in `tests/` must accept `fetch(url, site=None)`; checked by `test_test_fetchers_accept_site_keyword` (02-01) and the `def fetch(` grep gate in 02-02 Task 2 (baseline at HEAD: 1 stub lacks `site`).

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements: pytest, `httpx.MockTransport`, respx and the conftest fakes are installed and in use. New test files (`tests/test_runner.py`, `tests/test_cli_run.py`, `tests/test_scrape.py`, `tests/test_extract.py`) are written first inside their own `tdd="true"` or tracer tasks, so no task carries a MISSING sentinel.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live batch on one real site and one dead domain (optional) | RUN-01, RUN-02, SCR-01, EXT-02 | Needs the owner's live Gemini key and network access; the offline suite already proves the behavior | Plan 02-03 Task 2 `<human-check>`: from the repo root, never opening `.env`, write `out/live-domains.txt` with `linear.app` and `no-such-host-sprinto-check.invalid`, run `.venv/bin/python -m outreach run out/live-domains.txt`; expect linear.app no_contact with verbatim quotes in run.json, the `.invalid` domain failed (DomainUnreachable), exit 0; then `.venv/bin/python scripts/check_secrets.py` exits 0. Costs at most one Gemini call, no Hunter credit, no Resend send |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
