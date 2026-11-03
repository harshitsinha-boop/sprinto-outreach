---
phase: 02-runner-cli-and-real-scrape-extract
plan: 03
subsystem: extraction-and-prompt-injection-defence
tags: [python, pydantic, gemini-structured-output, prompt-injection, evidence-validation, pytest]
status: complete

requires:
  - phase: 02-runner-cli-and-real-scrape-extract
    provides: "scrape_domain, usable_pages, PageResult(kind, final_url), run_batch, offline test doubles"
  - phase: 01-foundation-and-walking-skeleton
    provides: "LLMLike.generate_structured seam, LLMClient with gemini_schema/build_config, run_one and RunStore"
provides:
  - "outreach.models: EvidencedText, EvidencedBool, StageFact, HeadcountFact, ComplianceMention, HiringSignal, EnterpriseCustomer, CompanyProfile, DroppedEvidence, reshaped ExtractOutput"
  - "outreach.extract: EXTRACT_SYSTEM, EXTRACT_PROMPT_VERSION=extract.2, MIN_QUOTE_CHARS, INJECTION_PATTERNS, normalize_ws, canonical_url, is_instruction_line, strip_instruction_lines, escape_page_tags, prompt_text, build_extract_prompt, validate_profile, extract_profile"
  - "stage_extract delegating to extract_profile over usable pages; score and draft helpers moved to the new profile"
affects: [phase-3, phase-5, phase-6]

actuals:
  tokens: 11000
  tasks: 2
  commits: 4
plan_head_before: 6da298e161ac21be926d256429a3772b46bc208a
plan_head_after: 3384f27dfd82a146bb961a1a743eb66269f94e6c

tech-stack:
  added: []
  patterns:
    - "The model and the validator see the same text: validate_profile compares quotes against prompt_text(page), never against raw page text"
    - "Two-step miss classification: a quote missing from the prompt text but present in the clipped original is instruction_like_text, otherwise quote_not_on_page"
    - "Deterministic guard only removes values; it never invents or repairs one, so an obedient model can only be reduced to what the page genuinely states"
    - "Page tags in text are escaped (&lt;) and attribute values are percent-encoded, so a page cannot close or open a block"

key-files:
  created:
    - src/outreach/extract.py
    - tests/test_extract.py
  modified:
    - src/outreach/models.py
    - src/outreach/stages.py
    - tests/conftest.py
    - tests/test_llm.py
    - tests/test_skeleton_e2e.py
    - tests/test_scrape.py

key-decisions:
  - "Instruction-line detection is nine narrow regex shapes (ignore/disregard previous instructions, you must now, you are now an assistant, reveal your system prompt, chat-role labels, 'as an AI language model', 'new instructions:', page/system/instructions tags); no bare verbs, so ordinary marketing and security copy passes unchanged (13 real-copy fixtures)"
  - "The original-text check for instruction_like_text uses the original text clipped to MAX_PAGE_CHARS, so a quote past the prompt limit is quote_not_on_page, not instruction_like_text"
  - "A cleared as_of is logged with field '<field>.as_of' and is not counted as a dropped item; evidence_kept = checked minus dropped items"
  - "Prompt page blocks carry kind: <page url=\"...\" kind=\"home\">; a page with no kind is labelled other"

requirements-completed: [EXT-01, EXT-02, EXT-03]

