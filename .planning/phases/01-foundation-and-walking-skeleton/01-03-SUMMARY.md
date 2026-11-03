---
phase: 01-foundation-and-walking-skeleton
plan: 03
subsystem: external-clients-and-cli
tags: [python, gemini, google-genai, hunter, httpx, trafilatura, typer, retry, cache, smoke, respx]
status: complete

requires:
  - phase: 01-foundation-and-walking-skeleton
    provides: "Plan 01-02 LLMLike/HunterLike/FetcherLike protocols, run_one, send_email, offline fakes"
provides:
  - "outreach.llm: LLMClient (retry/backoff honouring retryDelay, one repair retry, validated-output cache), error types, gemini_schema, build_config, USE_RESPONSE_JSON_SCHEMA and SEND_THINKING_CONFIG fallback flags"
  - "outreach.fetch: PageFetcher (10 s/5 s timeouts, 1.5 MB streamed cap, HTML only, trafilatura with BeautifulSoup fallback, page cache, chars == len(text))"
  - "outreach.hunter: cache-first HunterClient with persistent monthly budget and account(); FixtureHunter scoped to its own domain"
  - "outreach.smoke: five check functions plus run_smoke with the cheap-first stop rule"
  - "outreach.cli / python -m outreach: skeleton (dry-run only) and smoke commands, build_context"
affects: [01-04, phase-2, phase-3, phase-4, phase-5, phase-6]

actuals:
  tokens: 20000
  tasks: 3
  commits: 3
plan_head_before: da3fcfe0a29a96dfabcce8400e695ec787316546
plan_head_after: 8bf6d45a25dae6349580d459d0f549a2ba953bb2

tech-stack:
  added: []
  patterns:
    - "One Gemini wrapper: only llm.py and smoke.py import google.genai"
    - "Cache-before-network for Hunter: entry written with atomic_write_json before the call returns, zero-result 200s included"
    - "Smoke checks are plain functions over injected clients; every check returns a FAIL result instead of raising"
    - "Cheap checks first; the first cheap FAIL turns every later check into SKIPPED so no credit or email is spent"
    - "Retry error text is status code, status and message only; run_smoke redacts every printed line"

key-files:
  created:
    - src/outreach/llm.py
    - src/outreach/fetch.py
    - src/outreach/hunter.py
    - src/outreach/smoke.py
    - src/outreach/cli.py
    - src/outreach/__main__.py
    - tests/test_llm.py
    - tests/test_fetch.py
    - tests/test_hunter.py
    - tests/test_smoke.py
  modified:
    - tests/test_skeleton_e2e.py

key-decisions:
  - "generate_raw hands the SDK a copy of the contents list, so recorded calls are snapshots and the repair turn never rewrites the first request in test assertions"
  - "A corrupt LLM cache entry is treated as a miss and overwritten, never a crash"
  - "HunterClient converts transport errors to HunterError carrying only the exception type name, so no request detail can reach logs"
  - "Stopped skeleton runs print stop_reason before the status= line so the status= line is always the last output line (Plan 01-04's rerun gate)"
  - "check names carry the model for structured checks (gemini_structured[<model>]); the stop rule compares the family before the bracket"

requirements-completed: [FND-03, FND-04, SND-03]

