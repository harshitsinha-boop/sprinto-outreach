# Feature Research

**Domain:** Automated B2B cold-outreach pipeline (AI SDR / outbound) selling Sprinto (compliance automation: SOC 2, ISO 27001, GDPR)
**Researched:** 2026-11-03
**Confidence:** MEDIUM overall. Tool landscape and cold-email benchmarks come from vendor blogs (directional, not controlled studies). The ICP rubric, title ranking and pain points are a reasoned synthesis from the brief, G2 reviewer data, SOC 2 buying-journey content and GTM guides, not Sprinto internal data. Treat weights as starting hypotheses to calibrate on the first 10-20 domains.

---

## 1. What AI outbound/SDR tools have (landscape)

| Tool | What it is | Features relevant to our 7 steps | Confidence |
|------|-----------|----------------------------------|------------|
| Clay | Research/enrichment/orchestration layer | Waterfall enrichment across 100+ providers, AI web-research agent per row, ICP scoring columns, signal triggers. Needs a separate sender. | MEDIUM |
| Apollo | Data + sequencing platform | ICP/lead scoring, buying signals (job changes, funding), AI-drafted emails, sequences. More co-pilot than autonomous rep. | MEDIUM |
| Artisan (Ava) | Autonomous AI BDR | Lead sourcing, research, personalised emails, built-in mailbox warm-up/deliverability, multichannel. | MEDIUM |
| 11x (Alice) | Autonomous AI SDR | End-to-end: prospect, research, write, send, handle replies, book meetings. Opaque, expensive pricing; reviewer complaints about quality. | MEDIUM |
| Origami Agents / Persana / TheirStack | Signal-based prospecting | Custom signals (e.g. "SOC 2 mentioned in job post", scan trust pages and badge placement), job-posting intent with confidence tiers. | MEDIUM |

**Takeaway:** the commercial tools win on volume plumbing (data waterfall, warm-up, sequencing, reply handling, CRM sync). None of that is in scope here. What they under-deliver, and what the case brief rewards, is defensibility: "why this company, why this person, why this email". That is our differentiation lane.

Observations that shape the feature list:
- Persana and Origami already treat "SOC 2 / trust page / security job posts" as signals. Scanning trust pages and job posts is validated practice, not novel.
- Signal-based (trigger) outreach is consistently reported to beat generic outreach (vendor-reported 5-18% vs 1-3%; one split test 9% trigger-based vs 1% token-based personalisation). Numbers are unverified but the direction is consistent across every source.
- Sources disagree on whether questionnaire activity is a buy signal or a deal already in review. Prospeo rates "SOC compliance" intent as useless (no visible methodology). Conclusion: score evidence of pursuit/pressure on the company's own pages, not generic intent data.

---

## 2. Feature Landscape

### Table Stakes (pipeline is broken or indefensible without these)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Batch run over a domain file, no per-step decisions | Core brief requirement; "at scale" | LOW | One CLI command; per-domain try/except so one failure never stops the batch |
| Multi-page scrape (home, about, careers, security/trust, pricing, blog) tolerant of failures | Raw signal source for everything downstream | MEDIUM | Try path list: `/security /trust /trust-center /compliance /careers /jobs /pricing /about /customers /blog`, plus `trust.<domain>` subdomain. Timeouts, 404s, JS-only pages = record "page_unavailable", never crash |
| Schema-validated structured extraction (Pydantic + Gemini structured output) | Everything downstream consumes it | MEDIUM | Every field nullable with `unknown` default; each evidence field carries `quote` + `source_url`. Unknown stays unknown |
| Weighted ICP score with written rubric + threshold | Brief requires "researched written rubric" | MEDIUM | See Section 3. Score computed in deterministic Python from extracted booleans, LLM only extracts, never "feels" a score |
| Bounded agent loop that fetches more when data is insufficient | Brief requirement | MEDIUM | Hard cap (3 iterations), each extra fetch logs a reason tied to a specific unknown signal |
| PoC lookup via Hunter Domain Search + title ranking | Brief requirement | MEDIUM | See Section 4. Cache per domain on disk (25 searches/month). Free tier: `limit + offset` must be <= 10 |
| Skip-and-log when no suitable PoC found | Naming a random person is worse than skipping | LOW | Reason logged: "no email with ranked title / verification" |
| Two pain points per persona grounded in role + scraped evidence | Brief requirement | LOW-MEDIUM | Pick from persona pain library, anchored by at least one scraped fact |
| Personalised email addressed by first name, specific hook | Core deliverable | MEDIUM | Section 5 rules |
| Hallucination guard on the draft | "Validated against hallucinated facts" | MEDIUM | Every factual claim in email must map to an extracted evidence item or a whitelisted Sprinto claim; second LLM/structured pass or string check; fail = regenerate once then skip |
| Send via Resend with `--dry-run`, `to:` hardcoded to own email | Safety constraint | LOW | Default to dry-run; real-recipient address printed in log as "would have sent to" |
| Per-company decision log (JSON/markdown) | Core Value: defensible trail | LOW-MEDIUM | One record per domain: score breakdown, loop reasons, PoC candidates + why chosen, pain points, email + evidence map |
| Secrets in `.env`, not committed | Safety constraint | LOW | `.gitignore` + `.env.example` |

