# Architecture Research

**Domain:** Batch LLM outreach pipeline (scrape -> extract -> qualify w/ bounded agent loop -> find PoC -> pain points -> draft -> send), Python, Gemini + Hunter.io + Resend
**Researched:** 2026-11-03
**Confidence:** MEDIUM-HIGH (pattern design is HIGH from established practice; Gemini SDK and Hunter specifics MEDIUM, verified only by web search snippets, so re-check in Context7 or the official docs when coding)

## Standard Architecture

The shape that fits this problem is a **linear, synchronous, per-record pipeline with typed hand-offs**, not a framework (no LangChain, no LangGraph, no queue). One domain flows through seven stage functions; each stage takes Pydantic models in and returns a Pydantic model out; a runner loops over domains, isolates failures, and writes an audit trail. The only non-linear part is the qualify stage, which contains a small, hard-capped, hand-rolled tool loop.

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│ CLI / Runner  (cli.py, runner.py)                                    │
│  args: --domains file --dry-run --limit N --force --only domain      │
│  for domain in domains:  try: process(domain) except: record failure │
└───────────────┬──────────────────────────────────────────────────────┘
                │ one CompanyRun (state + decision log) per domain
┌───────────────▼──────────────────────────────────────────────────────┐
│ Pipeline stages (pure-ish functions: models in -> model out)         │
│                                                                      │
│  scrape ─▶ extract ─▶ qualify ──(gate: score>=threshold)──▶ find_poc │
│                         │ ▲                                    │     │
│                  agent loop (fetch_url, search)                ▼     │
│                  max N iters, logged reasons          pain_points    │
│                                                                │     │
│                                         send ◀── validate ◀── draft  │
└───────┬──────────────┬──────────────┬───────────────┬────────────────┘
        │              │              │               │