coverage:
  - id: D1
    description: "Retry/backoff on 408/429/5xx/transport errors honouring retryDelay; 400 not retried; auth immediate; retryDelay above max_wait raises LLMQuotaError"
    requirement: FND-03
    verification:
      - kind: unit
        ref: "tests/test_llm.py -k retry (13 tests)"
        status: pass
  - id: D2
    description: "Exactly one repair attempt for blocked/empty/truncated/invalid output; invalid output never cached"
    requirement: FND-03
    verification:
      - kind: unit
        ref: "tests/test_llm.py -k repair (6 tests)"
        status: pass
  - id: D3
    description: "No temperature/top_p/top_k, SDK retries off, no default keys in the schema, flag fallbacks, key only in x-goog-api-key header, thought signatures preserved"
    requirement: FND-03
    verification:
      - kind: unit
        ref: "tests/test_llm.py -k config (7 tests) and -k wire (3 tests, respx over the real genai.Client)"
        status: pass
  - id: D4
    description: "Hunter is cache-first, budget-capped, never caches 401/429, account() keeps a real 0, FixtureHunter attaches its contact only to piedpiper.com"
    requirement: SND-03
    verification:
      - kind: unit
        ref: "tests/test_hunter.py (22 tests incl. test_account_zero_credits_returns_zero, test_fixture_hunter_returns_contact_only_for_fixture_domain)"
        status: pass
  - id: D5
    description: "Page fetcher caches, caps size and text, keeps chars == len(text) for live, cached and over-long pages"
    requirement: FND-03
    verification:
      - kind: unit
        ref: "tests/test_fetch.py (14 tests incl. test_ok_page_chars_equals_text_length)"
        status: pass
  - id: D6
    description: "Every smoke check passes on a good fake and FAILs cleanly on a bad one; cheap FAIL skips Hunter search and Resend; hunter FAILs NOT LIVE from cache; real HunterClient zero credits skips search and send"
    requirement: FND-04
    verification:
      - kind: unit
        ref: "tests/test_smoke.py (16 tests)"
        status: pass
  - id: D7
    description: "Second run of the same domain through the real LLMClient, PageFetcher and HunterClient makes zero Gemini calls, zero page fetches and zero live Hunter calls"
    requirement: FND-03
    verification:
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_rerun_makes_zero_gemini_and_hunter_calls"
        status: pass
  - id: D8
    description: "skeleton CLI prints the dry-run payload and never calls Resend; missing config names variables only"
    requirement: SND-03
    verification:
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_skeleton_cli_prints_payload_and_exits_zero, test_skeleton_cli_missing_config_names_variables_only, test_fixture_hunter_on_other_domain_stops_no_contact"
        status: pass
---

# Phase 1 Plan 3: Real clients and CLI Summary

**One Gemini wrapper (retry with honoured `retryDelay`, a single repair retry, validated-output cache), a cached page fetcher, a cache-first budget-capped Hunter client, and the `skeleton` and `smoke` commands, all proven offline; a rerun of the same domain through the real clients makes zero Gemini, page and Hunter calls.**

## Accomplishments

- Task 1 (`6e44d05`): `llm.py` with `LLMClient`, `build_config`, `gemini_schema`, error types and the two documented live-fallback flags. 37 offline tests, including respx wire tests against the real `genai.Client` (key only in `x-goog-api-key`, no `temperature`/`topP`/`topK`, `thoughtSignature` round-tripped, SDK retries off so one 429 costs exactly one extra request).
- Task 2 (`eb2dcc9`): `fetch.py`, `hunter.py` and 36 tests. The Hunter cache envelope (`domain, fetched_at, params, credits_used, response`) is asserted key-for-key because Phase 4 reads it.
- Task 3 (`8bf6d45`): `smoke.py`, `cli.py`, `__main__.py`, 16 smoke tests and 9 added e2e tests (the 5 named in the plan plus stopped-run exit code, failure redaction, missing domain, bad `--only`).
- Tracer/RED cadence: Tasks 1 and 2 were run RED first (collection error on the missing module), then GREEN. Task 3 is not `tdd="true"`; its implementation preceded its tests.

## Task Commits

1. Task 1: `6e44d05` feat(01-03): Gemini wrapper with retry, one repair retry and validated-output cache
2. Task 2: `eb2dcc9` feat(01-03): cached page fetcher and cache-first, budget-capped Hunter client
3. Task 3: `8bf6d45` feat(01-03): skeleton and smoke CLI commands wired to real clients

## Verification

