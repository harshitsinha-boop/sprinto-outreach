---
phase: 02-runner-cli-and-real-scrape-extract
plan: 02
subsystem: scrape-and-fetch-safety
tags: [python, httpx, robots-txt, ssrf, trafilatura, beautifulsoup, page-gate, pytest]
status: complete

requires:
  - phase: 02-runner-cli-and-real-scrape-extract
    provides: "run_batch, outcome_for, DomainUnreachable, test doubles that accept fetch(url, site=None)"
  - phase: 01-foundation-and-walking-skeleton
    provides: "PageFetcher with disk cache, usable_pages, stage_scrape, FakeFetcher"
provides:
  - "outreach.pagegate: MIN_PAGE_CHARS, BLOCK_MAX_CHARS, BLOCK_SIGNATURES, looks_blocked, page_gate, is_usable, same_site"
  - "outreach.fetch.PageFetcher: robots.txt per RFC 9309, non-public-address guard, manual same-site redirects (max 5), 20 s deadline, 1 s per-host politeness, hidden-text stripping, nav link capture, usable-content gate at the fetcher, GUARD_VERSION cache entries"
  - "outreach.scrape: PAGE_KINDS, FALLBACK_PATHS, KIND_KEYWORDS, candidate_urls, canonical, scrape_domain with attempt, fetch and time caps and duplicate detection"
  - "outreach.models: Link; PageResult kind, reason, final_url, links; ScrapeOutput kinds_found, fetches, skipped_kinds"
  - "FetcherLike.fetch(url, site=None); stage_scrape rewired to scrape_domain(ctx.fetcher, domain)"
affects: [02-03, phase-3, phase-4]

actuals:
  tokens: 14700
  tasks: 2
  commits: 4
plan_head_before: 2d6833905e9d3549d489c3e1f8e6be56e20e7737
plan_head_after: 1c5d2ef0f5d9c1cde171f1869c50b68ae8de6294

tech-stack:
  added: []
  patterns:
    - "Every guard lives in the fetcher (robots, address, redirect, deadline, politeness, sanitise, gate); scrape.py only chooses URLs and takes the fetcher as a parameter"
    - "One scope rule (pagegate.same_site) used by the fetcher and by candidate_urls; every fetch passes site=domain"
    - "Cache entries carry GUARD_VERSION; an entry without the current version is a miss, so a guard change can never be bypassed by an old cache"
    - "usable_pages re-applies is_usable at the extract call site, so a fetcher that does not gate still cannot put a blocked or thin page in a prompt"
    - "Test doubles key on site or subdomain, not exact host, because the scraper also asks for trust.<domain>"

key-files:
  created:
    - src/outreach/pagegate.py
    - src/outreach/scrape.py
    - tests/test_scrape.py
  modified:
    - src/outreach/fetch.py
    - src/outreach/models.py
    - src/outreach/stages.py
    - src/outreach/skeleton.py
    - tests/conftest.py
    - tests/test_fetch.py
    - tests/test_skeleton_e2e.py
    - tests/test_runner.py
    - tests/test_cli_run.py

key-decisions:
  - "robots.txt: 4xx except 429 allows everything; 5xx, 429 and transport errors stop the host; only 2xx and 4xx answers are stored on disk, so a transient 503 is retried on the next run instead of blocking the host forever"
  - "A failed robots lookup is also memoised in memory per fetcher, so one broken host costs one robots request per run, not one per page"
  - "Failures that come from the robots stage (private address, off-site redirect, DNS, transport) are returned for the page but never cached; robots_disallowed, ok and unavailable pages are cached"
  - "Fragment-only hrefs (#top) are skipped during link capture: they point at the same page, not at a new one"
  - "candidate_urls takes the first two keyword matches, then dedupes by canonical form with the fixed paths, exactly as specified (two harvested links that canonicalise equal collapse into one)"
  - "DNS rebinding between check and connect (T-02-13) and off-site ATS links (T-02-14) stay accepted, as planned"

requirements-completed: [SCR-01, SCR-02]