┌───────▼─────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼───────┐
│ Clients     │ │ LLM wrapper │ │ Cache      │ │ Audit/Store  │
│ http, hunter│ │ gemini.py   │ │ (JSON/disk │ │ runs/<domain>│
│ resend      │ │ (structured │ │  keyed by  │ │ /run.json    │
│             │ │  + tool turn)│ │  domain)   │ │ /decision.md │
└─────────────┘ └─────────────┘ └────────────┘ └──────────────┘
```

Key rule: **stages never call each other and never touch the filesystem or network directly.** They receive clients and an `AuditLog` via a small `Context` object. The runner is the only thing that sequences stages. This makes each stage testable with a fixture and lets you build and demo one stage at a time.

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `cli.py` | Parse flags, load `.env`, read domains file, call runner, print summary table | `argparse` or `typer`; `python-dotenv` |
| `runner.py` | Per-domain loop, failure isolation, skip-if-cached, stage sequencing, gate logic, summary | Plain `for` loop with `try/except Exception` per domain (optionally `ThreadPoolExecutor` later) |
| `models.py` | All Pydantic data contracts (the spine of the system) | One file, ~10 small models |
| `stages/scrape.py` | Fetch candidate pages, return cleaned text per page type | `httpx` + `trafilatura` or `selectolax`/BeautifulSoup; page-path probing |
| `stages/extract.py` | Text -> `CompanyProfile` (unknowns stay `None`) | One Gemini call with `response_schema` |
| `stages/qualify.py` | Rubric score + bounded agent loop for missing data + gate decision | Tool loop (manual) then one structured scoring call |
| `stages/poc.py` | Hunter Domain Search, title ranking, cache | Deterministic Python ranking, **LLM not needed** |
| `stages/pain.py` | Two pain points grounded in persona + evidence | One Gemini structured call |
| `stages/draft.py` | Email subject/body + `claims` list; fact validation | One Gemini structured call + deterministic validator |
| `stages/send.py` | Resend send or dry-run render | `resend` SDK or plain `httpx` POST |
| `llm.py` | Only module that imports the Gemini SDK; exposes `generate_structured()` and `run_tool_turn()`; retries, timeouts, token/usage logging | `google-genai` |
| `tools.py` | Tool implementations + Gemini function declarations for the agent loop | `fetch_url(url)`, `search(query)` |
| `cache.py` | Disk cache keyed by `(namespace, key)` with TTL | Directory of JSON files: `.cache/hunter/<domain>.json`, `.cache/pages/<sha>.json` |
| `audit.py` | Append-only decision log per company; renders Markdown | `AuditLog.add(stage, decision, reason, evidence)` |
| `config/icp.yaml` (or `icp.py`) | The written ICP rubric: criteria, weights, threshold, title-priority list | Data, not code, so it is demoable and editable |
| `prompts/` | Prompt templates as `.md`/`.txt` files | Loaded at startup; hashed into the run log |

## Recommended Project Structure

```
sprinto-outreach/
├── .env                      # GEMINI_API_KEY, HUNTER_API_KEY, RESEND_API_KEY, OWNER_EMAIL (gitignored)
├── .env.example
├── .gitignore                # .env, .cache/, runs/
├── domains.txt               # one domain per line (# comments allowed)
├── config/
│   └── icp.yaml              # criteria + weights + threshold + persona title ranking
├── prompts/
│   ├── extract.md
│   ├── qualify_agent.md
│   ├── qualify_score.md
│   ├── pain_points.md
│   └── draft_email.md
├── src/outreach/
│   ├── cli.py                # entrypoint: python -m outreach.cli domains.txt --dry-run
│   ├── runner.py             # loop, isolation, orchestration, gate
│   ├── models.py             # Pydantic contracts
│   ├── context.py            # Context dataclass: clients, cache, audit, flags
│   ├── llm.py                # Gemini wrapper (sole importer of google.genai)
│   ├── tools.py              # fetch_url / search + declarations
│   ├── cache.py
│   ├── audit.py
│   ├── clients/
│   │   ├── http.py           # shared httpx client, UA, timeouts, size cap
│   │   ├── hunter.py
│   │   └── resend_client.py
│   └── stages/
│       ├── scrape.py
│       ├── extract.py
│       ├── qualify.py
│       ├── poc.py
│       ├── pain.py
│       ├── draft.py
│       └── send.py
├── runs/                     # output, gitignored (or committed sample for demo)
│   └── 2026-11-03T10-30-00/
│       ├── summary.csv       # one row per domain: status, score, poc, subject, reason
│       ├── acme.com/
│       │   ├── run.json      # full CompanyRun (all stage outputs + decision log)
│       │   └── decision.md   # human-readable "why" for the demo
│       └── ...
└── tests/                    # a few fixture-driven tests, optional within 1.5h
```

### Structure Rationale

- **`stages/` vs `clients/`:** stages hold business logic and prompts; clients hold I/O. When Hunter quota or a Gemini model changes, only one file moves.
- **`llm.py` as the only Gemini importer:** model name, retry policy, JSON-schema handling, and usage logging live in one place. If the SDK quirk appears (see Pitfalls below), you fix it once.
- **ICP and prompts as files:** the case brief asks that the rubric be "researched and written" and defensible. A `icp.yaml` that is loaded, hashed, and printed into every decision log is a stronger demo artifact than constants buried in code.
- **`runs/<timestamp>/<domain>/`:** immutable per-run output. Re-runs do not overwrite the audit trail of an earlier run, which matters when you are demoing "here is exactly what happened".
- **Flat `models.py`:** at this size, splitting contracts by stage creates import churn. One file is the quickest way to see the whole data flow.

## Data Contracts (Pydantic models between steps)

Design principle: **every field an LLM fills is `Optional` with an explicit `evidence`/`source_url`, and "unknown" is a legal value.** Every model that an LLM produces carries enough provenance for the audit trail.

```python
# models.py  (sketch, not final)
from pydantic import BaseModel, Field
from typing import Literal, Optional

class Page(BaseModel):
    url: str
    kind: Literal["home","about","careers","security","pricing","blog","other"]
    status: Literal["ok","http_error","timeout","blocked","empty"]
    text: str = ""                 # cleaned, truncated (e.g. 8k chars)

class ScrapeResult(BaseModel):
    domain: str
    pages: list[Page]              # failures retained, not dropped
    # stage never raises on a bad page; raises only if ZERO pages ok -> runner marks 'scrape_failed'

class Signal(BaseModel):           # reusable "claim + proof" unit
    value: str
    source_url: Optional[str] = None
    quote: Optional[str] = None    # verbatim snippet used later to validate email facts

class CompanyProfile(BaseModel):   # extract output
    name: Optional[str] = None
    product_summary: Optional[str] = None
    is_saas: Optional[bool] = None
    stage: Optional[Literal["pre-seed","seed","series-a","series-b","series-c","later","public","unknown"]] = "unknown"
    headcount_band: Optional[str] = None            # "11-50", "51-200", ...
    compliance_mentions: list[Signal] = []          # SOC 2, ISO 27001, trust center...
    hiring_signals: list[Signal] = []               # security/compliance/GRC roles
    enterprise_customers_signal: Optional[Signal] = None
    missing_fields: list[str] = []                  # explicit, drives the agent loop

class AgentStep(BaseModel):         # one logged loop iteration
    i: int
    tool: str                       # "fetch_url" | "search"
    args: dict
    reason: str                     # model's stated reason (required in tool schema)
    result_digest: str              # first ~300 chars, not the full page
    error: Optional[str] = None

class CriterionScore(BaseModel):
    criterion: str                  # key from icp.yaml
    weight: float
    score: int = Field(ge=0, le=5)
    rationale: str
    evidence: list[Signal] = []

