"""Live-proof smoke checks (FND-04) with injected clients, so every check is proven offline.

Order is cheapest first: gemini_structured (both models), gemini_tools, hunter_account
(free), then the one Hunter search (<= 1 credit), then the one Resend email. The first
FAIL among the cheap checks stops the run: every later check is reported SKIPPED, so a
bad key or an exhausted allowance never spends a Hunter search or sends an email.

Output carries check names, sources and results only, never key values.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from google.genai import types
from pydantic import BaseModel

from outreach import llm as llm_mod
from outreach.config import ENV_MAP, Settings, redact
from outreach.hunter import HunterClient
from outreach.llm import LLMAuthError, LLMClient, LLMError
from outreach.send import send_email

SMOKE_CHECKS = ("gemini_structured", "gemini_tools", "hunter", "resend")
# Live-proven (01-04, Assumption A1): the Gemini API rejected role="tool" with a 400 on the
# function-response turn and accepted role="user"; Phase 4's agent loop must send "user" too.
TOOL_RESULT_ROLE = "user"
FALLBACK_TOOL_RESULT_ROLE = "user"
# Free or near-free checks; they run first and the first FAIL here stops the run.
CHEAP_CHECKS = ("gemini_structured", "gemini_tools", "hunter_account")
UNKNOWN_REMAINING = "remaining=unknown"


@dataclass
class SmokeResult:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


class SmokeProbe(BaseModel):
    company: str | None
    is_saas: bool | None


def _pass(name: str, detail: str) -> SmokeResult:
    return SmokeResult(name, True, redact(detail))


def _fail(name: str, detail: str) -> SmokeResult:
    return SmokeResult(name, False, redact(detail))


def _exc(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- Gemini


def check_gemini_structured(llm: LLMClient, model: str) -> SmokeResult:
    name = f"gemini_structured[{model}]"
    if llm.cache_dir is not None:
        return _fail(name, "client has a cache attached; a cached answer proves nothing live")
    try:
        obj = llm.generate_structured(
            model=model,
            system="Extract facts from the text. Use null when a fact is not stated.",
            prompt="Acme sells project-management software to teams.",
            schema=SmokeProbe,
            purpose="smoke",
        )
    except Exception as e:  # every check reports, none raises
        return _fail(name, _exc(e))
    return _pass(name, f"company={obj.company!r} is_saas={obj.is_saas!r}")


def check_function_calling(
    llm: LLMClient, model: str, role: str = TOOL_RESULT_ROLE
) -> SmokeResult:
    name = "gemini_tools"
    try:
        decl = types.FunctionDeclaration(
            name="fetch_page",
            description="Fetch one more page from the prospect's own site",
            parameters_json_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["url", "reason"],
            },
        )
        base: dict = dict(
            tools=[types.Tool(function_declarations=[decl])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=1024,
        )
        if llm_mod.SEND_THINKING_CONFIG:
            base["thinking_config"] = types.ThinkingConfig(thinking_level="LOW")
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
        history = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="Call fetch_page for https://example.com/about with reason 'smoke test'."
                    )
                ],
            )
        ]
        r1 = llm.generate_raw(model, history, types.GenerateContentConfig(**base, tool_config=force))
        calls = r1.function_calls or []
        if len(calls) != 1 or calls[0].name != "fetch_page":
            return _fail(name, f"expected exactly one fetch_page call, got {len(calls)}")
        args = dict(calls[0].args or {})
        if not {"url", "reason"} <= set(args):
            return _fail(name, f"fetch_page call is missing url/reason (got {sorted(args)})")
        history.append(r1.candidates[0].content)  # VERBATIM: preserves thought signatures

        def turn2(turn_role: str):
            turn = types.Content(
                role=turn_role,
                parts=[
                    types.Part.from_function_response(
                        name="fetch_page",
                        response={"result": "Example Domain. This domain is for use in examples."},
                    )
                ],
            )
            return llm.generate_raw(
                model, [*history, turn], types.GenerateContentConfig(**base, tool_config=stop)
            )

        used = role
        try:
            r2 = turn2(role)
        except LLMError as e:
            if isinstance(e, LLMAuthError) or e.code != 400 or role != TOOL_RESULT_ROLE:
                raise
            used = FALLBACK_TOOL_RESULT_ROLE
            r2 = turn2(used)
        final = r2.text if r2.candidates else None
        if not final:
            return _fail(name, f"round trip returned no final text (role={used})")
        return _pass(name, f"role={used} args={sorted(args)} final={final[:60]!r}")
    except Exception as e:
        return _fail(name, _exc(e))


# ---------------------------------------------------------------- Hunter


def check_hunter_account(hunter, budget: int) -> SmokeResult:
    name = "hunter_account"
    try:
        acct = hunter.account()
    except Exception as e:
        return _fail(name, _exc(e))
    remaining = acct.get("remaining")
    plan, reset = acct.get("plan"), acct.get("reset_date")
    if remaining is not None and remaining <= 0:
        return _fail(name, f"remaining={remaining} plan={plan} reset_date={reset}; no search credits left")
    shown = UNKNOWN_REMAINING if remaining is None else f"remaining={remaining}"
    detail = f"plan={plan} {shown} reset_date={reset}"
    if remaining is not None and remaining != budget:
        detail += f" WARNING remaining {remaining} != local budget {budget}"
    return _pass(name, detail)


def check_hunter(hunter, domain: str | None) -> SmokeResult:
    name = "hunter"
    if not domain:
        return _fail(name, "set SKELETON_DOMAIN (no search was made)")
    try:
        res = hunter.domain_search(domain)
    except Exception as e:
        return _fail(name, _exc(e))
    if res.get("from_cache"):
        return _fail(name, "NOT LIVE: served from cache; this proves nothing about the live API")
    live = getattr(hunter, "live_calls_this_process", 0)
    if live > 1:
        return _fail(name, f"{live} live Hunter calls in one smoke run (limit 1)")
    response = res.get("response") or {}
    data = response.get("data") or {}
    results = (response.get("meta") or {}).get("results")
    if results is None:
        results = len(data.get("emails") or [])
    return _pass(name, f"results={results} credits_used={res.get('credits_used')}")


# ---------------------------------------------------------------- Resend


def check_resend(settings: Settings, *, sender: Callable | None = None) -> SmokeResult:
    name = "resend"
    try:
        sent = send_email(
            settings,
            "[SMOKE] sprinto-outreach",
            "Smoke test from sprinto-outreach.\nIf you can read this, Resend delivery works.",
            dry_run=False,
            idempotency_key="smoke-" + uuid.uuid4().hex,
            sender=sender,
        )
    except Exception as e:
        return SmokeResult(name, False, redact(_exc(e), settings))
    return _pass(name, f"id={sent.id}; check inbox and spam at {settings.owner_email}")


# ------------------------------------------------------------------ runner


def _family(name: str) -> str:
    return name.split("[", 1)[0]


def run_smoke(
    settings: Settings,
    *,
    only: str | None = None,
    llm: LLMClient | None = None,
    hunter=None,
    sender: Callable | None = None,
    out: TextIO | None = None,
) -> list[SmokeResult]:
    stream = out if out is not None else sys.stdout

    def emit(line: str) -> None:
        stream.write(redact(line, settings) + "\n")
        stream.flush()

    for env_name in ENV_MAP:  # names and sources only, never values
        source = settings.sources.get(env_name, "missing")
        emit(f"config {env_name}: missing" if source == "missing" else f"config {env_name}: set ({source})")

    # cache_dir=None: a cached answer would make the smoke pass without a live call.
    llm = llm or LLMClient(settings.gemini_api_key.get_secret_value(), cache_dir=None)
    hunter = hunter or HunterClient(
        settings.hunter_api_key.get_secret_value(),
        settings.cache_dir / "hunter",
        settings.hunter_monthly_budget,
    )
    fast, smart = settings.gemini_model_fast, settings.gemini_model_smart

    plan: list[tuple[str, str, Callable[[], SmokeResult]]] = []
    if only in (None, "gemini_structured"):
        plan.append(("gemini_structured", f"gemini_structured[{fast}]", lambda: check_gemini_structured(llm, fast)))
        plan.append(("gemini_structured", f"gemini_structured[{smart}]", lambda: check_gemini_structured(llm, smart)))
    if only in (None, "gemini_tools"):
        plan.append(("gemini_tools", "gemini_tools", lambda: check_function_calling(llm, smart)))
    if only in (None, "hunter"):
        plan.append(("hunter", "hunter_account", lambda: check_hunter_account(hunter, settings.hunter_monthly_budget)))
        plan.append(("hunter", "hunter", lambda: check_hunter(hunter, settings.skeleton_domain)))
    if only in (None, "resend"):
        plan.append(("resend", "resend", lambda: check_resend(settings, sender=sender)))

    results: list[SmokeResult] = []
    stopped_by: str | None = None
    for _family_key, label, run in plan:
        if stopped_by is not None:
            res = SmokeResult(label, ok=False, skipped=True, detail=f"skipped: {stopped_by} failed first")
        else:
            res = run()
            if not res.ok and _family(res.name) in CHEAP_CHECKS:
                stopped_by = res.name
        results.append(res)
        status = "SKIPPED" if res.skipped else ("PASS" if res.ok else "FAIL")
        emit(f"{status} {res.name} {res.detail}")
        if res.ok and res.name == "hunter_account" and UNKNOWN_REMAINING in res.detail:
            emit("WARNING hunter_account: remaining unknown; zero-credit guard inactive")
    return results