coverage:
  - id: D1
    description: "Homepage plus about, careers, security or trust, pricing and customers pages are fetched with harvested same-site links first, fixed paths second, and attempt, fetch and time caps"
    requirement: "SCR-01"
    verification:
      - kind: unit
        ref: "tests/test_scrape.py#test_scrape_fetches_home_and_five_page_kinds"
        status: pass
      - kind: unit
        ref: "tests/test_scrape.py#test_harvested_nav_link_is_preferred_over_fallback_path"
        status: pass
      - kind: unit
        ref: "tests/test_scrape.py#test_offsite_ats_link_is_never_fetched"
        status: pass
      - kind: unit
        ref: "tests/test_scrape.py#test_attempt_and_fetch_caps_hold"
        status: pass
      - kind: unit
        ref: "tests/test_scrape.py#test_time_budget_skips_remaining_kinds"
        status: pass
    human_judgment: false
  - id: D2
    description: "robots.txt is fetched once per host with the project user agent and honoured per RFC 9309; a disallowed URL is never requested"
    requirement: "SCR-01"
    verification:
      - kind: unit
        ref: "tests/test_fetch.py#test_robots_disallowed_path_is_unavailable_without_request"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_robots_5xx_is_error_and_page_not_requested"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_robots_fetched_once_per_host_and_reused_from_disk"
        status: pass
    human_judgment: false
  - id: D3
    description: "No request to a non-http(s) URL or a host resolving to a non-public address; redirects that leave the site, hit a private address or exceed 5 hops are refused"
    requirement: "SCR-01"
    verification:
      - kind: unit
        ref: "tests/test_fetch.py#test_private_address_is_refused_without_request"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_off_site_redirect_is_unavailable"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_redirect_to_private_address_is_refused"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_too_many_redirects_is_unavailable"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_non_http_scheme_is_unavailable_without_request"
        status: pass
    human_judgment: false
  - id: D4
    description: "Deadline and politeness are enforced on top of the Phase 1 timeouts and 1.5 MB cap; a rerun makes zero requests and a Phase 1 cache entry is ignored"
    requirement: "SCR-01"
    verification:
      - kind: unit
        ref: "tests/test_fetch.py#test_fetch_deadline_stops_slow_body"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_polite_interval_between_requests_to_same_host"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_legacy_unversioned_cache_entry_is_ignored"
        status: pass
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_rerun_makes_zero_gemini_and_hunter_calls"
        status: pass
    human_judgment: false
  - id: D5
    description: "Thin, blocked, duplicate or non-HTML pages are unavailable with a reason, never reach an LLM prompt, and hidden text is stripped before extraction"
    requirement: "SCR-02"
    verification:
      - kind: unit
        ref: "tests/test_fetch.py#test_hidden_elements_and_comments_never_reach_text"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_challenge_page_is_unavailable_blocked"
        status: pass
      - kind: unit
        ref: "tests/test_fetch.py#test_thin_page_chars_is_extracted_length_and_text_none"
        status: pass
      - kind: unit
        ref: "tests/test_scrape.py#test_duplicate_content_is_marked_unavailable"
        status: pass
      - kind: e2e
        ref: "tests/test_scrape.py#test_blocked_page_never_reaches_llm_through_run_batch"
        status: pass
      - kind: e2e
        ref: "tests/test_scrape.py#test_only_usable_pages_reach_extract_prompt"
        status: pass
    human_judgment: false
  - id: D6
    description: "A domain with no usable page stops as insufficient_data with per-reason counts; a dead domain ends failed through the batch runner while the next domain completes"
    requirement: "SCR-02"
    verification:
      - kind: unit
        ref: "tests/test_scrape.py#test_insufficient_data_detail_counts_reasons"
        status: pass
      - kind: e2e
        ref: "tests/test_scrape.py#test_dead_domain_is_failed_through_run_batch"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-11-03
---

# Phase 2 Plan 02: Safe Fetch and Multi-Page Scrape Summary