### Differentiators (where this build competes; align with Core Value)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Score interval (min with unknowns=0, max with unknowns=full weight) driving the agent loop | Loop fetches only when an unknown signal could flip the decision; makes "why did it fetch more" provable | MEDIUM | `qualify` if min >= 60, `reject` if max < 45, else loop targeting the highest-weight unknown signals |
| Evidence-quoted score breakdown ("+20: trust page says 'SOC 2 Type I in progress' [url]") | Demo-able, human-checkable, no black-box score | LOW-MEDIUM | Falls out of extraction schema carrying quote + URL |
| Hook-to-evidence provenance map in the log | Proves the hook is real; the strongest answer to "can you defend this email" | MEDIUM | Email JSON: `{hook_claim, evidence_id, quote}` |
| Persona-specific hook angle (founder vs CTO vs security lead vs GRC) | Different pain, different first line; most AI SDRs use one template | MEDIUM | Prompt includes persona card (Section 4) |
| Competitor/incumbent detection (Vanta, Drata, Secureframe, SafeBase, Conveyor, Thoropass, Scytale, Oneleet badges/links on trust page) | Avoids pitching someone who already bought; flips pitch to "switch" angle | MEDIUM | Detect by text/links/images on security/trust pages. Specific hostname patterns are unverified (LOW); string-match brand names instead |
| Multi-framework gap angle (has SOC 2, lacks ISO 27001/GDPR) | Opens expansion hook for already-certified firms | LOW-MEDIUM | Optional; only if time allows |
| Calibration run summary (score distribution, qualify rate per rubric version) | Lets the demo show the rubric is tunable | LOW | Print table at end of batch |
| Caching of scrape + Hunter + LLM outputs | Rerunnable demo, protects 25-search quota, cheap iteration | LOW-MEDIUM | Disk cache keyed by domain + content hash |

### Anti-Features (do NOT build)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Sending to real prospects | "Real" outbound | Brief hardcodes own address; legal/reputation risk; onboarding@resend.dev can't deliver elsewhere anyway | Log "would have sent to {prospect}" in dry-run |
| Follow-up sequences, reply handling, CRM sync | Standard in 11x/Artisan | Out of brief; large surface; 58% of replies come from email 1 so first email is where value is | Defer to v2 |
| Mailbox warm-up / deliverability engine | Artisan has it | Irrelevant with Resend sandbox sender | Keep one short plain-text-ish email |
| Web UI / dashboard | Looks impressive | Burns the 1.5h budget | Markdown/JSON decision log + console table |
| LinkedIn scraping / personal-signal hooks (posts, hobbies) | "Deeper personalisation" | ToS risk, creepy, sources call compliment openers hollow and AI-detectable | Professional signals only: company pages, job posts, trust page |
| LLM-judged free-form "fit score" | Fast to write | Not reproducible or defensible; drifts between runs | LLM extracts facts, Python computes weighted score |
| Unbounded agent loop / open-ended web crawling | "More data is better" | Cost, latency, nondeterminism, hard to demo | Cap 3 iterations, allowlist of fetch targets (same-domain pages, one news search) |
| Guessing emails / patterns when Hunter returns none | Increase coverage | Bounces, wrong person, undermines "real named person" | Skip + log |
| Hunter search before qualification | Simpler ordering | Burns 25-search quota on rejects | Qualify first, Hunter only for qualified domains |
| Invented social proof / stats in the email | Persuasion | Fails hallucination guard; credibility | Whitelist of verified Sprinto claims only |
| A/B testing infra, send-time optimisation | Growth-tool staple | No volume to test | None |

