---
phase: "1"
slug: foundation-and-walking-skeleton
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-11-03"
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.2.0 (respx 0.23.1 for httpx; `resend.default_http_client` fake for Resend) |
| **Config file** | none yet — Wave 0 creates `pyproject.toml` with `[tool.pytest.ini_options] pythonpath = ["src"]`, `testpaths = ["tests"]` |
| **Quick run command** | `.venv/bin/python -m pytest -q -x` (all offline) |
| **Full suite command** | `.venv/bin/python -m pytest -q && .venv/bin/python scripts/check_secrets.py` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -q -x tests/<touched module>`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q && .venv/bin/python scripts/check_secrets.py`
- **Before `/gsd-verify-work`:** Full suite green, secret check clean, live `.venv/bin/python -m outreach smoke` reporting six PASS lines (structured on both models, tools, hunter_account, hunter, resend), the smoke email in the owner inbox, and a skeleton dry-run payload on screen
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Plan / Task | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|-------------|----------|-----------|-------------------|-------------|--------|
| 01-01 T1 | FND-01 | `.gitignore` + `.env.example` are the first commit, alone; ignore rules hold | git | `git diff-tree` / `git check-ignore` gate in 01-01-PLAN.md Task 1 | n/a | ⬜ pending |
| 01-01 T3 | FND-01 | `.gitignore` ignores `.env`, `.cache/`, `out/`, `*.egg-info/` but not `.env.example` | unit | `.venv/bin/python -m pytest tests/test_hygiene.py::test_gitignore_rules -x` | ❌ W0 | ⬜ pending |
| 01-01 T3 | FND-01 | `.env.example` has empty secret values and no recipient-variable key | unit | `.venv/bin/python -m pytest tests/test_hygiene.py::test_env_example_shape -x` | ❌ W0 | ⬜ pending |
| 01-01 T3 | FND-01 | Scanner catches planted values (tracked, untracked, `out/`, history) and key shapes; clean repo passes | script/unit | `.venv/bin/python -m pytest tests/test_hygiene.py -k check_secrets -x` and `.venv/bin/python scripts/check_secrets.py` | ❌ W0 | ⬜ pending |
| 01-01 T3 | FND-02 | Settings load from env and `.env`; missing key names the variable not the value; repr masks | unit | `.venv/bin/python -m pytest tests/test_config.py -x` | ❌ W0 | ⬜ pending |
| 01-02 T1 | SND-03, LOG-01 | Tracer: 6 ordered stages, dry-run payload printed, no sender call, run.json on disk | e2e | `.venv/bin/python -m pytest tests/test_skeleton_e2e.py -x` | ❌ W0 | ⬜ pending |
| 01-02 T2 | FND-01 | Canary keys never leak to output, logs, run.json, caches or repr | unit | `.venv/bin/python -m pytest tests/test_skeleton_e2e.py::test_canary_never_leaks -x` | ❌ W0 | ⬜ pending |
| 01-02 T2 | SND-03, LOG-01 | Mixed pages: a page under MIN_PAGE_CHARS is absent from the extract prompt and the run continues on the usable page | e2e | `.venv/bin/python -m pytest tests/test_skeleton_e2e.py::test_mixed_pages_short_page_excluded_from_extract_prompt -x` | ❌ W0 | ⬜ pending |
| 01-02 T2 | LOG-01 | `run.json` written after each stage; stage failure keeps prior stages | unit | `.venv/bin/python -m pytest tests/test_audit.py -k per_stage -x` | ❌ W0 | ⬜ pending |
| 01-02 T2 | LOG-01 | Hard kill leaves valid JSON with earlier stages | subprocess | `.venv/bin/python -m pytest tests/test_audit.py -k hard_kill -x` | ❌ W0 | ⬜ pending |
| 01-02 T2 | SND-03 | Dry-run prints payload, no Resend call, `to` is the owner, subject shows intended recipient | unit | `.venv/bin/python -m pytest tests/test_send.py -k dry_run -x` | ❌ W0 | ⬜ pending |
| 01-02 T2 | SND-03 | `send_email` has no `to` parameter; 403 owner-only error mapped; missing id errors | unit | `.venv/bin/python -m pytest tests/test_send.py -x` | ❌ W0 | ⬜ pending |
| 01-03 T1 | FND-03 | Retry on 429/503, no retry on 400, auth errors abort, retryDelay honoured | unit | `.venv/bin/python -m pytest tests/test_llm.py -k retry -x` | ❌ W0 | ⬜ pending |
| 01-03 T1 | FND-03 | One repair retry on invalid output; failed output never cached | unit | `.venv/bin/python -m pytest tests/test_llm.py -k repair -x` | ❌ W0 | ⬜ pending |
| 01-03 T1 | FND-03 | Second identical call makes zero API calls; key changes with model/prompt/schema | unit | `.venv/bin/python -m pytest tests/test_llm.py -k cache -x` | ❌ W0 | ⬜ pending |
| 01-03 T1 | FND-03 | No sampling params set; SDK retries disabled; no `default` in schema | unit | `.venv/bin/python -m pytest tests/test_llm.py -k config -x` | ❌ W0 | ⬜ pending |
| 01-03 T1 | FND-03 | Wire contract: key header, mime type, thought signature and function response history | contract | `.venv/bin/python -m pytest tests/test_llm.py -k wire -x` | ❌ W0 | ⬜ pending |
| 01-03 T2 | FND-03 | Page cache: second fetch makes no HTTP; errors not cached; size and text caps | unit | `.venv/bin/python -m pytest tests/test_fetch.py -x` | ❌ W0 | ⬜ pending |
| 01-03 T2 | FND-04 | Hunter: miss costs 1 live call, hit costs 0, budget blocks, errors not cached, zero results cached | unit | `.venv/bin/python -m pytest tests/test_hunter.py -x` | ❌ W0 | ⬜ pending |
| 01-03 T2 | FND-04 | FixtureHunter returns its contact only for piedpiper.com; other domains get zero emails | unit | `.venv/bin/python -m pytest tests/test_hunter.py::test_fixture_hunter_returns_contact_only_for_fixture_domain -x` | ❌ W0 | ⬜ pending |
| 01-03 T3 | FND-04 | Each smoke check passes on a good fake and fails cleanly on a misbehaving one | unit | `.venv/bin/python -m pytest tests/test_smoke.py -x` | ❌ W0 | ⬜ pending |
| 01-03 T2 | FND-04 | `account()` keeps a real 0 as 0 (explicit None checks, never truthiness) | unit | `.venv/bin/python -m pytest tests/test_hunter.py::test_account_zero_credits_returns_zero -x` | ❌ W0 | ⬜ pending |
| 01-03 T3 | FND-04 | First cheap-check FAIL stops smoke; later checks SKIPPED; no Hunter search, no Resend send (incl. a real HunterClient with 0 credits) | unit | `.venv/bin/python -m pytest tests/test_smoke.py -k skips -x` | ❌ W0 | ⬜ pending |
| 01-03 T3 | FND-04 | Smoke hunter check FAILs as NOT LIVE when served from cache | unit | `.venv/bin/python -m pytest tests/test_smoke.py::test_hunter_cache_hit_fails_not_live -x` | ❌ W0 | ⬜ pending |
| 01-03 T3 | Criteria 3 and 5 | Real clients: rerun makes zero Gemini, page and Hunter calls; CLI prints payload; fixture on a real domain stops no_contact | e2e | `.venv/bin/python -m pytest tests/test_skeleton_e2e.py -x` | ❌ W0 | ⬜ pending |
| 01-04 T2 | FND-04, FND-01, SND-03 | Live smoke six PASS lines; separate warm-up then free rerun; scanner clean with real keys | live | `out/smoke.log` PASS gate, warm-up `out/skeleton.log` then `.venv/bin/python -m outreach skeleton`, `.venv/bin/python scripts/check_secrets.py` | n/a (needs `.env`) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` with pytest config and pinned deps; venv and install (after the package-legitimacy checkpoint)
- [ ] `tests/conftest.py` — `FakeModels`, `FakeLLM`, `FakeHunter`, `FakeSender`, `fake_sleep`, canary env, tmp cache dirs
- [ ] `tests/fixtures/hunter_domain_search.json` — captured with Hunter's public `test-api-key`
- [ ] `tests/test_hygiene.py`, `test_config.py`, `test_llm.py`, `test_fetch.py`, `test_hunter.py`, `test_send.py`, `test_audit.py`, `test_smoke.py`, `test_skeleton_e2e.py`
- [ ] `scripts/check_secrets.py`

Each test file is created by the plan task that first needs it (see the map above); no task's `<automated>` command depends on a file a later task creates.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Gemini structured output on both models, function-calling round trip, one Hunter call, one Resend send | FND-04 | No API keys exist in the build environment | Owner creates `.env` from `.env.example` (Plan 01-04 Task 1, including `SKELETON_DOMAIN`), then Claude runs `.venv/bin/python -m outreach smoke` |
| Resend email arrives in the owner inbox | FND-04 | Delivery is only visible in the owner's mailbox | `<human-check>` in Plan 01-04 Task 2: check inbox and spam after the smoke run |
| Skeleton dry-run on the chosen domain | SND-03 | Needs live keys and a chosen domain | `.venv/bin/python -m outreach skeleton` (defaults to `SKELETON_DOMAIN`; `--domain <D>` overrides) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