class Qualification(BaseModel):
    criteria: list[CriterionScore]
    total: float                    # computed IN PYTHON from weights, not by the LLM
    threshold: float
    qualified: bool                 # computed IN PYTHON: total >= threshold
    stop_reason: Literal["sufficient_data","max_iters","no_missing_fields","tool_errors"]
    agent_steps: list[AgentStep]
    enriched_profile: CompanyProfile   # profile after loop merges new facts

class PoC(BaseModel):
    first_name: str; last_name: str; email: str
    position: str; seniority: Optional[str]; department: Optional[str]
    hunter_confidence: Optional[int]
    rank_reason: str                # "matched priority title 'Head of Security' (rank 1 of ICP list)"
    candidates_considered: int
    from_cache: bool

class PainPoint(BaseModel):
    pain: str
    why_this_person: str            # ties to role
    evidence: list[Signal]          # must cite scraped signals

class PainAnalysis(BaseModel):
    pain_points: list[PainPoint] = Field(min_length=2, max_length=2)

class EmailDraft(BaseModel):
    subject: str
    body: str
    hook: str                       # the single specific hook sentence
    claims: list[Signal]            # every factual claim made about the company, with quote
    rationale: str                  # why this angle/this person

class ValidationReport(BaseModel):
    passed: bool
    ungrounded_claims: list[str]
    checks: dict[str,bool]          # addressed_by_name, has_hook, no_banned_phrases, length_ok
    attempts: int

class SendResult(BaseModel):
    mode: Literal["sent","dry_run","skipped"]
    resend_id: Optional[str] = None
    to: str                         # always OWNER_EMAIL
    intended_recipient: Optional[str] = None   # real PoC email, recorded but NOT used

class CompanyRun(BaseModel):        # the whole audit record, serialized to run.json
    domain: str
    status: Literal["sent","dry_run","disqualified","no_poc","failed"]
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    scrape: Optional[ScrapeResult] = None
    profile: Optional[CompanyProfile] = None
    qualification: Optional[Qualification] = None
    poc: Optional[PoC] = None
    pain: Optional[PainAnalysis] = None
    draft: Optional[EmailDraft] = None
    validation: Optional[ValidationReport] = None
    send: Optional[SendResult] = None
    decisions: list["Decision"] = []   # ordered, human-readable log
    started_at: str; finished_at: Optional[str] = None
    prompt_hashes: dict[str,str] = {}; model: str = ""

class Decision(BaseModel):
    stage: str
    outcome: str                   # "qualified" | "rejected" | "chose_poc" | "drafted" | ...
    reason: str                    # one or two sentences
    evidence_urls: list[str] = []
```

Notes that matter for roadmap:

- **Computed fields live in Python, not the LLM.** The LLM produces per-criterion 0-5 scores and rationales; Python multiplies by weights, sums, compares to threshold. This makes "why qualified" arithmetically reproducible and defensible. (HIGH confidence, standard practice.)
- **`CompanyRun` is both the state object and the audit record.** One object, serialized after each stage, so a crash leaves a partial but readable trail.
- **`status` is a small closed enum** so the summary table is a trivial group-by and the demo can show "7 sent, 2 disqualified, 1 failed (scrape)".

## Architectural Patterns

### Pattern 1: Stage functions with a shared `Context`, orchestrated by one runner

**What:** Each stage is `def run(ctx: Context, run: CompanyRun) -> <Output model>`. The runner assigns outputs onto `CompanyRun`, flushes `run.json`, and decides whether to continue (gate).
**When to use:** Always here. It is the cheapest structure that gives testability, resume, and a clean audit trail.
**Trade-offs:** Slightly more ceremony than a script of sequential calls; pays back at first debugging session. Not a framework, so no learning cost.

```python
STAGES = [("scrape", scrape.run), ("extract", extract.run), ("qualify", qualify.run),
          ("poc", poc.run), ("pain", pain.run), ("draft", draft.run), ("send", send.run)]

def process(domain, ctx) -> CompanyRun:
    run = CompanyRun(domain=domain, ...)
    for name, fn in STAGES:
        try:
            out = fn(ctx, run)                 # reads earlier fields off `run`
            setattr(run, FIELD[name], out)
        except GateStop as g:                  # expected control flow, not an error
            run.status = g.status; run.decisions.append(g.decision); break
        except Exception as e:                 # isolation boundary
            run.status, run.failed_stage, run.error = "failed", name, repr(e)
            log.exception(...); break
        finally:
            ctx.store.flush(run)               # always persist what we have
    return run
