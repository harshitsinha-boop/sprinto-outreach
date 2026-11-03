# Walking Skeleton — Sprinto Cold Outreach Pipeline

**Phase:** 1
**Generated:** 2026-11-03

## Capability Proven End-to-End

Running `python -m outreach skeleton --domain <D>` scrapes one company's homepage and `/about`, extracts a schema-validated profile with Gemini, computes a simple deterministic score, picks one named Hunter contact through a disk cache, drafts one email with Gemini, and prints the exact Resend payload (`to` = the owner's own address) without calling Resend, while `out/<domain>/run.json` is rewritten after every stage. `python -m outreach smoke` proves the same four external services (Gemini structured output, Gemini function calling, Hunter, Resend) work live with the user's keys.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.13 (needs >=3.11) in a local `.venv`, `pip install -e ".[dev]"` | Locked user decision (Python); `google-genai` 2.34 needs >=3.11; `uv` is not installed |
| Package layout | src layout, one flat package `src/outreach/` (no `stages/` or `clients/` sub-packages yet) | 30-35 minute budget does not pay for nesting; Phase 2+ may split `stages.py` without changing any seam |
| CLI | `typer` app in `outreach/cli.py`, entry `python -m outreach` (`__main__.py`) and console script `outreach`; Phase 1 commands: `skeleton`, `smoke` | Becomes the Phase 2 batch CLI (`run`, `--send`) by adding commands, not by restructuring |
| LLM access | `google-genai` `client.models.generate_content` behind `outreach/llm.py` `LLMClient` (sole importer of `google.genai`, plus `smoke.py` for the function-calling proof); own retry loop with SDK retries set to `attempts=1`; one repair retry on schema failure; disk cache of validated output | One place owns retry, repair, caching, error typing and wire-format quirks (FND-03) |
| Models | `GEMINI_MODEL_FAST=gemini-3.5-flash-lite` (extraction), `GEMINI_MODEL_SMART=gemini-3.8-flash` (drafting, function calling, `thinking_level="LOW"`); no `temperature`/`top_p`/`top_k`; no `-latest`/`-preview` IDs | Pinned GA IDs from `.env` (STACK.md); sampling params are deprecated on Gemini 3.6+ |
| Structured output | Pydantic v2 models in `outreach/models.py`; schema sent as `response_json_schema` with `default` keys stripped; LLM-filled fields are nullable and have no defaults; `model_validate_json` is the gate | "Unknown stays unknown" and one source of truth for schema plus validation |
| Data layer | No database. JSON files with atomic writes (`*.tmp` then `os.replace`): `.cache/llm/<sha256>.json`, `.cache/pages/<sha1(url)>.json`, `.cache/hunter/<domain>.json` plus `.cache/hunter/_usage.json`, and `out/<domain>/run.json` | Human-inspectable, crash-safe, zero dependencies; caches make reruns free and deterministic |
| Identity | The normalised domain (`cache.normalize_domain`) keys every run record and the Hunter cache; LLM and page caches are keyed by content hashes | One identity per company across all phases |
| Run record | `RunRecord` / `StageRecord` (models.py), flushed by `audit.RunStore.flush` before stage 1 and after every stage | LOG-01: a killed process still leaves a partial trail; Phase 6 renders the decision log from this file |
| Orchestration | `skeleton.run_one(domain, ctx)` iterates `stages.STAGES` (scrape, extract, score, hunter, draft, send); expected stops raise `StopStage(reason)`; any other exception records `failed` with a redacted error and is re-raised | Single sequencing point that becomes Phase 2's per-domain inner loop |
| Seams | `skeleton.Context` carries `settings`, `llm`, `hunter`, `fetcher`, `store`, `sender`, `dry_run`, `out`; Protocols `LLMLike`, `HunterLike`, `FetcherLike` | Every external call is injectable, so the whole pipeline is testable offline with fakes |
| Config / secrets | `.env` read with `python-dotenv` `dotenv_values` (process env wins), typed `config.Settings` with `SecretStr` keys, `config.redact()` on every printed or stored error; `OWNER_EMAIL` supersedes STACK.md's `RECIPIENT_EMAIL` | FND-01/FND-02; keys never reach repr, logs, run records or git |
| Auth | No user auth (single-user local CLI). Outbound API keys only: Gemini `x-goog-api-key` header (SDK), Hunter `X-API-KEY` header, Resend key set on `resend.api_key` at call time | Keys never appear in URLs or logs |
| Send | `send.build_payload` is the only payload builder; `send.send_email` has no `to` parameter and always uses `[settings.owner_email]`; dry-run prints the same payload the live path would pass to `resend.Emails.send` | SND-03 now, and the never-cut `send()` guard for Phase 6 |
| Hunter | `hunter.HunterClient`: cache-first Domain Search with one fixed filter set (`type=personal`, `required_field=full_name,position`, `seniority=senior,executive`, `limit=10`), cache written before returning, persistent monthly budget counter (default 25), `account()` for remaining credits; `FixtureHunter` for zero-credit runs | Free-tier credits are the scarcest resource |
| Testing | pytest + respx (Gemini SDK wire contract) + `httpx.MockTransport` (pages, Hunter) + injected fakes (`FakeModels`, `FakeLLM`, `FakeHunter`, `FakeFetcher`, `FakeSender`) in `tests/conftest.py`; all offline | No keys exist in the build environment; live proof is the separate `smoke` command |
| Deployment | Local CLI only: `.venv/bin/python -m outreach smoke` and `.venv/bin/python -m outreach skeleton [--domain D] [--hunter-fixture]` | No server; the documented local commands exercise the full stack |
| Directory layout | `src/outreach/{__init__,__main__,cli,config,models,cache,audit,llm,fetch,hunter,send,stages,skeleton,smoke}.py`, `scripts/check_secrets.py`, `tests/` (with `tests/fixtures/hunter_domain_search.json`), gitignored `.cache/` and `out/` | Flat and greppable; matches 01-RESEARCH.md "Recommended Project Structure" |

