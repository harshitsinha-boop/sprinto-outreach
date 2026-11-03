"""Typed settings loaded from the process environment or a local .env (FND-02).

Secrets are typed as SecretStr so repr/str are masked, errors name variables and
never values, and `.env` is read with `dotenv_values` so os.environ is not mutated.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from dotenv import dotenv_values, find_dotenv
from pydantic import BaseModel, ConfigDict, SecretStr


class ConfigError(Exception):
    """Raised for missing or invalid settings. Messages name variables, never values."""


ENV_MAP: dict[str, str] = {
    "GEMINI_API_KEY": "gemini_api_key",
    "HUNTER_API_KEY": "hunter_api_key",
    "RESEND_API_KEY": "resend_api_key",
    "OWNER_EMAIL": "owner_email",
    "GEMINI_MODEL_SMART": "gemini_model_smart",
    "GEMINI_MODEL_FAST": "gemini_model_fast",
    "HUNTER_MONTHLY_BUDGET": "hunter_monthly_budget",
    "RESEND_FROM": "resend_from",
    "SKELETON_DOMAIN": "skeleton_domain",
}
SECRET_VARS: tuple[str, ...] = ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY")
REQUIRED_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "HUNTER_API_KEY",
    "RESEND_API_KEY",
    "OWNER_EMAIL",
)
_HAS_DEFAULT = {"GEMINI_MODEL_SMART", "GEMINI_MODEL_FAST", "HUNTER_MONTHLY_BUDGET", "RESEND_FROM"}
_MIN_SECRET_LEN = 8
_SINGLE_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    gemini_api_key: SecretStr = SecretStr("")
    hunter_api_key: SecretStr = SecretStr("")
    resend_api_key: SecretStr = SecretStr("")
    owner_email: str = ""
    gemini_model_smart: str = "gemini-3.8-flash"
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    hunter_monthly_budget: int = 25
    resend_from: str = "onboarding@resend.dev"
    skeleton_domain: str | None = None
    cache_dir: Path = Path(".cache")
    out_dir: Path = Path("out")
    # Variable name -> "env" | ".env" | "default" | "missing". Names only, never values.
    sources: dict[str, str] = {}

    def secret_values(self) -> list[str]:
        values = (
            self.gemini_api_key.get_secret_value(),
            self.hunter_api_key.get_secret_value(),
            self.resend_api_key.get_secret_value(),
        )
        return [v for v in values if v and len(v) >= _MIN_SECRET_LEN]


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
    require: Iterable[str] = REQUIRED_VARS,
) -> Settings:
    """Build Settings from the process env (or `env`) layered over a local .env file.

    A non-empty process value wins over a file value. When `env` is given and
    `dotenv_path` is None no file is read, which keeps tests hermetic.
    """
    required = tuple(require)
    process: Mapping[str, str] = os.environ if env is None else env

    path: str | Path | None = dotenv_path
    if path is None and env is None:
        found = find_dotenv(usecwd=True)
        path = found or None
    file_values: dict[str, str] = {}
    if path is not None:
        file_values = {k: v for k, v in dotenv_values(path).items() if v is not None}

    raw: dict[str, str] = {}
    sources: dict[str, str] = {}
    for name in ENV_MAP:
        from_process = (process.get(name) or "").strip()
        from_file = (file_values.get(name) or "").strip()
        if from_process:
            raw[name], sources[name] = from_process, "env"
        elif from_file:
            raw[name], sources[name] = from_file, ".env"
        elif name in _HAS_DEFAULT:
            sources[name] = "default"
        else:
            sources[name] = "missing"

    missing = [name for name in required if name not in raw]
    if missing:
        raise ConfigError(
            f"Missing required settings: {', '.join(missing)}. "
            "Set them in .env (see .env.example)."
        )

    owner = raw.get("OWNER_EMAIL")
    if owner is not None and not _SINGLE_EMAIL.match(owner):
        raise ConfigError("OWNER_EMAIL must be exactly one email address.")

    for name in ("GEMINI_MODEL_SMART", "GEMINI_MODEL_FAST"):
        value = raw.get(name)
        if value is not None and any(bad in value.lower() for bad in ("latest", "preview")):
            raise ConfigError(f"{name} must be a pinned model ID (no 'latest' or 'preview').")

    fields: dict[str, object] = {}
    for name, value in raw.items():
        field = ENV_MAP[name]
        if name == "HUNTER_MONTHLY_BUDGET":
            try:
                budget = int(value)
            except ValueError:
                raise ConfigError("HUNTER_MONTHLY_BUDGET must be an integer.") from None
            if budget < 0:
                raise ConfigError("HUNTER_MONTHLY_BUDGET must not be negative.")
            fields[field] = budget
        elif name in SECRET_VARS:
            fields[field] = SecretStr(value)
        else:
            fields[field] = value
    return Settings(sources=sources, **fields)


def redact(
    text: str, settings: Settings | None = None, *, secrets: Iterable[str] = ()
) -> str:
    """Replace every secret value of length >= 8 with '***'."""
    values = set(secrets)
    if settings is not None:
        values.update(settings.secret_values())
    for value in sorted((v for v in values if len(v) >= _MIN_SECRET_LEN), key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def configure_logging() -> None:
    """Quiet chatty HTTP loggers; httpx logs full request URLs at INFO."""
    for name in ("httpx", "httpcore", "google_genai", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
