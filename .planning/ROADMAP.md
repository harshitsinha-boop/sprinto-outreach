# Roadmap: Sprinto Cold Outreach Pipeline

## Overview

A time-boxed (1.5 hour) build of a Python CLI that takes a file of company domains and, with no human decisions in between, qualifies each against a written Sprinto ICP rubric, finds one named decision-maker through Hunter, drafts a validated personalised email, and sends it through Resend to the owner's own address, leaving a defensible decision log for every company. The journey is vertical: Phase 1 proves one domain end to end as a dry-run with all four external APIs verified live, then each later phase deepens one slice (batch runner and real scraping, rubric and agent loop, PoC selection, pain points and draft validation, live send and demo hardening). Every phase leaves the pipeline runnable.

**Time-box guardrails:**
- Walking skeleton (Phase 1) should be running by about T+30 min; freeze features at about T+75 min and spend the rest on rehearsal.
- If the clock runs out, cut in this order: Jina fallback, incumbent detection, separate pain stage (fold it into the draft but still log it separately), score-interval loop targeting (use "if a key signal is unknown, fetch").
- Never cut: the draft validator, the `to:` guard inside `send()`, the decision log, or one real send.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation and Walking Skeleton** - One hardcoded domain runs end to end as a dry-run, with secrets hygiene and all four APIs proven live
- [ ] **Phase 2: Runner, CLI and Real Scrape/Extract** - One command runs a file of domains with failure isolation, safe multi-page scraping and evidence-quoted extraction
- [ ] **Phase 3: ICP Rubric and Bounded Agent Loop** - Reproducible weighted qualification with a capped, logged agent loop for insufficient data
- [ ] **Phase 4: PoC Selection** - One named decision-maker per qualified company from cached, budget-capped Hunter lookups
- [ ] **Phase 5: Pain Points, Draft and Validator** - Two grounded pain points and a validated 50-90 word email addressed by name
- [ ] **Phase 6: Send, Decision Log and Demo Hardening** - Guarded Resend send, readable and replayable decision trail, rehearsed demo set and README

## Phase Details

### Phase 1: Foundation and Walking Skeleton
**Goal:** One hardcoded domain goes end to end (scrape, extract, simple score, Hunter via cache, one draft, dry-run payload printed) with secrets kept out of git and all four external APIs confirmed working live.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, LOG-01, SND-03
**Success Criteria** (what must be TRUE):
  1. `.gitignore` and `.env.example` exist before any `.env` file, and a grep of the repo and the logs for the configured key values finds nothing.
  2. User sets the Gemini, Hunter and Resend keys, the owner email and the model IDs in a local `.env` only, and the smoke test passes: one Gemini structured-output call, one Gemini function-calling round trip, one Hunter call, and one Resend send that arrives at the owner address.
  3. Running the skeleton on one domain prints the exact email payload (from, to, subject, body) that would be sent, without calling Resend.
  4. After each stage the domain's run record is on disk, so killing the process mid-run still leaves a partial trail to inspect.
  5. A rate-limited or schema-invalid Gemini response is retried or repaired automatically, and running the same domain a second time makes no new Gemini calls.
**Plans:** 1/4 plans executed

Plans:
**Wave 1**
- [x] 01-01-PLAN.md — Secret hygiene first commit, approved pinned dependencies, typed Settings from .env, secret scanner (FND-01, FND-02)

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 01-02-PLAN.md — Walking-skeleton tracer: one domain through six stages to a printed owner-addressed dry-run payload, run.json after every stage (LOG-01, SND-03)

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 01-03-PLAN.md — Real clients fill the seams: Gemini wrapper (retry, repair, cache), page and Hunter caches, `skeleton` and `smoke` CLI (FND-03, FND-04 offline)

**Wave 4** *(blocked on Wave 3 completion)*
- [ ] 01-04-PLAN.md — Live proof: owner creates .env, live smoke passes, skeleton dry-run on a real domain, secret scan clean (FND-04 live)

Note: the skeleton's Hunter call goes through a minimal cache-first path so the first live call never burns free-tier quota twice. POC-01 itself (qualified-only gating, filtered query, empty results cached) is delivered and verified in Phase 4.

### Phase 2: Runner, CLI and Real Scrape/Extract
**Goal:** User runs one command on a file of domains and each domain is safely scraped and turned into schema-validated, evidence-quoted company data, with one bad domain never stopping the batch.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: RUN-01, RUN-02, RUN-03, RUN-04, SCR-01, SCR-02, EXT-01, EXT-02, EXT-03
**Success Criteria** (what must be TRUE):
  1. User runs the pipeline on a text file of domains with a single command and no prompts between steps, and it defaults to dry-run; a live send requires an explicit `--send` flag.
  2. A domain that fails (dead DNS, timeout) is recorded as failed and the batch carries on, while a systemic failure such as an invalid API key aborts the whole batch immediately.
  3. At the end of a run a summary table lists every domain with its outcome drawn from the full set (qualified, disqualified, insufficient data, no contact, rejected draft, sent, failed).
  4. For each domain the homepage plus about, careers, security or trust, pricing and customers pages are fetched with timeouts, size caps and robots.txt respected, and a page with too little text or a block signature is marked unavailable and never reaches the LLM.
  5. Extracted company data validates against the schema with unknown fields left null, every evidence item carries a quote and source URL that is a verbatim substring of the fetched text, and instruction-like text planted in a page does not change the output.