coverage:
  - id: D1
    description: "Extraction returns a CompanyProfile with name, offering, is_b2b, stage, headcount, compliance mentions, hiring signals and enterprise customers; every field required but nullable in the schema"
    requirement: "EXT-01"
    verification:
      - kind: unit
        ref: "tests/test_extract.py#test_company_profile_schema_requires_every_field_and_has_no_defaults"
        status: pass
      - kind: e2e
        ref: "tests/test_extract.py#test_unknown_facts_stay_null_through_run_one"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every kept evidence item has a quote of at least 8 characters found verbatim (whitespace-normalised) on the page its source_url names; others are dropped with a reason and a failing scalar becomes null"
    requirement: "EXT-02"
    verification:
      - kind: unit
        ref: "tests/test_extract.py#test_quote_on_other_page_is_dropped"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_scalar_with_bad_quote_becomes_null"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_unknown_source_url_is_dropped"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_short_quote_is_dropped"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_as_of_not_on_page_is_cleared"
        status: pass
      - kind: e2e
        ref: "tests/test_extract.py#test_extract_stage_records_evidence_counts_in_run_json"
        status: pass
    human_judgment: false
  - id: D3
    description: "Page text is delimited per page, page tags are escaped, instruction lines are removed before prompting, ordinary copy is never removed, and the system instruction declares page text untrusted"
    requirement: "EXT-03"
    verification:
      - kind: unit
        ref: "tests/test_extract.py#test_page_closing_tag_breakout_is_escaped"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_instruction_lines_are_removed_before_prompting"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_ordinary_copy_is_not_flagged_as_instructions"
        status: pass
      - kind: unit
        ref: "tests/test_extract.py#test_planted_instruction_lines_are_flagged"
        status: pass
    human_judgment: false
  - id: D4
    description: "The extraction call carries no tools of any kind and the Gemini wrapper exposes no tools parameter"
    requirement: "EXT-03"
    verification:
      - kind: unit
        ref: "tests/test_extract.py#test_extract_call_passes_no_tools"
        status: pass
    human_judgment: false
  - id: D5
    description: "A page with planted instruction-like text yields exactly the same validated profile as the clean page, even when the model output follows the planted text"
    requirement: "EXT-03"
    verification:
      - kind: unit
        ref: "tests/test_extract.py#test_injected_page_yields_same_validated_profile_as_clean_page"
        status: pass
      - kind: e2e
        ref: "tests/test_skeleton_e2e.py#test_planted_instructions_do_not_change_extracted_profile"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-11-03
---

# Phase 2 Plan 03: Evidence-Quoted Extraction and Injection Defence Summary

**`extract_profile` turns usable pages into a schema-validated `CompanyProfile` where every kept value carries a quote found verbatim on the page it cites, page text is escaped and stripped of instruction lines before prompting, the call has no tools, and planted instructions provably leave the validated profile unchanged.**

## Performance

- **Duration:** about 9 min
- **Completed:** 2026-11-03T10:56Z
- **Tasks:** 2 of 2 (both TDD: RED then GREEN commit each)
- **Files:** 2 created, 6 modified
- **Suite:** 236 tests at start, 279 at end, all offline; `scripts/check_secrets.py` clean

## Accomplishments

- Full EXT-01 profile with no defaults anywhere, so the Gemini schema marks all eight fields required and the model must write null or `[]`; `is_b2b` is tri-state.
- `validate_profile`: unknown URL, too-short quote, quote not on the cited page (a quote on a different page fails), whitespace reflow tolerated, `final_url` and trailing-slash citations accepted, `as_of` cleared when absent from the cited page. Every drop is logged in `evidence_dropped`.
- Hostile-text handling: page tags escaped, URL and kind attribute values percent-encoded, instruction-like lines emptied before prompting, and a quote taken from a removed line dropped as `instruction_like_text`. `injection_suspected_pages` names affected pages.
- Invariance proven twice: at the validator (obedient model output over the injected page equals the clean-page profile) and through `run_one` and `run.json`.

## Task Commits

1. **Task 1 RED: failing extract tests** - `34d1f4d` (test)
2. **Task 1 GREEN: CompanyProfile family, validate_profile, stage wiring** - `90638b4` (feat)
3. **Task 2 RED: failing untrusted-text, no-tools and invariance tests** - `7ac9016` (test)
4. **Task 2 GREEN: escaping, instruction-line removal, CompanyProfileLite removed** - `3384f27` (feat)