---

## 3. Proposed ICP scoring rubric (Sprinto)

### 3.1 Who Sprinto actually sells to (evidence)

- Brief: SaaS, typically Series A-C, preparing for an audit or pressured by enterprise customers to certify. (HIGH, given)
- G2 reviewer mix for Sprinto: ~56% small business (<=50 employees), ~42% mid-market (51-1,000), ~1% enterprise; Vanta is similar (~58%/40%). So the sweet spot skews small, 20-300 employees. (MEDIUM, reviewer demographics only)
- Sprinto positions on first-time SOC 2/ISO programs, pre-configured to the customer's stack; case studies include companies that start compliance before the first enterprise customer. (MEDIUM)
- Customer motivation in reviews: win enterprise deals, pass vendor security assessments, cut manual evidence work. (MEDIUM)
- Typical SOC 2 journey: enterprise prospect sends questionnaire, last question asks for SOC 2 report; startup gets Type I (4-8 weeks) to unblock the deal then Type II (observation window months). Programs commonly start 3-6 months before a big deal and take 3-18 months. Year-one cost $25-60k plus 100-200 internal hours landing on engineering/IT, which at a 10-person company means a founder. (MEDIUM, secondary sources)

### 3.2 Hard gates (applied before scoring; fail = reject with logged reason)

