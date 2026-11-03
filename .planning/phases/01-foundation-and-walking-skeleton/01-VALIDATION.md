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
| **Quick run command** | `pytest -q -x` (all offline) |
| **Full suite command** | `pytest -q && python scripts/check_secrets.py` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest -q -x tests/<touched module>`
- **After every plan wave:** Run `pytest -q && python scripts/check_secrets.py`
- **Before `/gsd-verify-work`:** Full suite green, secret check clean, live `python -m outreach smoke` reporting four PASS, and a skeleton dry-run payload on screen
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| FND-01 | `.gitignore` ignores `.env`, `.cache/`, `out/` but not `.env.example` | unit | `pytest tests/test_hygiene.py::test_gitignore_rules -x` | ❌ W0 | ⬜ pending |
| FND-01 | `.env.example` has empty secret values | unit | `pytest tests/test_hygiene.py::test_env_example_shape -x` | ❌ W0 | ⬜ pending |
| FND-01 | `.env` never tracked or in history; canary keys never leak | script/unit | `python scripts/check_secrets.py` and `pytest tests/test_hygiene.py::test_canary_never_leaks -x` | ❌ W0 | ⬜ pending |
| FND-02 | Settings load from env and `.env`; missing key names the variable not the value; repr masks | unit | `pytest tests/test_config.py -x` | ❌ W0 | ⬜ pending |
| FND-03 | Retry on 429/503, no retry on 400, auth errors abort, retryDelay honoured | unit | `pytest tests/test_llm.py -k retry -x` | ❌ W0 | ⬜ pending |
| FND-03 | One repair retry on invalid output; failed output never cached | unit | `pytest tests/test_llm.py -k repair -x` | ❌ W0 | ⬜ pending |
| FND-03 | Second identical call makes zero API calls; key changes with model/prompt/schema | unit | `pytest tests/test_llm.py -k cache -x` | ❌ W0 | ⬜ pending |
| FND-03 | No sampling params set; SDK retries disabled; no `default` in schema | unit | `pytest tests/test_llm.py -k config -x` | ❌ W0 | ⬜ pending |
| FND-03 | Wire contract: key header, mime type, thought signature and function response history | contract | `pytest tests/test_llm.py -k wire -x` | ❌ W0 | ⬜ pending |
| FND-04 | Each smoke check passes on a good fake and fails cleanly on a misbehaving one | unit | `pytest tests/test_smoke.py -x` | ❌ W0 | ⬜ pending |
| FND-04 | Hunter: miss costs 1 live call, hit costs 0, budget blocks, errors not cached, zero results cached | unit | `pytest tests/test_hunter.py -x` | ❌ W0 | ⬜ pending |
| LOG-01 | `run.json` written after each stage; stage failure keeps prior stages | unit | `pytest tests/test_audit.py -k per_stage -x` | ❌ W0 | ⬜ pending |
| LOG-01 | Hard kill leaves valid JSON with earlier stages | subprocess | `pytest tests/test_audit.py -k hard_kill -x` | ❌ W0 | ⬜ pending |
| SND-03 | Dry-run prints payload, no Resend call, `to` is the owner, subject shows intended recipient | unit | `pytest tests/test_send.py -k dry_run -x` | ❌ W0 | ⬜ pending |
| SND-03 | `send_email` has no `to` parameter; 403 owner-only error mapped; missing id errors | unit | `pytest tests/test_send.py -x` | ❌ W0 | ⬜ pending |
| Criteria 3 and 5 | Offline end-to-end: 6 ordered stages, dry-run payload, rerun makes zero Gemini and Hunter calls | e2e | `pytest tests/test_skeleton_e2e.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` with pytest config and pinned deps; venv and install (after the package-legitimacy checkpoint)
- [ ] `tests/conftest.py` — `FakeModels`, `FakeLLM`, `FakeHunter`, `FakeSender`, `fake_sleep`, canary env, tmp cache dirs
- [ ] `tests/fixtures/hunter_domain_search.json` — captured with Hunter's public `test-api-key`
- [ ] `tests/test_hygiene.py`, `test_config.py`, `test_llm.py`, `test_hunter.py`, `test_send.py`, `test_audit.py`, `test_smoke.py`, `test_skeleton_e2e.py`
- [ ] `scripts/check_secrets.py`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Gemini structured output on both models, function-calling round trip, one Hunter call, one Resend send | FND-04 | No API keys exist in the build environment | Create `.env` from `.env.example`, then run `python -m outreach smoke` |
| Resend email arrives in the owner inbox | FND-04 | Delivery is only visible in the owner's mailbox | Check inbox and spam after the smoke run |
| Skeleton dry-run on the chosen domain | SND-03 | Needs live keys and a chosen domain | `python -m outreach skeleton --domain <D>` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
