"""The single Gemini wrapper (FND-03).

Every Gemini call goes through `LLMClient`. Only this module and `smoke.py` import
`google.genai`. Behaviour:

- transient errors (408, 429, 5xx, transport errors) are retried with capped, jittered
  exponential backoff that honours a server `RetryInfo.retryDelay`;
- a 400 is never retried; 401/403 (or a 400 that complains about the API key) raises
  `LLMAuthError` immediately, because it is systemic;
- an empty, blocked, truncated or schema-invalid answer gets exactly ONE repair attempt;
- only validated output is cached, keyed by a hash of everything that shapes the answer.

SDK-level retries are switched off (`attempts=1`) so they never multiply ours, and no
request ever sets temperature, top_p or top_k (deprecated on Gemini 3.6+).
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from outreach.cache import atomic_write_json

# Documented live fallbacks. Plan 01-04 flips one only if the live smoke rejects the default.
USE_RESPONSE_JSON_SCHEMA = True  # False: pass the Pydantic class as `response_schema`
SEND_THINKING_CONFIG = True  # False: never send thinking_config

REQUEST_TIMEOUT_MS = 60_000


class LLMError(Exception):
    """Base error. `code` is the HTTP status when there is one."""

    def __init__(self, message: str, *, code: int | None = None):
        super().__init__(message)
        self.code = code


class LLMAuthError(LLMError):
    """Systemic (bad or missing key): Phase 2 aborts the whole batch on it."""


class LLMQuotaError(LLMError):
    """429 after retries, or a server retryDelay longer than `max_wait`."""


class LLMSchemaError(LLMError):
    """The repair retry also failed to produce valid structured output."""


def gemini_schema(model: type[BaseModel]) -> dict:
    """`model_json_schema()` with every `default` key removed at any depth."""

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "default"}
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node

    return strip(model.model_json_schema())


def _retry_delay_s(e: errors.APIError) -> float | None:
    """Seconds from a RetryInfo detail (`"13s"` -> 13.0), else None."""
    body = e.details if isinstance(e.details, dict) else {}
    err = body.get("error") or {}
    for detail in err.get("details") or []:
        if isinstance(detail, dict) and str(detail.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(detail["retryDelay"]).rstrip("s"))
            except (KeyError, ValueError):
                return None
    return None


def _is_auth(e: errors.APIError) -> bool:
    if e.code in (401, 403):
        return True
    return e.code == 400 and "api key" in str(e.message or "").lower()


@dataclass
class LLMStats:
    api_calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    repairs: int = 0
    total_tokens: int = 0


def build_config(
    *,
    system: str | None,
    schema: type[BaseModel],
    max_output_tokens: int,
    thinking_level: str | None,
) -> types.GenerateContentConfig:
    """Structured-output request config. Never sets temperature, top_p or top_k."""
    kwargs: dict[str, Any] = {
        "system_instruction": system,
        "response_mime_type": "application/json",
        "max_output_tokens": max_output_tokens,
        "http_options": types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    }
    if USE_RESPONSE_JSON_SCHEMA:
        kwargs["response_json_schema"] = gemini_schema(schema)
    else:
        kwargs["response_schema"] = schema
    if thinking_level and SEND_THINKING_CONFIG:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    return types.GenerateContentConfig(**kwargs)


class LLMClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path | None,
        *,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
        max_delay: float = 30.0,
        max_wait: float = 60.0,
    ):
        # Explicit key, never env-implicit: GOOGLE_API_KEY vs GEMINI_API_KEY precedence is moot.
        self._c = client or genai.Client(api_key=api_key)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.max_delay = max_delay
        self.max_wait = max_wait
        self.stats = LLMStats()

    # ------------------------------------------------------------------ raw

    def generate_raw(self, model: str, contents: list, cfg: types.GenerateContentConfig):
        """One logical call with retry only. Never cached (the smoke command uses this)."""
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.stats.api_calls += 1
            delay: float | None = None
            try:
                r = self._c.models.generate_content(
                    model=model, contents=list(contents), config=cfg
                )
                usage = getattr(r, "usage_metadata", None)
                if usage is not None and usage.total_token_count:
                    self.stats.total_tokens += usage.total_token_count
                return r
            except errors.APIError as e:
                text = f"{e.code} {e.status}: {e.message}"
                if _is_auth(e):
                    raise LLMAuthError(text, code=e.code) from e
                code = e.code or 0
                if not (code in (408, 429) or code >= 500):
                    raise LLMError(text, code=e.code) from e
                last, delay = e, _retry_delay_s(e)
            except httpx.TransportError as e:  # timeouts, connection resets
                last = e
            if attempt == self.max_attempts:
                code = getattr(last, "code", None)
                text = (
                    f"{code} {getattr(last, 'status', '')}: {getattr(last, 'message', '')}"
                    if code is not None
                    else f"{type(last).__name__}: {last}"
                )
                cls = LLMQuotaError if code == 429 else LLMError
                raise cls(text, code=code) from last
            if delay is None:
                delay = min(self.max_delay, 2**attempt) * random.uniform(0.5, 1.5)
            if delay > self.max_wait:
                raise LLMQuotaError(
                    f"retryDelay {delay:.0f}s exceeds max_wait {self.max_wait:.0f}s",
                    code=getattr(last, "code", None),
                ) from last
            self.stats.retries += 1
            self.sleep(delay)
        raise LLMError("unreachable")  # pragma: no cover - loop always returns or raises

    # ----------------------------------------------------------- structured

    def _cache_path(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        thinking_level: str | None,
        prompt_version: str,
    ) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(
            json.dumps(
                {
                    "m": model,
                    "s": system,
                    "p": prompt,
                    "sch": gemini_schema(schema),
                    "t": thinking_level,
                    "v": prompt_version,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return self.cache_dir / f"{key}.json"

    def generate_structured(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        purpose: str,
        thinking_level: str | None = None,
        prompt_version: str = "1",
        max_output_tokens: int = 4096,
    ) -> BaseModel:
        path = self._cache_path(
            model=model,
            system=system,
            prompt=prompt,
            schema=schema,
            thinking_level=thinking_level,
            prompt_version=prompt_version,
        )
        if path is not None and path.exists():
            try:
                cached = schema.model_validate_json(json.loads(path.read_text())["text"])
            except (ValueError, KeyError):
                cached = None  # corrupt entry: treat as a miss, it is overwritten below
            if cached is not None:
                self.stats.cache_hits += 1
                return cached

        contents: list = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
        for attempt in (1, 2):  # the original request plus ONE repair
            cfg = build_config(
                system=system,
                schema=schema,
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
            )
            r = self.generate_raw(model, contents, cfg)
            text = r.text if r.candidates else None
            finish = r.candidates[0].finish_reason if r.candidates else None
            finish_name = getattr(finish, "name", str(finish) if finish else "")
            try:
                if not text:
                    raise ValueError(f"empty or blocked response (finish_reason={finish_name})")
                if finish_name == "MAX_TOKENS":
                    raise ValueError("response truncated (finish_reason=MAX_TOKENS)")
                obj = schema.model_validate_json(text)  # pydantic.ValidationError is a ValueError
            except ValueError as ve:
                if attempt == 2:
                    raise LLMSchemaError(f"{purpose}: {str(ve)[:600]}") from ve
                self.stats.repairs += 1
                if finish_name == "MAX_TOKENS":
                    max_output_tokens *= 2
                if text:
                    contents.append(
                        types.Content(role="model", parts=[types.Part.from_text(text=text)])
                    )
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    "Your previous output failed validation: "
                                    f"{str(ve)[:600]}. Return corrected JSON only."
                                )
                            )
                        ],
                    )
                )
                continue
            if path is not None:  # cache ONLY validated output; never the key
                atomic_write_json(
                    path,
                    {
                        "purpose": purpose,
                        "model": model,
                        "prompt_version": prompt_version,
                        "text": text,
                    },
                )
            return obj
        raise LLMSchemaError(f"{purpose}: unreachable")  # pragma: no cover