| Gate | Rule |
|------|------|
| G1 Business model | Must sell software/SaaS/platform to businesses (B2B). Reject B2C apps, agencies, consultancies, marketplaces for consumers, nonprofits, hardware-only |
| G2 Reachable | Domain loads and yields at least homepage text. If unreachable, mark `insufficient_data` (not reject) and let loop retry once |
| G3 Size ceiling | Reject if confidently > 1,000 employees (G2 shows ~1% enterprise; not Sprinto's lane). Unknown headcount passes |

### 3.3 Weighted signals (positives sum to 100)

| # | Signal | Where to find it | Weight | Scoring rule |
|---|--------|------------------|--------|--------------|
| **A. Firmographic fit (30)** | | | | |
| A1 | B2B SaaS / software product with customer data (API, integrations, accounts, PII) | Home, product, pricing pages | 10 | Clear B2B SaaS = 10; B2B tech-enabled service = 4; unclear = 0 |
| A2 | Stage: seed to Series C, or funded within ~24 months | About, blog/press, "backed by" logos, footer; loop: news search | 10 | Series A-C = 10; Seed = 7; bootstrapped/profitable with team >30 = 5; Series D+/public = 2; unknown = 0 |
| A3 | Headcount 20-300 | About/team page, careers page count, LLM estimate with quote | 10 | 20-150 = 10; 151-300 = 7; 10-19 = 5; 301-1000 = 3; <10 or unknown = 0 |
| **B. Compliance-pressure evidence (50)** | | | | |
| B1 | Public statement of pursuing/planning SOC 2, ISO 27001 or similar ("in progress", "Type I", "coming soon", "audit underway", "request our roadmap") | Security/trust page, footer, docs, blog, job posts | 20 | Explicit "in progress/planned" = 20; Type I only (no Type II) = 15; GDPR/"secure by design" mentioned with no attestation = 8; nothing = 0 |
| B2 | Enterprise/upmarket motion | Customer logos (known mid/large brands), pricing page with "Enterprise" tier, SSO/SAML/SCIM/audit-log features, "Contact sales", enterprise AE/CS hiring | 12 | 3+ indicators = 12; 2 = 8; 1 = 4; none = 0 |
| B3 | Security / GRC / compliance / IT hiring, or SOC 2 / ISO 27001 mentioned in any job description | Careers/jobs page (Greenhouse, Lever, Ashby, etc. links) | 10 | Security/GRC/Compliance role open = 10; JD mentions SOC 2/ISO 27001 = 7; IT/DevOps role only = 3; none = 0 |
| B4 | Security page exists but is thin (no downloadable report, no trust-center platform, short bullet list) | Security/trust page | 8 | Thin page or pure marketing "bank-grade security" = 8; no security page at all = 4 (enterprise buyers will ask; weaker evidence); full trust center with reports = 0 |
| **C. Timing and exposure (20)** | | | | |
| C1 | Recent funding or expansion event (last 12 months) | Blog/press, about page, loop: news fetch | 10 | Round in last 12 months = 10; 12-24 months = 5; unknown = 0 |
| C2 | Regulated or high-trust vertical, or EU/international customers | Product copy: fintech, health, HR/payroll, data infra, AI/LLM with customer data, EU presence, GDPR/DPA pages | 5 | Strong = 5; partial = 2 |
| C3 | Security-review artefacts: DPA page, sub-processor list, "request security documentation" form, security questionnaire/VSA mentions | Legal/trust pages | 5 | Present = 5 (indicates buyers are already asking) |

### 3.4 Penalties (applied after summing; subtract, floor at 0)

| Penalty | Where | Points | Reason |
|---------|-------|--------|--------|
| Already holds SOC 2 Type II and ISO 27001 | Trust page, badges | -30 | Not in the "first audit" moment; consider expansion angle only |
| Trust center on a competitor platform (Vanta, Drata, Secureframe, Thoropass, Scytale, Oneleet badge/link) | Trust page | -25 (and set `incumbent` field) | Already bought a tool; a switch pitch needs a different hook |
| Holds SOC 2 Type II only (no ISO, no competitor visible) | Trust page | -15 | Possible ISO/GDPR expansion; lower urgency |
| Named CISO and dedicated GRC team visible | About/team/careers | -8 | Mature program; still could buy but not first-timer |
| Confidently >300 employees | About | handled by A3 weights | |

### 3.5 Threshold and unknown handling

- Compute `score_min` (unknown signals = 0) and `score_max` (unknown signals = full weight, penalties unchanged).
- `score_min >= 60` -> QUALIFY.
- `score_max < 45` -> REJECT.
- Otherwise -> LOOP: choose the highest-weight unknown signals, fetch targeted pages (e.g. `/security` variants, `trust.<domain>`, `/customers`, careers subpages, a funding news search), re-extract, recompute. Max 3 iterations. After cap, decide on `score_min` and log `decided_with_unknowns=[...]`.
- Suggested starting threshold 60 with a gray band 45-59. Calibrate on 10-20 domains including 2-3 obvious fits (e.g. a funded B2B SaaS with "SOC 2 in progress") and obvious rejects (B2C app, already-Vanta'd company). Tune weights, not thresholds, when calibrating.
- Illustrative archetypes:
  - Series A B2B SaaS, "SOC 2 Type I in progress", enterprise plan, hiring security engineer: ~10+10+10 + 20+8+10+0 + 10+3+0 = ~81 -> QUALIFY.
  - Seed SaaS, thin security page, no hiring data, unknown funding: A=10+7+10 =27, B4=8, B2=4 -> min ~39, max ~80 -> LOOP.
  - 400-person SaaS with SafeBase trust center showing SOC 2 Type II and ISO 27001: heavy penalties -> REJECT.

### 3.6 Extraction schema fields the rubric requires (feeds Step 2)

`business_model`, `product_summary`, `headcount_estimate` (+quote), `stage_or_funding` (+date, quote), `customers_named[]`, `enterprise_indicators[]` (sso, enterprise_plan, contact_sales, etc.), `compliance.mentions[]` (framework, status: in_progress|type1|type2|certified|none|unknown, quote, url), `trust_center` (exists, platform_brand, has_reports), `incumbent_tool` (name|null), `hiring.roles[]` (title, security/grc/it flag, mentions_soc2), `regulated_vertical`, `eu_presence`, `security_artifacts[]`. Every value nullable; `unknown` is a first-class value.

---

## 4. PoC selection

### 4.1 Title priority by company size (headcount from Step 2)

Hunter Domain Search returns `position`, `seniority`, `department`, `confidence`, `verification.status`, `decision_maker`, `linkedin`. On the free tier `limit + offset <= 10`, so fetch a single page of 10 and rank locally. Pass `seniority=senior,executive` and `required_field=full_name,position` if results are not empty; fall back to unfiltered. Do not use generic (`type=generic`) addresses.

**Small (about 10-50 employees): founders own it, and engineering does the work**
1. CTO / Co-founder and CTO / Technical Co-founder
2. CEO / Founder / Co-founder (if no technical founder surfaced)
3. VP Engineering / Head of Engineering
4. COO / Head of Operations / Head of IT

**Mid (about 50-200)**
1. Head of Security / Director of Security / CISO (if present)
2. VP Engineering / Head of Engineering / Director of Engineering
3. Head of IT / IT Manager / Director of IT
4. Head of Compliance / GRC Manager / Compliance Manager
5. CTO
6. COO

**Larger (about 200-1,000)**
1. CISO / Head of Security / VP Security
2. Head of GRC / Director of Compliance / Compliance Manager / Security Compliance Lead
3. Head of IT / VP IT
4. VP Engineering / CTO
5. Senior Security Engineer / Security Manager (only if nothing above)

**Rules**
- Final PoC score = title rank score x seniority bonus x (Hunter confidence >= 80 or verification = valid). Prefer `verification.status = valid`; accept `accept_all` with confidence >= 80; reject `unknown`/low-confidence unless it is the only candidate (then log risk).
- Exclude: sales, marketing, HR/recruiting, customer success, finance, interns, generic mailboxes, "advisor", "board".
- Tie-breakers: `decision_maker = true`, executive seniority, presence of `linkedin`.
- If a CISO exists in a <50-person firm, still pick CTO/founder only if CISO is absent; a real security lead outranks founders at any size.
- Log the top 3 candidates with scores and the reason the winner won.
- Confidence: MEDIUM. Title-by-size ranking is a defensible hypothesis from how SOC 2 work is distributed (founder/engineering at small, security/GRC at larger), not measured Sprinto buyer data. Sources describing GRC buying committees (CRO/CFO budget, Head of GRC champion, IT security evaluator) target mid-market regulated firms, not Sprinto's startup core.

### 4.2 Persona pain library (pick two per email: one business pain + one workload pain)

| Persona | Pain 1 (business) | Pain 2 (workload) | Hook angle |
|---------|-------------------|-------------------|------------|
| Founder / CEO | Enterprise deals stall or die at the security review ("do you have SOC 2?"); revenue blocked by a certificate | Founder time absorbed by questionnaires and chasing auditors/engineers instead of selling | The deal-blocking moment; speed to a first report |
| CTO / VP Eng / Head of Eng | Roadmap slips because engineers do evidence collection, access reviews, policy writing | Months-long Type II observation window with controls that must hold continuously; auditor back-and-forth | Engineering hours reclaimed; automated evidence from cloud/GitHub/HRIS |
| Head of Security / CISO | Proving posture to customers repeatedly (questionnaires, trust requests) | Manual, screenshot-based evidence; controls drifting between audits; spreadsheet tracking | Continuous monitoring instead of audit sprints; one source of truth |
| Head of IT | Onboarding/offboarding, device (MDM), access review evidence scattered | Vendor risk and policy acknowledgement chasing across teams | Automating access reviews and device/user checks |
| GRC / Compliance lead | Re-mapping the same controls across SOC 2, ISO 27001, GDPR | Audit prep sprints dominated by evidence chasing (one cited fintech team spent ~37% of time on this) | Cross-framework control mapping, fewer audit sprints |

Pain points must be tied to a scraped fact (e.g. "hiring a security engineer", "Type I in progress", "enterprise plan with SSO") or the email must not assert them as fact. Phrase as an informed inference, not a claim about their internals.

---

## 5. What makes a cold-email hook reply-worthy

Evidence strength: MEDIUM. Sources are mostly vendor blogs (Instantly 2026 benchmark: ~3.4% average reply, elite 10%+ with <80 words, 58% of replies come from email 1; Prospeo split test 1% token personalisation vs ~9% trigger-based; SyncGTM case 3% -> 6% after cutting from 141 to <56 words; Belkins: 2-4 word subjects had highest opens). Directionally consistent; exact numbers unreliable.

**Rules to encode in the prompt and validator**

1. **One trigger, verifiable, from their own pages.** Opener names a single concrete fact with a short quote: "Your trust page says SOC 2 Type I is in progress", "You're hiring a Security Engineer", "Your pricing page now lists an Enterprise plan with SSO". Do not stack signals.
2. **Hook -> pain -> proof -> ask.** Sentence 1 trigger; sentence 2 translate to that persona's pain (Section 4.2); sentence 3 one proof point from the Sprinto whitelist; one small ask.
3. **Length 50-90 words, plain text, no links or images, no attachments.** Under 80 correlates with elite reply rates; first-touch emails are read on mobile.
4. **Subject: 2-5 words, lowercase, internal-sounding, specific.** Examples: "soc 2 timeline", "your trust page", "security hire". Avoid salesy phrasing, the word "free", Sprinto's name, emojis. Sources conflict on including company name; skip it.
5. **CTA is interest-based and tiny:** "Worth a look?", "Open to a 10-minute walkthrough?" One question, not "30 minutes Thursday?".
6. **Trigger-based beats generic compliments.** No "loved your post", no "congrats on the round" as sole hook (generic, AI-detectable). A funding mention is acceptable only as context for a pressure the persona recognises (for example enterprise deals after a round), and only if the funding fact is in extracted evidence.
7. **Persona-specific language.** Founder: deal speed. CTO: engineering hours. Security: continuous evidence. GRC: control mapping.
8. **No fabricated facts.** Every sentence about the prospect maps to an evidence ID. Sprinto claims are limited to a whitelist file (product description plus anything verified, such as G2 rating ~4.8 with ~1,500+ reviews; confirm before using). No made-up customer names or percentages.
9. **Do not assert they need SOC 2 if they already have it.** Branch the hook (expansion/ISO, or skip) when `compliance.status = type2`.
10. **Honest inference language.** "Looks like you're heading toward..." rather than "You are struggling with...".
11. Sign off with a real sender name placeholder from config; no fake urgency, no "following up".

**Validator checks (cheap, deterministic where possible):** word count 50-90, subject word count <= 6, exactly one question mark in body, name present and equals PoC first name, each prospect-fact sentence has an evidence ID, no banned phrases ("hope this finds you", "quick question", "game-changer", "revolutionary"), no URLs, no digits not found in evidence or whitelist.

**Example hook shape (CTO at a Series A SaaS with "SOC 2 in progress" on trust page):**
> Subject: soc 2 timeline
> Hi Priya, saw your trust page lists SOC 2 as in progress. That usually lands on engineering: evidence pulls, access reviews, policy writing, for months of the observation window. Sprinto automates that evidence from your cloud and code stack so the audit stops competing with your roadmap. Worth a look?

---

## Feature Dependencies

```
Domain file loader
    └──requires──> Per-domain error isolation + disk cache
                       └──requires──> Scraper (multi-page, failure tolerant)
                                          └──requires──> Schema-validated extraction (Gemini structured output)
                                                             └──requires──> ICP scorer (deterministic, interval min/max)
                                                                                └──requires──> Bounded agent loop (reads unknowns from scorer)
                                                                                └──gates──>    Hunter PoC lookup (qualified only)
                                                                                                    └──requires──> Title ranker + persona detection
                                                                                                                       └──requires──> Pain-point picker (persona library + evidence)
                                                                                                                                          └──requires──> Email drafter
                                                                                                                                                             └──requires──> Hallucination/format validator
                                                                                                                                                                                └──requires──> Resend sender (dry-run default)

Decision log ──consumes──> every stage (write incrementally, not at the end)
Evidence-quote fields in schema ──enables──> score breakdown, hook provenance, hallucination guard
Competitor/incumbent detection ──enhances──> ICP scorer penalties and hook branching
Calibration summary ──enhances──> ICP scorer (tune weights)
Hunter-before-qualify ──conflicts──> Hunter quota (25/month)
Unbounded loop ──conflicts──> repeatability and defensibility
```

### Dependency Notes

- **Extraction schema must carry `quote` + `source_url` per evidence item:** this single decision enables score breakdown, hook provenance, and hallucination validation. Retrofitting it later is costly.
- **Scorer must expose unknown signals:** the loop's targeting logic needs the ranked list of unknown signals and their weights.
- **Hunter lookup requires headcount from extraction:** title ranking depends on size band; if headcount is unknown, use the mid band.
- **Persona detection precedes pain/hook selection:** drafting before PoC selection wastes calls and produces a generic email.
- **Decision log is cross-cutting:** write per-stage so a crash still leaves a partial trail.
- **Hunter caching must precede any real run:** the 25/month quota makes the cache a table-stakes dependency of PoC lookup.

---

## MVP Definition

### Launch With (v1, thin end-to-end slice in ~1.5h)

- [ ] Domain file loader + per-domain error isolation + dry-run default
- [ ] Scraper for homepage, `/security` or `/trust`, `/careers`, `/pricing`, `/about` (blog/customers if time)
- [ ] Pydantic extraction with evidence quotes and unknown-as-first-class
- [ ] Deterministic rubric (Section 3) with gates, score breakdown, threshold 60
- [ ] Bounded loop (cap 3) with reason log, driven by unknown signals
- [ ] Hunter lookup with disk cache and title ranking (Section 4.1)
- [ ] Persona pain library + 2 pains picker
- [ ] Email draft with validator (word count, name, evidence map, no URLs)
- [ ] Resend send with `to:` hardcoded and `--dry-run`
- [ ] Per-company decision log (JSON + readable markdown)

### Add After Validation (v1.x)

- [ ] Score interval (min/max) loop targeting if v1 uses a simpler "if unknown, fetch" rule
- [ ] Competitor/incumbent detection and hook branching
- [ ] Calibration summary table across the batch
- [ ] Second-pass LLM fact-checker on drafts
- [ ] Multi-framework expansion angle for already-certified companies

### Future Consideration (v2+)

- [ ] Real recipient sending with verified domain (SPF/DKIM/DMARC)
- [ ] Follow-up sequence (email 2 with a new angle is where one source saw the highest reply rate)
- [ ] CRM sync and reply handling
- [ ] Multiple contacts per account (buying committee: founder/CTO plus security lead)
- [ ] Paid signal sources (job-posting intent APIs, funding databases)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Scrape + structured extraction with evidence quotes | HIGH | MEDIUM | P1 |
| Deterministic weighted ICP score + threshold | HIGH | MEDIUM | P1 |
| Decision log with score breakdown | HIGH | LOW | P1 |
| Hunter lookup + cache + title ranking | HIGH | MEDIUM | P1 |
| Email draft + hallucination validator | HIGH | MEDIUM | P1 |
| Resend send + dry-run + hardcoded recipient | HIGH | LOW | P1 |
| Bounded agent loop with logged reasons | HIGH | MEDIUM | P1 |
| Persona pain library | MEDIUM | LOW | P1 |
| Hook provenance map | HIGH | LOW | P1 (free if schema carries quotes) |
| Score-interval loop targeting | MEDIUM | MEDIUM | P2 |
| Incumbent/competitor detection | MEDIUM | MEDIUM | P2 |
| Calibration summary | LOW | LOW | P2 |
| Multi-framework expansion angle | LOW | LOW | P3 |
| Follow-ups / CRM / reply handling | LOW (out of brief) | HIGH | P3 |

**Priority key:** P1 must have; P2 should have; P3 later.

---

## Competitor Feature Analysis

| Feature | Clay / Apollo | Artisan / 11x | Our Approach |
|---------|---------------|---------------|--------------|
| Prospect research | Enrichment waterfall plus AI research agent | Autonomous research per lead | Scrape 6 pages, schema extraction with quotes, bounded loop |
| ICP scoring | Scoring columns / lead score, often LLM-judged | Opaque | Written weighted rubric, deterministic, score breakdown with evidence |
| Signals | Funding, job changes, hiring signals | Mostly baked-in | Compliance-specific signals from trust page, careers, pricing |
| Contact finding | 100+ provider waterfall / Apollo database | Built-in database | Hunter Domain Search, ranked by title and size band, cached |
| Personalisation | Template plus AI first line | AI-written, quality complaints | Persona-specific hook grounded in an evidence ID |
| Fact checking | Rare | Rare / reviewer complaints about quality | Mandatory validator and provenance map |
| Sending / deliverability | Sequencing (Apollo) / external sender (Clay) | Built-in warm-up and sequences | Resend, single send, dry-run default |
| Auditability | Row-level data, no "why" narrative | Little | Per-company decision log (core differentiator) |

---

## Open Questions / Calibration Needs

- Weights and threshold are untested; run 10-20 real domains and tune weights before the demo.
- Competitor trust-center hostname/badge patterns are unverified (LOW); use brand-name string match on trust pages for v1. Vanta's trust center is reportedly powered by SafeBase (now part of Drata), so a SafeBase link does not uniquely identify a competitor customer.
- Hunter free-tier behaviour: `limit + offset <= 10` confirmed in API docs; per-search credit cost and whether a repeated query is free within a billing period should be verified in the Hunter dashboard (docs say repeat queries return `X-Credits-Used: 0`).
- Sprinto proof-point whitelist must be provided or verified (the brief PDF could not be rendered here because `pdftoppm` is not installed; re-read it for any ICP/claim wording that overrides this document).
- Funding/stage is often not on a company's own site; expect it to be `unknown` for many domains, which is why the loop and interval scoring matter.

---

## Sources

- Project brief context: `/Users/harshitsinha/Projects/sprinto-outreach/.planning/PROJECT.md` (HIGH; the PDF brief itself could not be read)
- Hunter.io API docs, Domain Search parameters/response fields/free-tier pagination limit: https://hunter.io/api-documentation/v2#domain-search (HIGH)
- G2 Sprinto/Vanta/Hyperproof reviewer company-size mix via https://www.g2.com/compare/sprinto-inc-vs-vanta and https://www.g2.com/compare/hyperproof-vs-sprinto-inc (MEDIUM, reviewer demographics)
- Sprinto positioning and case studies: https://sprinto.com/de/soc-2/framework/ , https://www.casestudies.com/company/sprinto , https://sprinto.com/watch-infinite-data-case-study/ (MEDIUM)
- SOC 2 buying journey and ownership at startups: https://www.complyjet.com/blog/soc-2-for-startups , https://www.decryptiondigest.com/blog/soc2-type2-first-time-startup-guide , https://soc2auditors.org/soc-2-auditors-startups/ (MEDIUM, secondary)
- Signal-based selling and SOC 2/trust-page/job-post signals: https://firstsales.io/raw/hiring-signal-outbound.md , https://persana.ai/flows/redirect-soc2 , https://app.origamiagents.com/blog/how-to-identify-qualified-prospects-custom-signals , https://theirstack.com/en/buying-intents , https://www.securitypalhq.com/blog/5-truths-about-security-questionnaire-automation (MEDIUM-LOW, vendor content; sources conflict on questionnaire as a signal)
- Compliance/GRC buyer personas and pains: https://moderninbound.com/blog/cold-email-for-compliance-and-grc-saas (LOW-MEDIUM, GTM-agency opinion, mid-market regulated focus)
- Cold email benchmarks and structure: https://prospeo.io/s/cold-email-personalization , https://instantly.ai/blog/how-to-improve-your-cold-email-reply-rate , https://www.martal.ca/cold-emailing-statistics , https://www.cleverly.co/blog/trigger-based-cold-email , https://syncgtm.com/blog/personalized-cold-email-templates (MEDIUM-LOW, vendor-reported figures)
- AI SDR tool landscape: https://guptadeepak.com/tools/top-5-ai-sales-sdr-tools-2026/ , https://www.dashly.io/tools/comparisons/artisan-vs-11x/ , https://blog.gojiberry.ai/blog/ai-sdr-tools (MEDIUM-LOW, comparison blogs)
- Trust-center platform landscape (SafeBase acquired by Drata; Vanta trust center powered by SafeBase): https://help.drata.com/en/articles/15453390-safebase-trust-center-integration-in-drata-tprm , https://conveyor.com/blog/best-trust-center-software (MEDIUM)

---
*Feature research for: automated B2B cold-outreach pipeline (Sprinto)*
*Researched: 2026-11-03*
