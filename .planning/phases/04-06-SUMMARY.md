---
phases: [04, 05, 06]
status: complete
requirements: [POC-01, POC-02, POC-03, POC-04, DRF-01, DRF-02, DRF-03, DRF-04, SND-01, SND-02, LOG-02, LOG-03, LOG-04, LOG-05]
completed: 2026-11-04
---

# Phases 4-6 Summary (one fast pass, no per-plan ceremony)

Built directly from the roadmap and requirements. All tests offline; no live API call, no send.

## What shipped

- **webapi** (`src/outreach/webapi.py`): `run_stage(stage, state, *, settings, send=False, live_hunter=False, ...)`.
  Stateless JSON-in/JSON-out, one stage per call (`scrape, extract, qualify, poc, draft, send`),
  envelope `{stage, status ok|stopped|failed, stop_reason, detail, result, state}`. Caches and outputs
  move under a temp dir when `VERCEL` or `OUTREACH_DATA_DIR` is set. Optional seams (`data_dir, llm,
  fetcher, hunter, sender`) are additive. The `hunter` stage is now named `poc`.
- **Phase 4** (`poc.py`): deterministic title ranking per size band (small/mid/large; mid when headcount
  unknown), negative keywords, confidence/verification multiplier, tie-breakers (decision_maker,
  executive, linkedin, confidence, address), top 3 logged with the reason, `no_contact` stop. Name and
  title verbatim from Hunter. Hunter client keeps its cache-first persistent counter and gains a
  per-instance in-memory counter on Vercel. Default runs use the fixture unless `--live-hunter`.
- **Phase 5** (`draft.py`): evidence pack with stable ids, exactly two pain points (LLM, validated,
  persona-library fallback), draft returning `claims_used`, validator (greeting name, 50-90 words, subject
  2-5 lowercase, URLs, banned phrases, one question, numbers and proper nouns vs evidence, Sprinto
  whitelist S1/S2, evidence citation), one regeneration then `rejected_draft`, compliance footer with
  placeholder sender identity and opt-out.
- **Phase 6**: send path already guarded (owner-forced `to`, `[TEST -> Name <email>]`, idempotency key,
  id check), now covered by tests; `decision.md` (written beside `run.json` when a run finishes) and
  `python -m outreach show <domain>`; `run --replay` (caches only, uncached call = failed domain);
  `scripts/demo.py` saves six-domain offline output to `docs/demo/`; `README.md`.

## Decisions

- Pain points and draft share the `draft` stage (the web contract has six stages); pain points are in
  `DraftOutput.pain_points`.
- Sentence-initial words are exempt from the proper-noun check (a deliberate false-negative trade-off
  to avoid rejecting normal sentences); mid-sentence capitalised words must be in the evidence or whitelist.
- The pipeline now makes 3 LLM calls per qualified domain (extract, pain_points, draft); tests updated.

## Deviations

- [Rule 1] Existing tests asserted stage name `hunter`, 2 LLM calls and a draft naming the company;
  updated to `poc`, 3 calls and a company-agnostic canned draft (the validator rejects a company name
  that is not in the evidence).
- `tests/test_web_api.py` (the parallel web agent's tests) had 3 failures at the time of the last full
  run; not part of this work.

## Known gaps

- `--replay` for a live Hunter run requires the Hunter cache; no `--replay` for `show` is needed (it
  reads `run.json`).
- Web state carries scraped page text between calls (can approach request-size limits on big sites).
- Sender identity and postal address in the footer are placeholders.