## Stack Touched in Phase 1

- [ ] Project scaffold: `pyproject.toml` (setuptools, pytest config `pythonpath = ["src"]`), `.venv`, pinned `requirements.lock.txt`, test runner
- [ ] Routing: CLI commands `skeleton` and `smoke` (`python -m outreach`)
- [ ] Data layer: real reads and writes of `.cache/llm`, `.cache/pages`, `.cache/hunter` (+ `_usage.json`) and `out/<domain>/run.json`
- [ ] UI: the CLI prints the dry-run payload, the run-record path and call counters; `smoke` prints PASS/FAIL lines
- [ ] Deployment: documented local full-stack commands, run live once by the owner with real keys (Plan 01-04)

## Out of Scope (Deferred to Later Slices)

- Batch runner over a domains file, per-domain failure isolation, summary table, `--send` flag (Phase 2)
- Multi-page scrape (careers, security/trust, pricing, customers), robots.txt, block-signature detection, evidence-quote substring enforcement, untrusted-content hardening beyond delimiting (Phase 2)
- Written ICP rubric, score intervals, bounded agent loop with `fetch_page` tool (Phase 3); the Phase 1 scorer is a fixed four-signal score with no gate
- Qualified-only Hunter gating, title ranking by size band, no-contact handling as a batch outcome (Phase 4)
- Pain points, the deterministic draft validator, Sprinto claim whitelist (Phase 5)
- Live sends from the pipeline (the skeleton command always dry-runs; only `smoke` sends one self-addressed email), idempotent re-send semantics, readable decision log, `--replay`, demo set, README (Phase 6)
- Jina Reader fallback, incumbent detection, multiple contacts, real-recipient sending (v2 / cut list)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2: one command runs a file of domains with failure isolation, safe multi-page scraping and evidence-quoted extraction (adds `run` command and deepens `stage_scrape` / `stage_extract`)
- Phase 3: reproducible ICP rubric and a capped, logged agent loop for insufficient data (replaces `stage_score`, adds the loop behind `LLMClient.generate_raw`)
- Phase 4: one named, defensible decision-maker per qualified company within the Hunter budget (deepens `stage_hunter` on top of `HunterClient`)
- Phase 5: two grounded pain points and a validated 50-90 word email (deepens `stage_draft`, adds the validator)
- Phase 6: guarded live send, readable and replayable decision trail, rehearsed demo set and README (renders from `run.json`, hardens `send_email`)