```

`GateStop` (qualify below threshold, Hunter returns no usable contact) is **expected** and maps to `disqualified` / `no_poc`; any other exception is `failed`. Keep these two paths separate in the summary; conflating them makes the demo confusing.

### Pattern 2: Bounded agent loop (manual tool loop, not auto function-calling)

**What:** Qualify runs in two parts: (a) an optional tool-using **research loop** that fills `missing_fields` in the profile, then (b) a **separate structured scoring call** with no tools. The loop is hand-written so you control iteration count, logging, and stop conditions.

**Why manual rather than SDK automatic function calling:** The `google-genai` SDK auto-executes Python functions passed as tools and by default caps at 10 remote calls. You can disable it with `AutomaticFunctionCallingConfig(disable=True)` and read `response.function_calls`, which is what you want to log each call and reason. There is a reported GitHub issue (python-genai, adk-python #4133) where `disable=True` behaved inconsistently in some setups, so **assert in code that no automatic call happened** (check the response for function-call parts you must execute) and verify on the first run. (MEDIUM confidence; from search snippets, confirm in Context7/official docs.)

**Why split loop and scoring:** On several Gemini models, combining tools (function calling) with a JSON `response_schema` in one request is not supported (newer models relax this). Splitting is portable across models, easier to debug, and gives two clean audit sections ("what I looked up" vs "how I scored"). Likewise, Gemini's built-in Google Search grounding historically cannot be mixed with custom function declarations in one request, so implement `search` as your own function (or drop it and rely on `fetch_url` only, see Open Questions).

**Loop design:**

```
state: profile (with missing_fields), steps=[], fetched_urls=set()
for i in range(MAX_ITERS):            # MAX_ITERS = 3 (hard cap; 4 absolute max)
    if not profile.missing_fields_that_matter: stop("no_missing_fields"); break
    resp = llm.run_tool_turn(system=qualify_agent_prompt, context=profile+rubric_gaps, tools=[fetch_url, search])
    if no function_call in resp:  stop("sufficient_data"); break   # model chose to finish
    call = resp.function_call
    guard: url already fetched? -> skip + log;  domain off-allowlist (not company domain or its trust/docs subdomains, or search result)? -> refuse + log
    result = tools.dispatch(call)      # tool errors are caught and returned to the model as text
    steps.append(AgentStep(i, call.name, call.args, reason=call.args["reason"], result_digest=result[:300]))
    profile = extract.merge(profile, result)   # small structured extract call on the new text
else:
    stop("max_iters")
