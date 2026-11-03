"""FND-02: typed Settings loaded from the process env or a local .env."""

from pathlib import Path

import pytest

from outreach.config import (
    ENV_MAP,
    REQUIRED_VARS,
    ConfigError,
    Settings,
    load_settings,
    redact,
)

# Canary values are deliberately short (<20 chars) so this source never matches
# the secret scanner's key-shape regexes.
GEM = "canary-gem-0001x"
HUN = "canary-hun-0002x"
RES = "canary-res-0003x"
OTHER_GEM = "canary-gem-9999z"


def full_env(**overrides: str) -> dict[str, str]:
    env = {
        "GEMINI_API_KEY": GEM,
        "HUNTER_API_KEY": HUN,
        "RESEND_API_KEY": RES,
        "OWNER_EMAIL": "owner@example.com",
    }
    env.update(overrides)
    return env


def test_defaults_when_optional_vars_absent():
    s = load_settings(env=full_env())
    assert s.gemini_model_smart == "gemini-3.8-flash"
    assert s.gemini_model_fast == "gemini-3.5-flash-lite"
    assert s.hunter_monthly_budget == 25
    assert s.resend_from == "onboarding@resend.dev"
    assert s.owner_email == "owner@example.com"
    assert s.skeleton_domain is None
    assert s.sources["GEMINI_MODEL_SMART"] == "default"


def test_all_vars_are_read_from_mapping():
    env = full_env(
        GEMINI_MODEL_SMART="gemini-x-flash",
        GEMINI_MODEL_FAST="gemini-y-lite",
        HUNTER_MONTHLY_BUDGET="7",
        RESEND_FROM="me@example.com",
        SKELETON_DOMAIN="example.org",
    )
    s = load_settings(env=env)
    assert s.gemini_api_key.get_secret_value() == GEM
    assert s.hunter_api_key.get_secret_value() == HUN
    assert s.resend_api_key.get_secret_value() == RES
    assert s.gemini_model_smart == "gemini-x-flash"
    assert s.gemini_model_fast == "gemini-y-lite"
    assert s.hunter_monthly_budget == 7
    assert s.resend_from == "me@example.com"
    assert s.skeleton_domain == "example.org"
    assert set(ENV_MAP) <= set(s.sources)


def test_process_env_wins_over_dotenv_file(tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"GEMINI_API_KEY={OTHER_GEM}\nHUNTER_API_KEY={HUN}\nSKELETON_DOMAIN=file.example\n"
    )
    env = {
        "GEMINI_API_KEY": GEM,
        "RESEND_API_KEY": RES,
        "OWNER_EMAIL": "owner@example.com",
    }
    s = load_settings(env=env, dotenv_path=dotenv)
    assert s.gemini_api_key.get_secret_value() == GEM
    assert s.sources["GEMINI_API_KEY"] == "env"
    assert s.hunter_api_key.get_secret_value() == HUN
    assert s.sources["HUNTER_API_KEY"] == ".env"
    assert s.skeleton_domain == "file.example"
    assert s.sources["SKELETON_DOMAIN"] == ".env"


def test_given_env_reads_no_file_without_dotenv_path(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text(f"HUNTER_API_KEY={HUN}\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as exc:
        load_settings(env={"GEMINI_API_KEY": GEM, "RESEND_API_KEY": RES, "OWNER_EMAIL": "o@x.com"})
    assert "HUNTER_API_KEY" in str(exc.value)


def test_dotenv_file_is_not_loaded_into_os_environ(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SKELETON_DOMAIN", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("SKELETON_DOMAIN=file.example\n")
    import os

    load_settings(env=full_env(), dotenv_path=dotenv)
    assert "SKELETON_DOMAIN" not in os.environ


def test_missing_required_names_variables_never_values():
    env = {"HUNTER_API_KEY": HUN, "RESEND_API_KEY": RES}
    with pytest.raises(ConfigError) as exc:
        load_settings(env=env)
    msg = str(exc.value)
    assert "GEMINI_API_KEY" in msg
    assert "OWNER_EMAIL" in msg
    for value in (GEM, HUN, RES):
        assert value not in msg
    assert HUN not in msg and RES not in msg


def test_require_subset_succeeds_without_other_keys():
    s = load_settings(
        env={"GEMINI_API_KEY": GEM, "OWNER_EMAIL": "owner@example.com"},
        require=("GEMINI_API_KEY", "OWNER_EMAIL"),
    )
    assert s.gemini_api_key.get_secret_value() == GEM
    assert s.hunter_api_key.get_secret_value() == ""
    assert s.sources["HUNTER_API_KEY"] == "missing"
    assert set(REQUIRED_VARS) == {
        "GEMINI_API_KEY",
        "HUNTER_API_KEY",
        "RESEND_API_KEY",
        "OWNER_EMAIL",
    }


def test_repr_and_str_never_contain_key_values():
    s = load_settings(env=full_env())
    for text in (repr(s), str(s)):
        for value in (GEM, HUN, RES):
            assert value not in text


@pytest.mark.parametrize("bad", ["a@x.com,b@y.com", "not-an-email", "a@x.com;b@y.com", "a b@x.com", "a@nodot"])
def test_owner_email_must_be_single_address(bad: str):
    with pytest.raises(ConfigError) as exc:
        load_settings(env=full_env(OWNER_EMAIL=bad))
    assert "OWNER_EMAIL" in str(exc.value)
    assert bad not in str(exc.value)


@pytest.mark.parametrize(
    ("var", "bad"),
    [
        ("GEMINI_MODEL_SMART", "gemini-flash-latest"),
        ("GEMINI_MODEL_FAST", "gemini-3-flash-preview"),
    ],
)
def test_model_ids_reject_latest_and_preview(var: str, bad: str):
    with pytest.raises(ConfigError) as exc:
        load_settings(env=full_env(**{var: bad}))
    assert var in str(exc.value)
    assert bad not in str(exc.value)


def test_non_integer_budget_is_rejected():
    with pytest.raises(ConfigError) as exc:
        load_settings(env=full_env(HUNTER_MONTHLY_BUDGET="lots"))
    assert "HUNTER_MONTHLY_BUDGET" in str(exc.value)


def test_redact_masks_secrets_and_leaves_short_values():
    s = load_settings(env=full_env())
    assert redact(f"boom {GEM} end", s) == "boom *** end"
    assert redact("boom short end", s, secrets=["short"]) == "boom short end"
    assert redact("x extra-secret-value y", None, secrets=["extra-secret-value"]) == "x *** y"
    assert isinstance(s, Settings)