**Plans**: TBD

### Phase 3: ICP Rubric and Bounded Agent Loop
**Goal:** Every company gets a reproducible, defensible qualification verdict from a written ICP rubric, and insufficient data triggers a capped, logged agent loop instead of a guess.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: QUA-01, QUA-02, QUA-03, QUA-04, QUA-05
**Success Criteria** (what must be TRUE):
  1. The ICP rubric (hard gates, weighted signals, penalties, threshold) lives in a data file, and its hash appears in the log of every run.
  2. Scoring the same extracted evidence twice gives exactly the same score, because the LLM only extracts facts and Python computes the number.
  3. Each company shows a minimum score (unknowns as 0) and a maximum score (unknowns at full weight), and is qualified, rejected, or sent to the agent loop on that basis.
  4. For an insufficient-data company the agent loop fetches at most 3 extra pages, same-domain only, each with a logged reason, and always ends with a stop-reason value; an off-domain URL it is steered toward is refused.
  5. A disqualified or insufficient-data company shows its full score breakdown in the output and makes zero Hunter calls.
**Plans**: TBD

### Phase 4: PoC Selection
**Goal:** Each qualified company gets exactly one named, defensible decision-maker from Hunter within the free-tier budget, and every other company costs no Hunter credit.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: POC-01, POC-02, POC-03, POC-04
**Success Criteria** (what must be TRUE):
  1. Hunter Domain Search runs once per qualified domain with a single filtered query, and the result, including an empty one, is saved to disk so re-running the domain makes no new Hunter call.
  2. The chosen contact is the top deterministic title match for the company's size band, and the log shows the top candidates and the reason for the choice.
  3. A qualified domain with no named Hunter contact ends as "no contact" and no email is drafted for it.
  4. A persistent budget counter refuses any Hunter call that would exceed the allowance, and default runs and tests use cached or fixture data unless live Hunter is explicitly requested.
**Plans**: TBD

### Phase 5: Pain Points, Draft and Validator
**Goal:** For a qualified company with a named contact, the system produces a 50-90 word plain-text email addressed by name, with an evidence-cited hook, that a deterministic validator has cleared of invented facts.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: DRF-01, DRF-02, DRF-03, DRF-04
**Success Criteria** (what must be TRUE):
  1. For the chosen person the log shows the two most likely pain points, each tied to their role and to an evidence item.
  2. The email greets the person by the name Hunter returned, is 50 to 90 words of plain text, and contains one evidence-cited hook and one small ask.
  3. The validator rejects a draft with a different name, an unsupported number or claim, a URL, or a banned generic phrase; a failing draft is regenerated once and then ends as "rejected draft" if it still fails.
  4. A draft that makes a Sprinto claim outside the whitelist is rejected, so only whitelisted Sprinto claims ever appear in an email.
**Plans**: TBD

### Phase 6: Send, Decision Log and Demo Hardening
**Goal:** The email reaches the owner's inbox through Resend with the recipient forced to the owner address, every company's decision trail is readable and replayable, and a rehearsed demo set with saved output and a README is ready.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: SND-01, SND-02, LOG-02, LOG-03, LOG-04, LOG-05
**Success Criteria** (what must be TRUE):
  1. Running with `--send` delivers the email to the owner's inbox from onboarding@resend.dev, the recipient is the owner address even when Hunter returned a different contact, and the subject shows the intended recipient.
  2. The send confirms a returned message id and uses an idempotency key, so re-running a domain does not send a duplicate.
  3. For any company the readable decision log explains why it qualified, why this person was chosen, and why the email was written this way, including a map from each hook to its evidence.
  4. Running with `--replay` reproduces a run from cached responses with no network calls.
  5. A demo set of 5 to 8 domains (fits, non-fits, an unscrapeable site, a no-contact case) has been run with sample output saved, and the README covers how to run, known limits, and cold-email compliance notes.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation and Walking Skeleton | 1/4 | In Progress | - |
| 2. Runner, CLI and Real Scrape/Extract | 0/TBD | Not started | - |
| 3. ICP Rubric and Bounded Agent Loop | 0/TBD | Not started | - |
| 4. PoC Selection | 0/TBD | Not started | - |
| 5. Pain Points, Draft and Validator | 0/TBD | Not started | - |
| 6. Send, Decision Log and Demo Hardening | 0/TBD | Not started | - |