```

Rules:
1. **Every tool declaration requires a `reason` string argument.** That is the cheapest way to get a "logged reason for each extra fetch" that is the model's own words, satisfying the PROJECT.md reliability constraint.
2. **Hard cap enforced in Python** (`for i in range(MAX_ITERS)`), never trusted to the prompt. 3 iterations is enough for a 1.5h demo and bounds cost to about 3 tool turns plus 3 small extract calls per company.
3. **Stop conditions are an enum** (`sufficient_data`, `max_iters`, `no_missing_fields`, `tool_errors`) stored on `Qualification.stop_reason`. The decision log prints it.
4. **Loop only runs when it can change the outcome:** skip it if the profile is already complete, or if the profile is so far from ICP that no missing field could flip the verdict (cheap pre-check, optional).
5. **Insufficient data after max iters does not auto-reject.** Score with what you have, mark low-evidence criteria with score 0 and `rationale="unknown"`, and let the threshold decide. A "borderline / insufficient data" band is a nice differentiator.
6. **Tool outputs are untrusted input.** Fetched page text is wrapped in delimiters and the system prompt says to treat it as data. (Prompt injection from scraped pages is a real risk in an agent that then writes email.)
7. **Do not let the loop call Hunter or Resend.** Tools are read-only web tools only. Side-effecting and quota-limited services are called only by deterministic stages.

### Pattern 3: Deterministic skeleton, LLM only where judgment is needed

**What:** Use an LLM for extract, scoring rationales, pain points, drafting. Use plain Python for: scraping, weighted math, the gate, Hunter title ranking, quota/caching, fact-validation checks, recipient override, dry-run.
**When to use:** Always in this domain; it is what makes the trail defensible and the 1.5h build tractable.
**Trade-offs:** Title ranking is a ranked keyword list (`["ciso","head of security","vp engineering","cto","head of it","compliance","founder"...]`) that is crude but explainable, which the brief values. The rank list belongs in `icp.yaml`.

### Pattern 4: Disk cache + idempotency by content key

**What:** A tiny `cache.get(ns, key) / cache.put(ns, key, value, ttl)` over JSON files.

| Namespace | Key | TTL | Why |
|-----------|-----|-----|-----|
| `hunter` | normalized domain | long (30d) or forever | Free tier = 25 searches/month; **never spend a search twice for the same domain.** Cache the raw API response (all emails) so ranking changes can be re-run for free. Cache "no results" too. |
| `pages` | sha256(url) | 24h | Re-runs while iterating on prompts are fast and free |
| `llm` (optional) | sha256(model + prompt + schema) | none | Makes demo re-runs deterministic and free; invalidates automatically when prompt changes. Only add if time permits. |

Idempotency for the batch: `runs/<run-id>/<domain>/run.json` is the checkpoint. `--resume <run-id>` skips domains whose status is terminal; `--force` ignores it. Simple version for the thin slice: skip a domain if a `sent` result exists in any prior run (guards against double-sending).

**Hunter budget guard:** `hunter.py` keeps a counter file (`.cache/hunter/_usage.json`, per calendar month) incremented only on real network calls. Refuse (raise `QuotaExceeded`, which maps to `no_poc` with reason) at a configurable ceiling (e.g. 20 of 25, leaving 5 for the demo). Also add a **`--hunter-budget N`** flag. Hunter's Account API (`/v2/account`) can report remaining searches and is not counted as a search (verify in docs). (MEDIUM.)

### Pattern 5: Dry-run as a mode of the *last* stage only

**What:** `--dry-run` runs everything (including Gemini and, by default, cached Hunter) and replaces **only** the Resend call. The `send` stage renders the exact payload (`from`, `to`, `subject`, `html/text`) to `runs/.../<domain>/email.eml.txt` and sets `SendResult.mode="dry_run"`.
**Why:** If dry-run skips earlier stages, it does not test anything. Dry-run that is identical up to the final HTTP call is the standard safe-test pattern.
**Safety invariant (this project):** `to` is **not a parameter of the stage**. It is read once from `OWNER_EMAIL` in config, and `send()` refuses to run if `to != OWNER_EMAIL`. The real PoC email is stored in `intended_recipient` and rendered in the email body header for demo ("Would have sent to: jane@acme.com") so the demo can show the personalization without risk. Make dry-run the **default**, with `--send` required to actually send; this prevents a stray run from burning quota or mail.
**Optional `--no-hunter` / `--hunter-cache-only` flag:** lets you rehearse the whole pipeline with zero Hunter spend using canned or cached contacts.

### Pattern 6: Failure isolation and per-company decision log

**Isolation (three layers):**
1. **Inner:** scrape tolerates per-page failures (timeouts, 403, non-HTML, oversized); each becomes `Page.status != "ok"`. Per-request timeout (10s) and size cap (1-2 MB).
2. **Stage:** each stage call wrapped in `try/except` by the runner (see Pattern 1); an exception marks only that company `failed` with `failed_stage`.
3. **LLM:** `llm.py` retries transient errors (429/5xx) with exponential backoff, max 2-3 attempts; schema-validation failure retries once with the validation error appended; then raises. A hard wall-clock budget per company (e.g. 120s) prevents one slow domain from stalling the batch.
Also: a **batch-level circuit breaker** for systemic failure (e.g. Gemini key invalid, 5 consecutive auth errors) so the run aborts loudly instead of marking every domain `failed` identically.

**Decision log (the audit trail):** Two artifacts per company, from the same data:
- `run.json`: machine-readable `CompanyRun` (every stage output, agent steps, scores, prompt hashes, model name).
- `decision.md`: generated from `run.json` by a pure renderer, never hand-built by the LLM, so it cannot drift from what happened.

```markdown
# acme.com  ->  SENT (dry-run)            run 2026-11-03T10-30  model gemini-2.5-flash
## 1. Why qualified  (score 3.8 / threshold 3.0)
| Criterion | Weight | Score | Rationale / evidence |
| SaaS product | 0.25 | 5 | "Acme is a B2B workflow platform" (acme.com/about) |
| Stage Series A-C | 0.20 | 4 | "Series B led by ..." (acme.com/blog/funding) |
| Compliance pressure | 0.30 | 3 | Trust page lists SOC 2 "in progress" (acme.com/security) |
Agent loop: stopped = sufficient_data after 1 extra fetch
  step 1: fetch_url acme.com/security — reason: "headcount and compliance status missing"
## 2. Why this person
Hunter returned 7 contacts; chose Jane Doe, "Head of Security" (matched ICP title rank 1). Confidence 94. Cache: miss (search 4 of 25 this month).
## 3. Pain points (grounded)
1. ... evidence: <quote, url>
## 4. Why this email
Hook: "<sentence>"; claims verified 3/3 against scraped quotes. Validation: passed (attempt 1).
## 5. Send
mode=dry_run  to=<owner>  intended=jane@acme.com
```

Disqualified companies still get a `decision.md` (arguably the more valuable demo content: "why we did NOT email this company").

## Data Flow

### Request Flow (per company)

```
domains.txt
   │  normalize (strip scheme/www/path, lowercase, dedupe)
   ▼
