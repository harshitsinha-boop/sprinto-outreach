# API Coverage — Phase 1 (Gemini, Hunter.io, Resend)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Scope: only capabilities this project could plausibly use. Phase 1 wires the INTEGRATE rows marked "(P1)"; INTEGRATE rows marked with a later phase are owned by that phase's requirements and are listed so the surface stays decided, not silently dropped.

# API Coverage — Gemini (google-genai 2.34, `client.models`)

| capability | decision | reason |
|---|---|---|
| generate_content (text turn) | INTEGRATE | |
| structured output via response_json_schema (P1) | INTEGRATE | |
| response_schema fallback path (P1, behind USE_RESPONSE_JSON_SCHEMA flag) | INTEGRATE | |
| manual function calling, AFC disabled, tool_config ANY/NONE (P1 smoke; Phase 3) | INTEGRATE | |
| thinking_config thinking_level (P1, SMART model only) | INTEGRATE | |
| usage_metadata token accounting (P1, LLMStats.total_tokens) | INTEGRATE | |
| error taxonomy and RetryInfo retryDelay handling (P1) | INTEGRATE | |
| system_instruction (P1) | INTEGRATE | |
| automatic function calling | OPT-OUT | explicitly out of scope: the hard iteration cap and per-fetch logged reason require a manual loop, and SDK 3.x removes AFC from generate_content |
| generate_content_stream (streaming) | OPT-OUT | not needed: batch CLI validates complete JSON, nothing is shown token by token |
| count_tokens endpoint | OPT-OUT | not needed: usage_metadata on every response already reports tokens and pages are truncated before prompting |
| built-in Google Search grounding and URL context tools | OPT-OUT | explicitly out of scope: fetching stays in our own code so every fetch is logged (STACK.md); REQUIREMENTS.md excludes a search API |
| Interactions API (client.interactions) | OPT-OUT | not needed: generate_content is stateless and fully loggable; server-side state hurts the decision trail (STACK.md) |
| embeddings | OPT-OUT | not needed: no retrieval or similarity step anywhere in the pipeline |
| context caching (caches API) | OPT-OUT | not needed: prompts are small and the local disk cache already makes reruns free |
| files API and multimodal input | OPT-OUT | not needed: inputs are scraped text only |
| batch prediction API | OPT-OUT | not needed: 5-10 domains processed sequentially to respect free-tier limits |
| live API, image and audio generation | OPT-OUT | not needed: text-only pipeline |
| models.list discovery | OPT-OUT | not needed: model IDs are pinned in .env and the live smoke call validates them |

# API Coverage — Hunter.io (REST v2)

| capability | decision | reason |
|---|---|---|
| GET /v2/domain-search with filters (P1 cache-first; Phase 4 ranking) | INTEGRATE | |
| GET /v2/account remaining credits and reset date (P1 smoke pre-check) | INTEGRATE | |
| error handling for 400, 401, 403, 429, 451 (P1) | INTEGRATE | |
| X-Credits-Used response header (P1, optional, recorded in cache entry) | INTEGRATE | |
| GET /v2/email-finder | OPT-OUT | explicitly out of scope: REQUIREMENTS.md excludes guessing email addresses; Domain Search already returns named contacts |
| GET /v2/email-verifier | OPT-OUT | not needed: the recipient is forced to OWNER_EMAIL, so prospect deliverability is never tested, and verification spends credits |
| GET /v2/email-count | OPT-OUT | not needed: zero-result domain searches cost no credit and are cached, so a pre-count adds a call without saving one |
| company, person and combined enrichment | OPT-OUT | not needed: company facts must be evidence-quoted from the company's own pages (EXT-02) |
| discover (company search) | OPT-OUT | explicitly out of scope: input is a user-supplied domain list |
| leads, leads lists and campaigns | OPT-OUT | explicitly out of scope: follow-ups, sequences and CRM sync are excluded in REQUIREMENTS.md |
| pagination beyond limit 10 (offset) | OPT-OUT | not needed: free plan rejects limit plus offset above 10; one filtered query per domain |

# API Coverage — Resend (resend 2.50 SDK)

| capability | decision | reason |
|---|---|---|
| Emails.send plain text to OWNER_EMAIL (P1 smoke; Phase 6 pipeline send) | INTEGRATE | |
| idempotency_key send option (P1 smoke; Phase 6 SND-02 per-domain keys) | INTEGRATE | |
| ResendError error mapping including the owner-only 403 validation_error (P1) | INTEGRATE | |
| returned message id check (P1) | INTEGRATE | |
| Emails.get delivery status lookup | OPT-OUT | not needed yet: success is the returned id (SND-02) plus the owner's inbox check; revisit in Phase 6 if the demo needs delivery status |
| batch send | OPT-OUT | not needed: one email per qualified company, sent sequentially with idempotency |
| scheduled send, update and cancel | OPT-OUT | not needed: sends are immediate |
| html body and attachments | OPT-OUT | not needed: DRF-02 requires plain text |
| domains API (verify a sending domain) | OPT-OUT | explicitly out of scope: sender is fixed to onboarding@resend.dev by user decision; real-recipient sending is v2 SND-04 |
| audiences, contacts and broadcasts | OPT-OUT | explicitly out of scope: no list management or marketing broadcasts |
| API key management | OPT-OUT | not needed: the owner creates the key in the Resend dashboard |
| webhooks (delivery and engagement events) | OPT-OUT | explicitly out of scope: reply handling and tracking are excluded in REQUIREMENTS.md |