**`PageFetcher` now honours robots.txt (RFC 9309), refuses non-public addresses and off-site redirects, is bounded by deadline and politeness, strips hidden text, and gates thin or challenge pages; `scrape_domain` fetches home, about, careers, security or trust, pricing and customers within attempt, fetch and time caps.**

## Performance

- **Duration:** about 6 min of execution after the plan and sources were read
- **Started:** 2026-11-03T10:45:11Z (ledger stamp)
- **Completed:** 2026-11-03T10:51Z
- **Tasks:** 2 of 2 (both TDD: RED then GREEN commit each)
- **Files:** 3 created, 9 modified
- **Suite:** 183 tests at start, 236 at end, all offline (the autouse fixture blocks real DNS and sleeping); `scripts/check_secrets.py` clean

## Accomplishments

- Fetch safety: robots.txt per host with the project user agent (4xx allows, 5xx, 429 and transport errors stop the host), address guard on every hop (private, loopback, link-local, CGNAT, multicast, reserved, IPv4-mapped), `follow_redirects=False` with a manual same-site loop of at most 5 hops, 20 s deadline, 1 s per-host politeness.
- Sanitising before extraction: scripts, styles, noscript, templates, iframes, svg, hidden inputs, comments and `hidden`, `aria-hidden` and `display:none`/`visibility:hidden` elements are removed, so a planted marker in each never reaches the text; nav links are captured from what is left.
- One usable-content gate (`pagegate`): `empty`, `blocked` (signature on a page under 2000 characters), `too_short` (under 400). Applied at the fetcher and again in `usable_pages`, so an ungated fetcher still cannot feed a blocked page to the LLM.
- Cache safety: entries carry `GUARD_VERSION = 2`; every Phase 1 entry is ignored and re-fetched through all guards. A rerun makes zero page and zero robots requests.
- Discovery: `scrape_domain` tries the homepage, then five kinds (harvested same-site nav links first, fixed paths second), at most 3 attempts per kind, 14 fetches and 60 s per domain, duplicate-content detection, homepage-error short circuit. `stage_scrape` reports `0 usable of N pages (reason=count, ...)`.

## Task Commits

1. **Task 1 RED: failing fetch-safety tests** - `3226ed9` (test)
2. **Task 1 GREEN: guarded fetch, pagegate, models, conftest** - `ad0a0ff` (feat)
3. **Task 2 RED: failing discovery tests** - `4c8ee01` (test)
4. **Task 2 GREEN: scrape_domain wired into stage_scrape** - `1c5d2ef` (feat)

**Plan metadata:** the docs commit that carries this SUMMARY, STATE.md and ROADMAP.md follows.

## Files Created/Modified

- `src/outreach/pagegate.py` - usable-content gate and the same-site scope rule
- `src/outreach/fetch.py` - the hardened `PageFetcher`
- `src/outreach/scrape.py` - six-kind discovery with caps and duplicate detection
- `src/outreach/models.py` - `Link`, new `PageResult` and `ScrapeOutput` fields
- `src/outreach/stages.py` - `usable_pages` via `is_usable`, `stage_scrape` via `scrape_domain`, `SKELETON_PATHS` removed
- `src/outreach/skeleton.py` - `FetcherLike.fetch(url, site=None)`
- `tests/conftest.py` - `ORIGINAL_SYSTEM_RESOLVE`, autouse offline fixture, `FakeFetcher.fetch(url, site=None)` (the 02-01 heads-up)
- `tests/test_fetch.py`, `tests/test_scrape.py` - 22 plus extras, and 11 plus extras
- `tests/test_skeleton_e2e.py`, `tests/test_runner.py`, `tests/test_cli_run.py` - adjusted for robots requests and `trust.<domain>` fetches

## Decisions Made