[scrape]  probe / , /about, /careers, /security|/trust, /pricing, /blog  (+ sitemap/nav link discovery if time)
   │  ScrapeResult(pages[kind,status,text])
   ▼
[extract] Gemini structured output -> CompanyProfile (+ missing_fields)
   │
   ▼
[qualify] ┌─ agent loop (<=3): fetch_url/search -> merge into profile
          └─ score call (structured, per-criterion 0-5 + evidence)
          Python: total = sum(w*s); qualified = total >= threshold
   │      └─ not qualified → GateStop("disqualified")  → write decision.md, next domain
   ▼
[poc]     cache? else Hunter Domain Search(domain, seniority=senior,executive, department filter, limit=10) 
          Python ranks by title list + confidence; verified-email preferred
   │      └─ none usable → GateStop("no_poc")
   ▼
[pain]    Gemini structured: 2 PainPoints from (PoC.position, profile, evidence quotes)
   ▼
[draft]   Gemini structured: EmailDraft (+claims[] with quotes)
          Python validator: first name present, each claim's quote found in scraped text (fuzzy substring), no banned phrases, length bound
          fail → 1 regenerate with validator feedback → fail again: mark failed(draft_validation) or send nothing
   ▼
[send]    dry_run -> write payload file;   --send -> Resend (from onboarding@resend.dev, to OWNER_EMAIL)
   ▼
runs/<id>/<domain>/{run.json,decision.md}  +  runs/<id>/summary.csv
```

### State Management

```
CompanyRun (one per domain, in memory)
   ├─ mutated only by the runner (stage outputs assigned, never by stages directly)
   ├─ flushed to run.json after every stage  (crash-safe partial trail)
   └─ rendered to decision.md at the end (or on failure)
