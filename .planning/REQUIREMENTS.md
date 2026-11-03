# Requirements: Sprinto Cold Outreach Pipeline

**Defined:** 2026-11-03
**Core Value:** For a qualified company, a personalised email addressed to a real named person with a specific, evidence-based hook lands in the inbox, and every decision behind it can be defended from a logged trail.

## v1 Requirements

### Foundation

- [x] **FND-01**: `.gitignore` and `.env.example` exist before any secret file, and no API key is ever committed or logged
- [x] **FND-02**: User can configure Gemini, Hunter and Resend keys, the owner email and model IDs from a local `.env`
- [x] **FND-03**: All Gemini calls go through one wrapper with retry and backoff on 429 and 5xx, a repair retry on schema failure, and response caching
- [x] **FND-04**: A smoke test confirms Gemini structured output, one Gemini function-calling round trip, one Hunter call and one Resend send to the owner address work with the configured keys

### Runner

- [x] **RUN-01**: User can run the pipeline on a text file of domains with one command and no decisions between steps
- [x] **RUN-02**: A failure on one domain is recorded and does not stop the batch, and a systemic failure such as a bad API key aborts the batch
- [x] **RUN-03**: Dry-run is the default, and a live send needs an explicit `--send` flag
- [x] **RUN-04**: A summary table shows each domain's outcome (qualified, disqualified, insufficient data, no contact, rejected draft, sent, failed)

### Scrape and Extract

- [ ] **SCR-01**: For each domain the system fetches the homepage plus about, careers, security or trust, pricing and customers pages, with timeouts, size caps and robots.txt respected
- [ ] **SCR-02**: A page with too little usable text or a block signature is marked unavailable and never passed to the LLM
- [ ] **EXT-01**: The system extracts schema-validated company data (what it sells, B2B or not, stage, headcount, compliance mentions, hiring signals, enterprise customers)
- [ ] **EXT-02**: Every extracted field is nullable, and every evidence item carries a quote and source URL, with the quote checked as a substring of the fetched text
- [ ] **EXT-03**: Scraped text is treated as untrusted, delimited in prompts, and never given side-effect tools

### Qualification

- [ ] **QUA-01**: A written ICP rubric (hard gates, weighted signals, penalties, threshold) is stored as data and its hash is logged with every run
- [ ] **QUA-02**: The LLM extracts facts and Python computes the score, so the same evidence always gives the same score
- [ ] **QUA-03**: The score is computed as a minimum (unknowns as 0) and maximum (unknowns at full weight), qualifying, rejecting or triggering the agent loop accordingly
- [ ] **QUA-04**: When data is insufficient, an agent loop fetches more pages for at most 3 iterations, from same-domain URLs only, with a logged reason per fetch and a stop-reason enum
- [ ] **QUA-05**: A disqualified or insufficient-data company shows its score breakdown and costs no Hunter credit

### Point of Contact

- [ ] **POC-01**: Hunter Domain Search runs only for qualified companies, with one filtered query per domain and results cached to disk including empty ones
- [ ] **POC-02**: The PoC is chosen by deterministic title ranking by company-size band, and the top candidates and the reason for the choice are logged
- [ ] **POC-03**: If Hunter returns no named contact, the company is logged as no contact and no email is drafted
- [ ] **POC-04**: A persistent budget counter prevents exceeding the Hunter allowance, and tests use cached or fixture data unless live Hunter is requested

### Pain Points and Email

- [ ] **DRF-01**: The system identifies the two most likely pain points for the chosen person, each tied to their role and an evidence item
- [ ] **DRF-02**: The email is addressed to the person by name, is 50 to 90 words of plain text, and has one evidence-cited hook and one small ask
- [ ] **DRF-03**: A deterministic validator rejects an email with a name that differs from Hunter's, an unsupported number or claim, a URL, or a banned generic phrase, and allows one regeneration
- [ ] **DRF-04**: Only whitelisted Sprinto claims may appear in an email

### Send

- [ ] **SND-01**: The email is sent through Resend from onboarding@resend.dev, with the recipient forced to the owner email inside the send function
- [ ] **SND-02**: The subject shows the intended recipient, and the send checks for a returned message id and uses an idempotency key
- [x] **SND-03**: A dry-run prints the exact payload that would be sent without calling Resend

