# API Coverage — Phase 3 (Gemini function calling for the bounded research loop)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Scope: Phase 3 adds no new external service. It uses one more capability of the Gemini API that Phase 1 already decided ("manual function calling, AFC disabled, tool_config ANY/NONE (P1 smoke; Phase 3) | INTEGRATE" in `.planning/phases/01-foundation-and-walking-skeleton/COVERAGE.md`). This matrix re-decides every Gemini capability the research loop touches, starting again from full coverage instead of quietly reusing Phase 1's opt-outs. Hunter and Resend are not called by any Phase 3 code. The qualification gate exists so that Hunter runs only for qualified companies, and Phase 4 owns the Hunter rows.
>
> Notes on the INTEGRATE rows (Plan 03-02):
> - `fetch_page_declaration`: one FunctionDeclaration, `fetch_page(url, reason)`, with parameters_json_schema.
> - `afc_disabled_and_checked`: automatic_function_calling disabled in every tool config, and a response with AFC history raises.
> - `tool_config_any`: mode ANY, with allowed_function_names [fetch_page].
> - `function_response_role_user`: the role is read from smoke.TOOL_RESULT_ROLE (live-proven in Plan 01-04).
> - `verbatim_model_content`: the model content (thought signatures) goes back unchanged on the next turn.
> - `tool_turn_cache`: the key covers model, system, tool, prompt version and full history; only validated turns are stored.
> - `research_reextract_structured`: response_json_schema re-extraction is a separate request with no tools.

# API Coverage — Gemini (google-genai 2.34, `client.models.generate_content`)

| capability | decision | reason |
|---|---|---|
| fetch_page_declaration | INTEGRATE | |
| afc_disabled_and_checked | INTEGRATE | |
| tool_config_any | INTEGRATE | |
| function_response_role_user | INTEGRATE | |
| verbatim_model_content | INTEGRATE | |
| tool_turn_retry_backoff | INTEGRATE | |
| tool_turn_cache | INTEGRATE | |
| thinking_level_low_tool_turns | INTEGRATE | |
| usage_metadata_tool_turns | INTEGRATE | |
| research_reextract_structured | INTEGRATE | |
| tools_with_response_json_schema | OPT-OUT | explicitly out of scope: a locked decision keeps tool turns and structured calls in separate requests (mixing is a Gemini-3-only preview), and Python computes the score |
| tool_config_auto | OPT-OUT | not needed: code decides when to stop (sufficient data, caps, no progress); a text-only reply is still handled and ends the loop as model_done |
| tool_config_none_final_turn | OPT-OUT | not needed: the loop never asks the model for a final answer; the verdict is computed in Python from validated evidence |
| parallel_function_calls | OPT-OUT | explicitly out of scope: at most one fetch per turn; extra calls in a turn are answered as refused (one_fetch_per_turn) and logged |
| automatic_function_calling | OPT-OUT | explicitly out of scope: the 3-iteration cap, the per-fetch logged reason and the same-domain refusal all need a hand-written loop |
| google_search_and_url_context_tools | OPT-OUT | explicitly out of scope: REQUIREMENTS.md excludes a search API from the loop; every fetch goes through the guarded PageFetcher so it is logged and same-domain only |
| streaming_counttokens_caches_files_batch | OPT-OUT | not needed: same reasons as Phase 1 (batch CLI, small prompts, text only, local disk cache) |

# API Coverage — Hunter.io and Resend

| capability | decision | reason |
|---|---|---|
| hunter_domain_search_in_qualify_or_loop | OPT-OUT | explicitly out of scope: QUA-05 requires zero Hunter calls for disqualified and insufficient-data companies, so the loop has no Hunter tool; Phase 4 owns POC-01 to POC-04 |
| resend_send_in_qualify_or_loop | OPT-OUT | explicitly out of scope: the loop's only tool is a read-only same-domain page fetch; sending stays in the guarded send stage (Phase 6) |