See `key-decisions` above. The main one: robots answers are stored on disk only for 2xx and 4xx, so a transient 5xx never becomes a permanent block.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Moved the `len(pages1) >= 2` edit from Task 2 into Task 1**
- **Found during:** Task 1 (full-suite verify)
- **Issue:** robots.txt is now a request, so the real-fetcher rerun test saw 3 requests where it asserted exactly 2. Task 1's verify requires the whole suite green, and the plan placed this edit in Task 2.
- **Fix:** changed `len(pages1) == 2` to `>= 2` (zero requests on the second run, Hunter and Gemini counts unchanged).
- **Files modified:** tests/test_skeleton_e2e.py
- **Committed in:** `ad0a0ff`

**2. [Rule 1 - Bug] Plan 02-01 test doubles keyed on the exact host**
- **Found during:** Task 2 (full-suite run after wiring `scrape_domain`)
- **Issue:** the scraper also asks for `https://trust.<domain>/`, which `RoutingFetcher` and `ThinOrOkFetcher` did not treat as part of the same site. Six tests failed: thin domains became "qualified", an extra `send` call, and the "later domains never fetched" assertions saw `trust.a.example`.
- **Fix:** both doubles now match a host or any subdomain of it; `RoutingFetcher` records the `site` scope it was asked about, and the two abort and hygiene assertions compare scopes instead of raw hosts (same intent: no later domain is ever scraped).
- **Files modified:** tests/test_runner.py, tests/test_cli_run.py (not listed in the plan's `files_modified`)
- **Committed in:** `1c5d2ef`

### Small additions inside plan scope

- Extra tests beyond the named ones: robots user-agent group, robots 401 and 403, relative redirect, off-site URL, mixed private answer, `is_public_address` classes, `candidate_urls` canonical dedupe, `usable_pages` gate re-application, per-kind attempt cap and fetch cap as separate tests.
- `scrape.canonical()` is public (used by tests and by the scrape loop).

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug in earlier test doubles). **Impact:** none on behaviour; both are test-side.

## Issues Encountered

- The first caps test leaked a monkeypatched `MAX_FETCHES_PER_DOMAIN` into a later assertion; split into three tests.
- A Python 3.13 `RobotFileParser` quirk was avoided by design: the fetcher never calls `read()`, and 429 is checked before the generic 4xx rule so it means complete disallow as RFC 9309 requires.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None. All new surface is the planned one: T-02-08 to T-02-12 are mitigated and tested; T-02-13 (DNS rebinding) and T-02-14 (off-site ATS pages) are accepted as planned.

## Owner-pending items

- No live check was run. This plan made no network call, never opened `.env`, and spent no Gemini, Hunter or Resend call. The optional real-site run (including a dead `.invalid` domain through `outreach run`) stays with Plan 02-03 Task 2's human-check and is recorded as owner-pending.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `PageFetcher.fetch(url, site)`, `pagegate.same_site` and `PageResult.links` are ready for Phase 3's agent loop to reuse.
- Plan 02-03 can rely on `ScrapeOutput.kinds_found` and per-page `kind` and `reason` in the run record.
- Note for later plans: any new test fetcher must accept `fetch(self, url, site=None)` and treat subdomains of a domain as the same site.

## Self-Check: PASSED

- Files exist: `src/outreach/pagegate.py`, `src/outreach/scrape.py`, `tests/test_scrape.py` (FOUND)
- Commits `3226ed9`, `ad0a0ff`, `4c8ee01`, `1c5d2ef` are ancestors of HEAD (FOUND)
- `.venv/bin/python -m pytest -q`: 236 passed; `scripts/check_secrets.py`: OK
- Acceptance greps: `GUARD_VERSION` count 7, `def page_gate(` 1, `follow_redirects=False` 1, `scrape_domain(ctx.fetcher` 1, `usable_pages(prev["scrape"].pages)` 2, test `def fetch(` without `site` 0 and with `site` 4; the `is_public_address` one-liner and the `PAGE_KINDS` one-liner exit 0

## TDD Gate Compliance

Both tasks have a `test(02-02)` RED commit followed by a `feat(02-02)` GREEN commit (`3226ed9` then `ad0a0ff`; `4c8ee01` then `1c5d2ef`). Task 2's RED failed at collection (the `outreach.scrape` module did not exist yet), which is a failing state but not an assertion-level failure.