### Decision Log and Demo

- [x] **LOG-01**: Every company gets a record written after each stage, so a crash still leaves a partial trail
- [ ] **LOG-02**: A readable decision log explains why the company qualified, why this person, and why the email was written this way, including a hook-to-evidence map
- [ ] **LOG-03**: A `--replay` mode re-runs from cached responses with no network calls
- [ ] **LOG-04**: A demo set of 5 to 8 domains (fits, non-fits, an unscrapeable site, a no-contact case) is run, with sample output saved
- [ ] **LOG-05**: A README explains how to run, the known limits, and the cold-email compliance notes

### Web Runner

- [ ] **WEB-01**: A deployed Vercel URL serves a page where the owner enters a company domain and starts a full pipeline run
- [ ] **WEB-02**: The page and its API refuse every request without the shared password (APP_PASSWORD), and secrets exist only as Vercel environment variables entered by the owner
- [ ] **WEB-03**: Each stage's progress and result appears on the page as it finishes, and each stage fits within the serverless time limit
- [ ] **WEB-04**: The finished run shows the decision log (why this company, why this person, why this email) and the sent email, which goes only to the owner's address
- [ ] **WEB-05**: Per-session run limits and a Hunter-search ceiling prevent a shared link from exhausting credits

## v2 Requirements

- **ICP-01**: Incumbent GRC-tool detection (Vanta, Drata, Secureframe) with a score penalty and hook branching
- **ICP-02**: Calibration report across 10 to 20 domains to tune weights
- **SCR-03**: Jina Reader fallback for JavaScript-only sites
- **POC-05**: Several contacts per company and buying-committee targeting
- **SND-04**: Real-recipient sending from a verified domain

## Out of Scope

| Feature | Reason |
|---------|--------|
| Sending to real prospects | Brief hardcodes `to:` to the user's own address |
| Gmail sending | Replaced by Resend by user decision |
| Web UI | CLI plus decision log is enough for a 1.5h build |
| Follow-ups, reply handling, CRM sync | Not in the brief |
| LinkedIn scraping | Terms-of-service and reliability risk |
| LLM-judged free-form fit score | Not reproducible or defensible |
| Guessing email addresses | Wrong people and bounces; Hunter only |
| Hunter lookups before qualification | Wastes the limited free credits |
| Search API in the agent loop | Not in the stack; fetch-only loop covers most value |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 1 | Complete |
| FND-02 | Phase 1 | Complete |
| FND-03 | Phase 1 | Complete |
| FND-04 | Phase 1 | Complete |
| LOG-01 | Phase 1 | Complete |
| SND-03 | Phase 1 | Complete |
| RUN-01 | Phase 2 | Complete |
| RUN-02 | Phase 2 | Complete |
| RUN-03 | Phase 2 | Complete |
| RUN-04 | Phase 2 | Complete |
| SCR-01 | Phase 2 | Pending |
| SCR-02 | Phase 2 | Pending |
| EXT-01 | Phase 2 | Pending |
| EXT-02 | Phase 2 | Pending |
| EXT-03 | Phase 2 | Pending |
| QUA-01 | Phase 3 | Pending |
| QUA-02 | Phase 3 | Pending |
| QUA-03 | Phase 3 | Pending |
| QUA-04 | Phase 3 | Pending |
| QUA-05 | Phase 3 | Pending |
| POC-01 | Phase 4 | Pending |
| POC-02 | Phase 4 | Pending |
| POC-03 | Phase 4 | Pending |
| POC-04 | Phase 4 | Pending |
| DRF-01 | Phase 5 | Pending |
| DRF-02 | Phase 5 | Pending |
| DRF-03 | Phase 5 | Pending |
| DRF-04 | Phase 5 | Pending |
| SND-01 | Phase 6 | Pending |
| SND-02 | Phase 6 | Pending |
| LOG-02 | Phase 6 | Pending |
| LOG-03 | Phase 6 | Pending |
| LOG-04 | Phase 6 | Pending |
| LOG-05 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 34 total (corrected from 33; the list above contains 34 distinct IDs)
- Mapped to phases: 34
- Unmapped: 0

---
*Requirements defined: 2026-11-03*
*Last updated: 2026-11-03 after roadmap creation*