- `.venv/bin/python -m pytest -q`: 153 passed (55 prior + 98 new)
- `-k retry` 13, `-k repair` 6, `-k cache` 10, `-k config` 7, `-k wire` 3 passed; `tests/test_hunter.py` 22; `tests/test_fetch.py` 14; `tests/test_smoke.py` 16
- `tests/test_skeleton_e2e.py::test_rerun_makes_zero_gemini_and_hunter_calls` and `::test_fixture_hunter_on_other_domain_stops_no_contact`: passed
- `.venv/bin/python scripts/check_secrets.py`: OK, no secrets found (52 files scanned)
- `python -m outreach --help` lists `skeleton` and `smoke`; `skeleton --help` shows `--domain` and `--hunter-fixture`; `smoke --help` shows `--only`
- `grep -rlE "google\.genai|from google import genai" src/outreach` prints exactly `llm.py` and `smoke.py`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test arithmetic in `test_fetch_body_is_cut_at_max_bytes`**
- **Found during:** Task 2
- **Issue:** the 40 head paragraphs (about 2.6 KB) were shorter than the 3000-byte test cap, so the cut landed inside the tail and the assertion `TAILPART not in text` failed. The fetcher was right; the test data was wrong.
- **Fix:** 100 head paragraphs and an added `len(text) <= 3000` assertion.
- **Files modified:** tests/test_fetch.py
- **Commit:** `eb2dcc9`

### Process notes

**1. [Unintended live call] One real Gemini request during manual CLI check**
- After Task 3's tests passed I ran `python -m outreach smoke` from the project root to eyeball the output. The project `.env` is found by `find_dotenv(usecwd=True)` and holds values for the key variables, so the command made one real request to Gemini, which answered 401 `API key not valid` (the `.env` value is not a working key). Nothing was spent and no key value was printed. The cheap-fail stop rule worked on the real path: the Hunter account/search and Resend checks were SKIPPED, so no Hunter or Resend call was made. Later CLI checks were run from an empty directory with `env -i`. Plan 01-04 note: `.env` in this checkout currently holds a non-working Gemini key value; the owner must replace it before the live smoke.

**2. [Test count] `tests/test_smoke.py` holds exactly the 16 named tests**
- Extra assertions (cost-free cases such as the `WARNING remaining != budget` path and the `remaining unknown` warning line) were folded into those tests so the acceptance count of 16 stays exact.

## Authentication Gates

None.

## Known Stubs

None. The `USE_RESPONSE_JSON_SCHEMA` and `SEND_THINKING_CONFIG` flags are intentional switches for the live fallbacks Plan 01-04 may flip; they are not stubs.

## Threat Flags

None beyond the plan's register. T-01-10 (keys only in headers, errors carry status/ids only, run_smoke redacts every line) and T-01-11 to T-01-16 each have a covering test (`test_wire_header_key_and_generation_config`, `test_budget_blocks_next_miss_with_no_http_request`, `test_retry_delay_above_max_wait_raises_quota_without_sleeping`, `test_repair_two_invalid_raises_schema_error_and_caches_nothing`, `test_hunter_cache_hit_fails_not_live`, the fetch size/timeout tests).

## Notes for Plan 01-04

- A repeat `smoke` run reports `hunter` as FAIL `NOT LIVE: served from cache` by design (the first run is the live proof).
- `skeleton` prints `status=... run_record=... llm_api_calls=... llm_cache_hits=... hunter_live_calls=...` as its last line (stop_reason, when present, comes before it).
- `skeleton` and `smoke` read `.env` from the working directory upward, so run them from the intended project directory only when real keys are in place.

## Self-Check: PASSED

- FOUND: src/outreach/llm.py, fetch.py, hunter.py, smoke.py, cli.py, __main__.py; tests/test_llm.py, test_fetch.py, test_hunter.py, test_smoke.py, test_skeleton_e2e.py
- FOUND commits: 6e44d05, eb2dcc9, 8bf6d45 (all ancestors of HEAD)