Run-level state: summary rows list + hunter usage counter + circuit-breaker counter
No shared mutable state between domains (enables a later ThreadPoolExecutor with zero rewrite).
```

### Key Data Flows

1. **Evidence provenance flow:** `Page.text` -> `Signal(quote, source_url)` in extract -> cited in `CriterionScore.evidence` -> cited in `PainPoint.evidence` -> referenced in `EmailDraft.claims` -> verified against `Page.text` in the validator. One chain means every sentence of the email can be traced to a page. This is the architectural answer to "email validated against hallucinated facts" and the core defensibility story.
2. **Gate flow:** qualification result is the only thing that can spend Hunter quota or send mail. Disqualified companies cost zero Hunter searches. Order stages cheapest-first to protect the 25/month budget.
3. **Config flow:** `icp.yaml` -> qualify prompt (criteria text), qualify math (weights/threshold), poc ranking (titles), decision.md (printed). One source of truth for the rubric.

## Build Order (thin slice first, ~90 min)

Dependencies: models -> llm wrapper -> (stages in pipeline order) -> runner. Build **one real company end to end with the crudest version of every stage**, then deepen in order of demo value. Times are budgets, not promises.

| # | Slice | Deliverable | Depends on | Budget |
|---|-------|-------------|------------|--------|
| 0 | Skeleton | repo, `.env`, `models.py`, `llm.py` with `generate_structured()` smoke test, `audit.py` + `CompanyRun` writer | none | 10 min |
| 1 | **Thin end-to-end slice** (hardcode 1 domain) | scrape home+about only -> extract -> qualify with **no loop**, simple weighted score -> Hunter (cached) first-senior-contact -> single combined pain+draft -> `send` in dry-run printing payload | 0 | 25 min |
| 2 | Runner + isolation + CLI | `domains.txt` loop, per-domain try/except, `GateStop`, summary table, `--dry-run` default, `--send` real Resend to owner | 1 | 10 min |
| 3 | Real ICP rubric | `icp.yaml` (criteria, weights, threshold, title list); per-criterion scoring with evidence; Python total/gate | 1 | 10 min |
| 4 | **Bounded agent loop** | `tools.py`, manual tool loop, cap=3, `reason` arg, `stop_reason`, steps in log | 3 | 15 min |
| 5 | PoC depth | title ranking from `icp.yaml`, confidence/verified preference, Hunter cache + monthly counter, no-poc handling | 2 | 7 min |
| 6 | Split pain/draft + validator | separate pain stage; draft with `claims`; substring grounding check; one retry | 3,5 | 10 min |
| 7 | Decision log rendering | `decision.md` from `run.json`; run on 5-8 real domains incl. at least one disqualified and one scrape failure | all | 8 min |

Notes on ordering:
- **Dry-run + isolation (slice 2) come before the agent loop** because they make every later slice cheap and safe to test. The agent loop is the riskiest and most visible piece, but it only adds value once the baseline works. If time is tight, stage 4 degrades gracefully: the pipeline is already shippable without it, and the "loop disabled" path remains as a `--no-agent` flag.
- **Hunter caching goes in at slice 1**, not slice 5. The first real Hunter call must be written to cache immediately; every test call otherwise burns one of 25. Slice 5 is only about ranking and the counter. Test pipeline logic against a **fixture contacts JSON** instead of live Hunter until the PoC stage is stable.
- **Fix the demo domain set early.** Choose 6-8 domains (mix: clear fit, clear non-fit, hard-to-scrape, no Hunter results) at slice 1 and reuse. With Hunter at 25/month, the set must be at most about 10 live domains, with page and Hunter caches making re-runs free.
- **Leave a minute of buffer for a recorded dry-run output** (`runs/` sample committed) as demo insurance if an API is down.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 5-10 domains (the case) | Sequential loop, JSON files, no DB. Hunter free tier is the real cap (25 searches/month), not compute. |
| 100-1,000 domains | `ThreadPoolExecutor(4-8)` across domains (stages already share no state); per-provider rate limiter and Gemini 429 backoff; SQLite instead of JSON for run state; paid Hunter plan |
| 10k+ | Queue + workers, per-stage retry/dead-letter, proper scraper (headless browser, proxy), suppression list and CAN-SPAM/GDPR compliance, domain warmup and a verified sending domain. Out of scope. |

### Scaling Priorities

1. **First bottleneck:** Hunter quota (25/mo), solved by gating before Hunter, caching responses, and a usage counter.
2. **Second bottleneck:** Gemini free-tier rate limits (requests per minute and per day vary by model) and total latency: about 6-8 LLM calls per qualified company. Mitigate with a flash-tier model, backoff, and small page text caps (truncate to ~6-8k chars/page before extraction).

## Anti-Patterns

### Anti-Pattern 1: One giant "agent" prompt for the whole pipeline

**What people do:** Give the model all tools (scrape, Hunter, send) and a goal, let it decide.
**Why it's wrong:** Unbounded cost, no stable audit trail, quota burn on Hunter, and the model could attempt to send. Failures are undebuggable.
**Do this instead:** Deterministic pipeline; agency only in the qualify research loop, with read-only tools, a hard cap, and logged reasons.

### Anti-Pattern 2: Letting the LLM compute the score or the verdict

**What people do:** Ask "is this a fit? score 1-10".
**Why it's wrong:** Not reproducible, not defensible; the brief asks for a rubric and threshold.
**Do this instead:** LLM scores individual criteria with evidence; Python applies weights and threshold.

### Anti-Pattern 3: Passing raw dicts / free text between stages

**What people do:** Each stage returns whatever string the model produced.
**Why it's wrong:** Errors surface three stages later; "unknown" becomes a hallucinated value.
**Do this instead:** Pydantic models with `Optional` fields and `response_schema`; validate on every boundary; unknown stays `None`.

### Anti-Pattern 4: Dry-run that skips the pipeline, or a send stage that accepts a recipient

**What people do:** `if dry_run: return` at the top, or `send(to=poc.email)`.
**Why it's wrong:** Dry-run proves nothing; one wrong flag emails a real prospect (the brief explicitly forbids it).
**Do this instead:** Dry-run only replaces the final HTTP call; recipient comes from config only, with an assertion; real PoC email is recorded, not used.

### Anti-Pattern 5: Spending Hunter quota during development

**What people do:** Re-run the pipeline on every prompt tweak.
**Why it's wrong:** 25 searches vanish in 10 minutes.
**Do this instead:** Cache raw Hunter responses forever by domain; fixture contacts; gate before Hunter; usage counter with ceiling.

### Anti-Pattern 6: Catching exceptions per batch, not per domain (or swallowing silently)

**What people do:** One `try` around the loop, or `except: pass`.
**Why it's wrong:** One bad site kills the batch, or failures vanish and the summary lies.
**Do this instead:** Per-domain boundary, explicit `failed_stage` + error in `run.json`, summary counts by status, plus a systemic-failure circuit breaker.

### Anti-Pattern 7: Trusting scraped text as instructions

**What people do:** Paste page text into the prompt with no framing.
**Why it's wrong:** Prompt injection from a prospect's site can steer scoring or email content.
**Do this instead:** Delimit page text as data, instruct the model to ignore instructions inside it, keep tools read-only, and validate email claims deterministically.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Gemini (`google-genai`) | `llm.py` wrapper: `generate_structured(model_cls, system, user)` using `response_schema` (Pydantic) + JSON mime type; `run_tool_turn()` with function declarations and **automatic function calling disabled** | Do not mix tools and `response_schema` in one request (portable choice). Truncate inputs. Validate output with `model_validate_json`; retry once on failure. Confirm exact config names against current docs while coding. Log token usage per call. |
| Hunter.io Domain Search | `GET https://api.hunter.io/v2/domain-search?domain=...&seniority=senior,executive&limit=10` (also supports `department`, `job_titles`, `type`, `offset`) with API key | Free plan: 25 searches/month and small result limits (limit+offset above 10 reportedly errors on free; plan for 10 max). Invalid `seniority`/`department` values return 400 errors, so validate param values and handle `invalid_*`. Prefer `type=personal`. Cache the whole response. Treat 429 and 401 distinctly (quota vs key). (MEDIUM; snippet-level verification.) |
| Resend | `POST /emails` via `resend` SDK or `httpx`; `from: onboarding@resend.dev`, `to: [OWNER_EMAIL]` | onboarding sender only delivers to the account owner's email, consistent with the safety rule. Returns an id, store it in `SendResult`. Include text plus HTML body. Handle 4xx as `failed(send)`. |
| Target websites | `clients/http.py` shared `httpx.Client`: realistic UA, 10s timeout, redirect follow, size cap, content-type check | Many SaaS sites are JS-rendered or Cloudflare-protected; accept thin text and record `blocked`/`empty`. Do not build a headless browser in 1.5h. Respect robots.txt as a courtesy/defensible-practice note. |
| Search (for `search` tool) | Optional; a search API or Gemini grounding in a separate call | Undecided, see Open Questions. `fetch_url` alone covers most of the loop value. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| runner <-> stages | Function call: `stage.run(ctx, run) -> Model` | Runner is the sole orchestrator and sole writer of `CompanyRun` |
| stages <-> clients | Via `ctx` (injected) | Lets tests inject fakes (`FakeHunter`, `FakeLLM`) and enables `--hunter-cache-only` |
| stages <-> `llm.py` | Typed: pass Pydantic class in, get instance out | Only place that knows Gemini |
| qualify <-> tools | `tools.dispatch(name, args) -> str` | Tools read-only; return text capped to N chars; errors returned as strings |
| any stage <-> audit | `ctx.audit.add(Decision)` | Decisions are structured, rendering is separate |
| config <-> code | `icp.yaml` + `prompts/*.md` loaded at startup, hashed into `CompanyRun.prompt_hashes` | Reproducibility: you can say which rubric version made a decision |