**Plan metadata:** the docs commit carrying this SUMMARY, STATE.md and ROADMAP.md follows.

## Decisions Made

See `key-decisions`. The two worth remembering: validation always runs against `prompt_text`, and the instruction-line filter is deliberately narrow (full phrases only) because a false positive silently deletes real company copy.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Two existing prompt-shape assertions in tests not listed in the plan**
- **Found during:** Task 1 (full-suite run)
- **Issue:** the plan's page block is `<page url="URL" kind="KIND">`, but `tests/test_scrape.py` and `tests/test_skeleton_e2e.py` asserted the old `<page url="URL">` form.
- **Fix:** both assertions now expect `kind="home"` (the scraper sets the homepage kind).
- **Files modified:** tests/test_scrape.py, tests/test_skeleton_e2e.py (test_scrape.py is not in the plan's `files_modified`)
- **Committed in:** `90638b4`

### Small additions inside plan scope

- Extra tests: `test_as_of_on_page_is_kept`, `test_extract_profile_drops_are_counted_and_logged`, `test_attribute_values_cannot_close_the_tag`, `test_quote_beyond_the_prompt_limit_is_not_on_page`.
- `conftest.py` gained `PLANTED_LINES`, `INJECTED_PAGE_TEXT` and `obedient_extract_response()` so the unit and e2e invariance tests share one hostile fixture set.
- A cleared `as_of` that exists only on a removed line is logged as `instruction_like_text` (the plan's "same two-step rule"); one absent from the page is `as_of_not_on_page`.
- The original `Evidence` model is now unused but left in `models.py` (the plan only removes `CompanyProfileLite`).

**Total deviations:** 1 auto-fixed (blocking, test-side). **Impact:** none on behaviour.

## Issues Encountered

None.

## Authentication Gates

None.

## Known Stubs

None. The Phase 1 draft prompt and four-signal scorer remain placeholders owned by Phases 5 and 3 as planned; they now read the new profile.

## Threat Flags

None. T-02-15 to T-02-18 and T-02-21 are mitigated and tested. T-02-19 (planted text makes the model omit true facts) and T-02-20 (public page text sent to the Gemini free tier) are accepted as planned. The line filter is line-granular: an injected sentence inside a long paragraph removes the whole line, which biases toward unknown, never toward a false fact.

## Owner-pending items

- The optional live check in Task 2 (`outreach run out/live-domains.txt` with `linear.app` and a `.invalid` domain, then `scripts/check_secrets.py`) was NOT run. It needs the owner's live Gemini key and network access; this plan made no network call, never opened `.env` and spent no Gemini, Hunter or Resend call. Owner-pending.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `CompanyProfile` field names are the contract for the Phase 3 rubric, the Phase 5 drafter and the Phase 6 decision log. `validate_profile(profile, pages)` is ready for the Phase 3 agent loop to re-run on newly fetched pages.
- The LLM cache keys on schema and `extract.2`, so any earlier cached extract entries are not reused.

## Self-Check: PASSED

- Files exist: `src/outreach/extract.py`, `tests/test_extract.py` (FOUND)
- Commits `34d1f4d`, `90638b4`, `7ac9016`, `3384f27` are ancestors of HEAD (FOUND)
- `.venv/bin/python -m pytest -q`: 279 passed; `scripts/check_secrets.py`: OK
- Acceptance checks: `extract_profile(ctx.llm` count 1; `usable_pages(prev["scrape"].pages)` count 1; schema required-set one-liner exits 0; `CompanyProfileLite` absent; only `llm.py` and `smoke.py` import the Gemini SDK

## TDD Gate Compliance

Both tasks have a `test(02-03)` RED commit followed by a `feat(02-03)` GREEN commit (`34d1f4d` then `90638b4`; `7ac9016` then `3384f27`). Both REDs failed at collection (missing `conftest` constants or `outreach.extract` names), a failing state but not an assertion-level failure.
