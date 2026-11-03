# Sprinto Cold Outreach Pipeline

## What This Is

An automated pipeline that takes a list of company domains and, with no human decisions in between, decides whether each is a fit for Sprinto (compliance automation: SOC 2, ISO 27001, GDPR), finds the right decision-maker, and writes and sends a personalised cold email. Built for Mesa PGP Cohort 4, Term 2, AI Case 2 ("Cold Outreach, at Scale"), replacing a Growth Lead's manual 15-20 min/company research and writing.

## Core Value

For a qualified company, a personalised email addressed to a real named person with a specific, evidence-based hook lands in the inbox, and every decision behind it (why this company, why this person, why this email) can be defended from a logged trail.

## Business Context

- **Customer**: Sprinto's Growth Lead (outbound sales); built here as a course case
- **Revenue model**: Outbound pipeline for Sprinto's compliance-automation product
- **Success metric**: Email reaches inbox, named PoC, hook a human would reply to; every decision defensible
- **Strategy notes**: Brief at /Users/harshitsinha/Downloads/bb9aa7e9-82bb-4eaf-9e53-d0af5c812a10.pdf

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Run end-to-end on a file of domains without per-step decisions (repeatable)
- [ ] Step 1: scrape a prospect's site (home, about, careers, security/trust, pricing, blog) for raw signal, tolerating failures
- [ ] Step 2: extract schema-validated structured company data (stage, headcount, product, compliance mentions, hiring signals); unknown stays unknown
- [ ] Step 3: qualify against a researched, written Sprinto ICP rubric using a weighted score and threshold, with a bounded agent loop that fetches more information when data is insufficient
- [ ] Step 4: find the right PoC via Hunter.io Domain Search with title ranking and local caching (25 searches/month free tier)
- [ ] Step 5: identify the two most likely pain points for that person, grounded in role and scraped evidence
- [ ] Step 6: draft a personalised email addressed by name with a specific hook, validated against hallucinated facts
- [ ] Step 7: send via Resend (from onboarding@resend.dev, to: hardcoded to the user's own email) with a dry-run flag
- [ ] Per-company decision log (company qualification, PoC choice, email rationale) that can be shown in the demo

### Out of Scope

- Sending to real prospects — brief hardcodes `to:` to the user's own address
- Gmail sending — replaced by Resend (user decision; deviation from brief Step 7)
- Web UI — CLI plus decision log is enough for a 1.5h build
- Reply handling, follow-up sequences, CRM sync — not in the brief
- Apollo.io path — Hunter chosen

## Context

- Mesa PGP Cohort 4 Term 2 Build 2, session on 3 Nov 2026, 1.5 hours
- Sprinto ICP from the brief: SaaS companies, typically Series A-C, preparing for an audit or pressured by enterprise customers to certify
- Resend's onboarding@resend.dev sender delivers only to the Resend account owner's email, which fits the hardcoded-recipient rule
- Greenfield project in ~/Projects/sprinto-outreach

## Constraints

- **Tech stack**: Python; Gemini API for all LLM steps; Resend API for sending; Hunter.io Domain Search for PoC — user decisions
- **Timeline**: 1.5h build — keep scope to a thin end-to-end slice first, then deepen
- **Dependencies**: Hunter free tier is 25 searches/month — cache results and support dry-run
- **Safety**: `to:` is hardcoded to the user's own email; keys live in a local `.env`, never committed
- **Reliability**: Agent loop needs a hard iteration cap and a logged reason for each extra fetch

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python | Fast to build scraping and API glue | — Pending |
| Gemini API for LLM steps | User's choice | — Pending |
| Resend instead of Gmail | User's choice; simple API key | — Pending |
| Hunter.io for PoC | Repeatable API vs manual Apollo | — Pending |
| Weighted-score ICP with threshold | More defensible than pass/fail | — Pending |
| CLI plus decision log, no web UI | Time-boxed build | — Pending |
| from: onboarding@resend.dev | No DNS setup; matches own-email recipient | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-11-03 after initialization*