## Open Questions / Flags for Roadmap

- **`search` tool provider:** no search API is listed in the stack. Options: only `fetch_url` (plus guessed URLs like `/security`, `/trust`, `/customers`) in the loop, or Gemini Google-Search grounding in a separate call, or a free search API. Recommend: ship `fetch_url` only in slice 4, add `search` if time remains. Needs a decision in the stack research.
- **Gemini model and rate limits:** pick one flash-tier model and confirm free-tier RPM/RPD, since ~6-8 calls per qualified company times ~8 domains is fine but retries during dev may not be. Phase-specific check.
- **Tools plus structured output compatibility** differs by model version; verified only at the level of "historically unsupported on several models", so test early in slice 0/4.
- **Hunter response shape and confidence/verification fields:** confirm against the official OpenAPI (hunter.io/openapi.json) when implementing slice 5; the search results did not document the confidence score fields.
- **Fuzzy claim validation threshold:** substring vs normalized-token overlap; start with normalized substring and loosen only if false failures appear.

## Sources

- google-genai Python SDK function-calling guide (automatic function calling, `maximum_remote_calls`, `AutomaticFunctionCallingConfig(disable=True)`): https://www.mintlify.com/googleapis/python-genai/guides/function-calling (MEDIUM, third-party mirror of official docs)
- python-genai issue tracker on AFC config behavior: https://github.com/googleapis/python-genai/issues/331 and https://github.com/google/adk-python/issues/4133 (MEDIUM; behavior reports, verify on current SDK version)
- AutomaticFunctionCallingConfig reference (JS SDK, same semantics): https://googleapis.github.io/js-genai/release_docs/interfaces/types.AutomaticFunctionCallingConfig.html (MEDIUM)
- Hunter OpenAPI spec (domain-search parameters: `domain`, `company`, `limit`, `offset`, `department`, `job_titles`, `seniority`; response fields `position`, `seniority`, `department`): https://hunter.io/openapi.json (MEDIUM; seen via search snippet, not fully read)
- Hunter Domain Search connector docs (type=personal|generic, free-plan limit+offset behavior): https://learn.microsoft.com/en-us/connectors/hunterip/ (LOW-MEDIUM, third-party)
- Pipeline pattern guidance (deterministic skeleton, typed contracts, bounded loops, dry-run to the last side effect, audit trail): established engineering practice; no single source. (HIGH as practice, not citation-backed)
- Project context: /Users/harshitsinha/Projects/sprinto-outreach/.planning/PROJECT.md

---
*Architecture research for: batch LLM outreach pipeline (Sprinto cold outreach)*
*Researched: 2026-11-03*
