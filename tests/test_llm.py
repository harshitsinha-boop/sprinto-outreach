"""LLMClient: retry/backoff, one repair retry, validated-output cache, config, wire format.

Offline only. Fake SDK client for behaviour; respx over the real genai.Client for the wire.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from google.genai import types

import outreach.llm as llm_mod
from conftest import (
    CANARY_ENV,
    FakeGenaiClient,
    api_error,
    blocked_response,
    function_call_response,
    text_response,
)
from outreach.agent import FETCH_TOOL
from outreach.llm import (
    LLMAuthError,
    LLMClient,
    LLMError,
    LLMQuotaError,
    LLMSchemaError,
    build_config,
    build_tool_config,
    gemini_schema,
)
from outreach.models import CompanyProfile, EmailDraft, ToolResult

KEY = CANARY_ENV["GEMINI_API_KEY"]
MODEL = "gemini-3.5-flash-lite"
VALID = EmailDraft(subject="Hello", body="World body")
VALID_JSON = VALID.model_dump_json()


def make(queue, fake_sleep, cache_dir=None, **kw):
    return LLMClient(KEY, cache_dir, client=FakeGenaiClient(queue), sleep=fake_sleep, **kw)


def call(client, **over):
    args = dict(
        model=MODEL,
        system="sys",
        prompt="prompt",
        schema=EmailDraft,
        purpose="t",
    )
    args.update(over)
    return client.generate_structured(**args)


def calls_of(client):
    return client._c.models.calls


# ---------------------------------------------------------------- retry


def test_retry_429_then_success(fake_sleep):
    c = make([api_error(429, "RESOURCE_EXHAUSTED"), text_response(VALID_JSON)], fake_sleep)
    assert call(c) == VALID
    assert c.stats.retries == 1
    assert c.stats.api_calls == 2
    assert len(fake_sleep.delays) == 1


def test_retry_503_then_success(fake_sleep):
    c = make([api_error(503, "UNAVAILABLE"), text_response(VALID_JSON)], fake_sleep)
    assert call(c) == VALID
    assert c.stats.retries == 1
    assert len(fake_sleep.delays) == 1


def test_retry_honours_retry_delay(fake_sleep):
    c = make(
        [api_error(429, "RESOURCE_EXHAUSTED", retry_delay="13s"), text_response(VALID_JSON)],
        fake_sleep,
    )
    call(c)
    assert fake_sleep.delays == [13.0]


def test_retry_delay_above_max_wait_raises_quota_without_sleeping(fake_sleep):
    c = make(
        [api_error(429, "RESOURCE_EXHAUSTED", retry_delay="120s"), text_response(VALID_JSON)],
        fake_sleep,
        max_wait=60.0,
    )
    with pytest.raises(LLMQuotaError):
        call(c)
    assert fake_sleep.delays == []
    assert c.stats.api_calls == 1


def test_retry_400_is_not_retried(fake_sleep):
    c = make([api_error(400, "INVALID_ARGUMENT", "bad schema")], fake_sleep)
    with pytest.raises(LLMError) as ei:
        call(c)
    assert not isinstance(ei.value, LLMAuthError)
    assert ei.value.code == 400
    assert c.stats.api_calls == 1
    assert fake_sleep.delays == []


@pytest.mark.parametrize("code,status", [(401, "UNAUTHENTICATED"), (403, "PERMISSION_DENIED")])
def test_retry_auth_errors_raise_auth_immediately(fake_sleep, code, status):
    c = make([api_error(code, status)], fake_sleep)
    with pytest.raises(LLMAuthError):
        call(c)
    assert c.stats.api_calls == 1


def test_retry_400_api_key_message_is_auth(fake_sleep):
    c = make([api_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.")], fake_sleep)
    with pytest.raises(LLMAuthError):
        call(c)
    assert c.stats.api_calls == 1


def test_retry_exhausted_503_raises_llm_error(fake_sleep):
    c = make([api_error(503, "UNAVAILABLE")] * 3, fake_sleep, max_attempts=3)
    with pytest.raises(LLMError) as ei:
        call(c)
    assert not isinstance(ei.value, LLMQuotaError)
    assert c.stats.api_calls == 3
    assert len(fake_sleep.delays) == 2


def test_retry_exhausted_429_raises_quota(fake_sleep):
    c = make([api_error(429, "RESOURCE_EXHAUSTED")] * 3, fake_sleep, max_attempts=3)
    with pytest.raises(LLMQuotaError):
        call(c)
    assert c.stats.api_calls == 3


def test_retry_transport_timeout_is_retried(fake_sleep):
    c = make([httpx.ConnectTimeout("slow"), text_response(VALID_JSON)], fake_sleep)
    assert call(c) == VALID
    assert c.stats.retries == 1


def test_retry_error_message_has_no_key(fake_sleep):
    c = make([api_error(400, "INVALID_ARGUMENT", "nope")], fake_sleep)
    with pytest.raises(LLMError) as ei:
        call(c)
    assert KEY not in str(ei.value)
    assert "400" in str(ei.value)


# --------------------------------------------------------------- repair


def test_repair_invalid_then_valid(fake_sleep):
    c = make([text_response("not json"), text_response(VALID_JSON)], fake_sleep)
    assert call(c) == VALID
    assert c.stats.repairs == 1
    second = calls_of(c)[1]["contents"]
    assert second[-1].role == "user"
    assert "failed validation" in second[-1].parts[0].text
    # the bad model output is replayed as a model turn before the correction request
    assert second[-2].role == "model"
    assert second[-2].parts[0].text == "not json"


def test_repair_first_request_contents_unchanged_by_repair(fake_sleep):
    c = make([text_response("not json"), text_response(VALID_JSON)], fake_sleep)
    call(c)
    assert len(calls_of(c)[0]["contents"]) == 1
    assert len(calls_of(c)[1]["contents"]) == 3


def test_repair_blocked_response_counts_as_failed_attempt(fake_sleep):
    c = make([blocked_response(), text_response(VALID_JSON)], fake_sleep)
    assert call(c) == VALID
    assert c.stats.repairs == 1
    second = calls_of(c)[1]["contents"]
    assert second[-1].role == "user"
    assert "failed validation" in second[-1].parts[0].text


def test_repair_max_tokens_doubles_budget(fake_sleep):
    c = make(
        [text_response('{"subject":', finish_reason="MAX_TOKENS"), text_response(VALID_JSON)],
        fake_sleep,
    )
    call(c, max_output_tokens=1000)
    assert calls_of(c)[0]["config"].max_output_tokens == 1000
    assert calls_of(c)[1]["config"].max_output_tokens == 2000


def test_repair_two_invalid_raises_schema_error_and_caches_nothing(fake_sleep, tmp_path):
    cache = tmp_path / "llm"
    c = make([text_response("nope"), text_response("still nope")], fake_sleep, cache_dir=cache)
    with pytest.raises(LLMSchemaError) as ei:
        call(c)
    assert "t:" in str(ei.value)
    assert c.stats.api_calls == 2
    assert not cache.exists() or list(cache.iterdir()) == []


def test_repair_is_limited_to_one(fake_sleep):
    c = make([text_response("a"), text_response("b"), text_response(VALID_JSON)], fake_sleep)
    with pytest.raises(LLMSchemaError):
        call(c)
    assert c.stats.api_calls == 2


# ---------------------------------------------------------------- cache


def test_cache_second_identical_call_makes_no_api_call(fake_sleep, tmp_path):
    c = make([text_response(VALID_JSON)], fake_sleep, cache_dir=tmp_path / "llm")
    first = call(c)
    second = call(c)
    assert first == second == VALID
    assert c.stats.api_calls == 1
    assert c.stats.cache_hits == 1
    files = list((tmp_path / "llm").glob("*.json"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text())
    assert entry["purpose"] == "t" and entry["model"] == MODEL
    assert KEY not in files[0].read_text()


def test_cache_survives_a_new_client_instance(fake_sleep, tmp_path):
    cache = tmp_path / "llm"
    call(make([text_response(VALID_JSON)], fake_sleep, cache_dir=cache))
    c2 = make([], fake_sleep, cache_dir=cache)
    assert call(c2) == VALID
    assert c2.stats.api_calls == 0 and c2.stats.cache_hits == 1


@pytest.mark.parametrize(
    "over",
    [
        {"model": "gemini-3.8-flash"},
        {"prompt": "other prompt"},
        {"schema": CompanyProfile},
        {"prompt_version": "2"},
        {"system": "other system"},
        {"thinking_level": "LOW"},
    ],
)
def test_cache_key_changes_with_inputs(fake_sleep, tmp_path, over):
    cache = tmp_path / "llm"
    other_text = (
        CompanyProfile(
            name=None,
            offering=None,
            is_b2b=None,
            stage=None,
            headcount=None,
            compliance_mentions=[],
            hiring_signals=[],
            enterprise_customers=[],
        ).model_dump_json()
        if over.get("schema") is CompanyProfile
        else VALID_JSON
    )
    c = make([text_response(VALID_JSON), text_response(other_text)], fake_sleep, cache_dir=cache)
    call(c)
    call(c, **over)
    assert c.stats.api_calls == 2
    assert len(list(cache.glob("*.json"))) == 2


def test_cache_disabled_when_cache_dir_none(fake_sleep):
    c = make([text_response(VALID_JSON), text_response(VALID_JSON)], fake_sleep, cache_dir=None)
    call(c)
    call(c)
    assert c.stats.api_calls == 2 and c.stats.cache_hits == 0


# --------------------------------------------------------------- config


def _all_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(node, list):
        for x in node:
            yield from _all_keys(x)


def test_config_never_sets_sampling_params_and_disables_sdk_retries():
    cfg = build_config(system="s", schema=CompanyProfile, max_output_tokens=123, thinking_level=None)
    assert cfg.temperature is None and cfg.top_p is None and cfg.top_k is None
    assert cfg.http_options.retry_options.attempts == 1
    assert cfg.response_mime_type == "application/json"
    assert cfg.max_output_tokens == 123
    assert cfg.system_instruction == "s"
    assert cfg.thinking_config is None


def test_config_schema_has_no_default_keys():
    schema = gemini_schema(CompanyProfile)
    assert "default" not in set(_all_keys(schema))
    # a model that does declare defaults is stripped too
    from outreach.models import ScoreBreakdown

    assert "default" in set(_all_keys(ScoreBreakdown.model_json_schema()))
    assert "default" not in set(_all_keys(gemini_schema(ScoreBreakdown)))
    cfg = build_config(system="s", schema=CompanyProfile, max_output_tokens=10, thinking_level=None)
    assert "default" not in set(_all_keys(cfg.response_json_schema))


def test_config_thinking_level_set_only_when_given():
    cfg = build_config(system="s", schema=EmailDraft, max_output_tokens=10, thinking_level="LOW")
    assert cfg.thinking_config is not None
    assert str(cfg.thinking_config.thinking_level.value) == "LOW"


def test_config_thinking_flag_off_omits_thinking_config(monkeypatch):
    monkeypatch.setattr(llm_mod, "SEND_THINKING_CONFIG", False)
    cfg = build_config(system="s", schema=EmailDraft, max_output_tokens=10, thinking_level="LOW")
    assert cfg.thinking_config is None


def test_config_response_schema_fallback_passes_the_class(monkeypatch):
    monkeypatch.setattr(llm_mod, "USE_RESPONSE_JSON_SCHEMA", False)
    cfg = build_config(system="s", schema=CompanyProfile, max_output_tokens=10, thinking_level=None)
    assert cfg.response_schema is CompanyProfile
    assert cfg.response_json_schema is None


def test_config_flags_default_to_documented_values():
    assert llm_mod.USE_RESPONSE_JSON_SCHEMA is True
    assert llm_mod.SEND_THINKING_CONFIG is True


# ----------------------------------------------------------------- wire

GEN_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _ok_body(text: str) -> dict:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ]
    }


def test_wire_header_key_and_generation_config():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEN_URL.format(model=MODEL)).respond(200, json=_ok_body(VALID_JSON))
        client = LLMClient(KEY, cache_dir=None)
        assert call(client) == VALID
        req = route.calls[0].request
    assert req.headers["x-goog-api-key"] == KEY
    assert "key" not in req.url.params
    assert KEY not in str(req.url)
    body = json.loads(req.content)
    gen = body["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert "temperature" not in gen and "topP" not in gen and "topK" not in gen
    assert "responseJsonSchema" in gen
    assert "default" not in set(_all_keys(gen["responseJsonSchema"]))
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


def test_wire_function_calling_round_trip_keeps_thought_signature():
    fc_body = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "fetch_page",
                                "args": {"url": "https://example.com/about", "reason": "t"},
                            },
                            "thoughtSignature": "c2ln",
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }
    decl = types.FunctionDeclaration(
        name="fetch_page",
        description="fetch",
        parameters_json_schema={
            "type": "object",
            "properties": {"url": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["url", "reason"],
        },
    )
    base = dict(
        tools=[types.Tool(function_declarations=[decl])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        max_output_tokens=256,
    )
    force = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode="ANY", allowed_function_names=["fetch_page"]
        )
    )
    stop = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.NONE
        )
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEN_URL.format(model=MODEL)).mock(
            side_effect=[
                httpx.Response(200, json=fc_body),
                httpx.Response(200, json=_ok_body("done")),
            ]
        )
        client = LLMClient(KEY, cache_dir=None)
        history = [types.Content(role="user", parts=[types.Part.from_text(text="go")])]
        r1 = client.generate_raw(MODEL, history, types.GenerateContentConfig(**base, tool_config=force))
        assert len(r1.function_calls) == 1
        history.append(r1.candidates[0].content)
        history.append(
            types.Content(
                role="tool",
                parts=[types.Part.from_function_response(name="fetch_page", response={"result": "ok"})],
            )
        )
        r2 = client.generate_raw(MODEL, history, types.GenerateContentConfig(**base, tool_config=stop))
        assert r2.text == "done"
        first, second = (json.loads(c.request.content) for c in route.calls)
    assert first["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert second["toolConfig"]["functionCallingConfig"]["mode"] == "NONE"
    contents = second["contents"]
    model_turn = next(c for c in contents if c["role"] == "model")
    assert model_turn["parts"][0]["functionCall"]["name"] == "fetch_page"
    assert model_turn["parts"][0]["thoughtSignature"] == "c2ln"
    tool_turn = contents[-1]
    assert tool_turn["parts"][0]["functionResponse"]["name"] == "fetch_page"


def test_wire_429_retry_after_real_error_parse(fake_sleep):
    err_body = {
        "error": {
            "code": 429,
            "message": "quota",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}
            ],
        }
    }
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEN_URL.format(model=MODEL)).mock(
            side_effect=[
                httpx.Response(429, json=err_body),
                httpx.Response(200, json=_ok_body(VALID_JSON)),
            ]
        )
        client = LLMClient(KEY, cache_dir=None, sleep=fake_sleep)
        assert call(client) == VALID
        assert route.call_count == 2  # SDK retries are off: exactly one request per attempt
    assert fake_sleep.delays == [7.0]


def test_function_calling_helper_builders_available():
    # sanity: the fakes used by the smoke tests can be built
    assert function_call_response("fetch_page", {"url": "u", "reason": "r"}).function_calls


# ------------------------------------------------------------ tool sessions (manual FC)

FETCH_ARGS = {"url": "https://example.com/trust-center", "reason": "resolve compliance_pursuit"}
RESULT = [ToolResult(name="fetch_page", response={"status": "fetched", "score_min": 70})]


def tool_session(client, **over):
    args = dict(model=MODEL, system="agent system", tool=FETCH_TOOL, purpose="agent")
    args.update(over)
    return client.start_tool_session(**args)


def test_tool_config_never_mixes_schema_and_tools():
    cfg = build_tool_config(
        system="sys", tool=FETCH_TOOL, max_output_tokens=256, thinking_level="LOW"
    )
    declarations = cfg.tools[0].function_declarations
    assert [d.name for d in declarations] == ["fetch_page"] and len(cfg.tools) == 1
    assert sorted(declarations[0].parameters_json_schema["required"]) == ["reason", "url"]
    assert cfg.automatic_function_calling.disable is True
    calling = cfg.tool_config.function_calling_config
    assert str(getattr(calling.mode, "value", calling.mode)) == "ANY"
    assert calling.allowed_function_names == ["fetch_page"]
    for name in (
        "response_mime_type",
        "response_json_schema",
        "response_schema",
        "temperature",
        "top_p",
        "top_k",
    ):
        assert getattr(cfg, name) is None, name
    assert cfg.thinking_config is not None


def test_tool_session_wire_role_user_and_verbatim_signature():
    fc_body = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"functionCall": {"name": "fetch_page", "args": FETCH_ARGS}, "thoughtSignature": "c2ln"}
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEN_URL.format(model=MODEL)).mock(
            side_effect=[httpx.Response(200, json=fc_body), httpx.Response(200, json=_ok_body("done"))]
        )
        session = tool_session(LLMClient(KEY, cache_dir=None))
        first = session.send("go")
        second = session.respond(RESULT)
        sent = [json.loads(c.request.content) for c in route.calls]
    assert [c.name for c in first.calls] == ["fetch_page"] and first.calls[0].args == FETCH_ARGS
    assert second.calls == [] and second.text == "done"
    assert sent[0]["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert sent[0]["tools"][0]["functionDeclarations"][0]["name"] == "fetch_page"
    for body in sent:
        gen = body.get("generationConfig", {})
        assert "responseJsonSchema" not in gen and "responseMimeType" not in gen
    contents = sent[1]["contents"]
    model_turn = next(c for c in contents if c["role"] == "model")
    assert model_turn["parts"][0]["thoughtSignature"] == "c2ln"
    assert contents[-1]["role"] == "user"
    assert contents[-1]["parts"][0]["functionResponse"]["name"] == "fetch_page"


def test_tool_session_reads_role_from_smoke(monkeypatch, fake_sleep):
    monkeypatch.setattr("outreach.smoke.TOOL_RESULT_ROLE", "user-x")
    client = make([function_call_response("fetch_page", FETCH_ARGS), text_response("done")], fake_sleep)
    session = tool_session(client)
    session.send("go")
    session.respond(RESULT)
    assert calls_of(client)[1]["contents"][-1].role == "user-x"


def test_tool_session_rejects_automatic_function_calling_history(fake_sleep):
    response = types.GenerateContentResponse(
        candidates=function_call_response("fetch_page", FETCH_ARGS).candidates,
        automatic_function_calling_history=[
            types.Content(role="user", parts=[types.Part.from_text(text="x")])
        ],
    )
    session = tool_session(make([response], fake_sleep))
    with pytest.raises(LLMError, match="automatic function calling ran"):
        session.send("go")


def test_tool_session_retries_429(fake_sleep):
    client = make(
        [api_error(429, "RESOURCE_EXHAUSTED"), function_call_response("fetch_page", FETCH_ARGS)],
        fake_sleep,
    )
    reply = tool_session(client).send("go")
    assert [c.name for c in reply.calls] == ["fetch_page"]
    assert (client.stats.retries, client.stats.api_calls) == (1, 2)


SIGNATURE = b"\x00\x01thought-signature"


def run_two_turns(client):
    """One send and one respond; returns (send reply, respond reply, session)."""
    session = tool_session(client)
    first = session.send("go")
    second = session.respond(RESULT)
    return first, second, session


def test_tool_session_cache_hit_makes_no_call_and_keeps_signature(fake_sleep, tmp_path):
    cache = tmp_path / "llm"
    first_client = make(
        [
            function_call_response("fetch_page", FETCH_ARGS, SIGNATURE),
            function_call_response("fetch_page", FETCH_ARGS),
        ],
        fake_sleep,
        cache,
    )
    a1, a2, _ = run_two_turns(first_client)
    assert not a1.from_cache and not a2.from_cache and first_client.stats.api_calls == 2
    second_client = make([], fake_sleep, cache)
    b1, b2, session = run_two_turns(second_client)
    assert calls_of(second_client) == [] and second_client.stats.api_calls == 0
    assert second_client.stats.cache_hits == 2
    assert b1.from_cache and b2.from_cache
    assert b1.calls == a1.calls and b2.calls == a2.calls
    assert session.contents[1].parts[0].thought_signature == SIGNATURE


def test_tool_session_cache_key_changes_with_system_and_version(fake_sleep, tmp_path):
    cache = tmp_path / "llm"
    queue = [function_call_response("fetch_page", FETCH_ARGS) for _ in range(3)]
    client = make(queue, fake_sleep, cache)
    tool_session(client).send("go")
    assert client.stats.api_calls == 1
    tool_session(client).send("go")  # identical: a hit
    assert client.stats.api_calls == 1 and client.stats.cache_hits == 1
    tool_session(client, system="a different system").send("go")
    assert client.stats.api_calls == 2
    tool_session(client, prompt_version="2").send("go")
    assert client.stats.api_calls == 3


def test_tool_session_does_not_cache_blocked_response(fake_sleep, tmp_path):
    cache = tmp_path / "llm"
    client = make(
        [blocked_response(), function_call_response("fetch_page", FETCH_ARGS)], fake_sleep, cache
    )
    blocked = tool_session(client).send("go")
    assert blocked.calls == [] and blocked.text is None
    assert not (cache / "tools").exists() or not list((cache / "tools").glob("*.json"))
    again = tool_session(client).send("go")
    assert not again.from_cache and [c.name for c in again.calls] == ["fetch_page"]
    assert client.stats.api_calls == 2
    assert len(list((cache / "tools").glob("*.json"))) == 1
