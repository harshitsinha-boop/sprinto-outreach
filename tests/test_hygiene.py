"""FND-01: ignore rules, .env.example shape and the secret scanner."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "scripts" / "check_secrets.py"

# Short canaries so this source never matches the scanner's key-shape regexes.
CANARY = "canary-gem-0001x"

SECRET_VARS = ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY")


def git_check_ignore(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=REPO, capture_output=True, check=False
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", ".cache/llm/x.json", "out/x/run.json", ".venv/bin/python",
     "src/sprinto_outreach.egg-info/PKG-INFO"],
)
def test_gitignore_matches_secret_and_generated_paths(path: str):
    assert git_check_ignore(path), path


@pytest.mark.parametrize(
    "path",
    [".env.example", "src/outreach/config.py", "tests/fixtures/page.html",
     ".planning/STATE.md", "requirements.lock.txt"],
)
def test_gitignore_does_not_match_committable_paths(path: str):
    assert not git_check_ignore(path), path


def test_gitignore_rules():
    # Aggregate of the two parametrised groups above, kept as a named entry point.
    assert git_check_ignore(".env") and git_check_ignore("out/x/run.json")
    assert not git_check_ignore(".env.example") and not git_check_ignore(".planning/STATE.md")


def test_env_example_shape():
    values = dotenv_values(REPO / ".env.example")
    for key in ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY", "OWNER_EMAIL"):
        assert key in values, key
        assert values[key] in ("", None), key
    assert values["GEMINI_MODEL_SMART"] == "gemini-3.8-flash"
    assert values["GEMINI_MODEL_FAST"] == "gemini-3.5-flash-lite"
    assert values["HUNTER_MONTHLY_BUDGET"] == "25"
    assert values["RESEND_FROM"] == "onboarding@resend.dev"
    assert "SKELETON_DOMAIN" in values
    assert "RECIPIENT_EMAIL" not in values


# ---------------------------------------------------------------- scanner ---


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text((REPO / ".gitignore").read_text())
    (repo / ".env.example").write_text((REPO / ".env.example").read_text())
    _git(repo, "add", ".gitignore", ".env.example")
    _git(repo, "commit", "-q", "-m", "chore: gitignore and env example")
    return repo


def run_scanner(repo: Path, *, canary: str | None = CANARY) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_VARS}
    if canary is not None:
        env["GEMINI_API_KEY"] = canary
    return subprocess.run(
        [sys.executable, str(SCANNER), "--root", str(repo)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_secrets_clean_repo_exits_zero(temp_repo: Path):
    result = run_scanner(temp_repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("OK: no secrets found")


def test_check_secrets_flags_tracked_file(temp_repo: Path):
    (temp_repo / "notes.txt").write_text(f"token = {CANARY}\n")
    _git(temp_repo, "add", "notes.txt")
    _git(temp_repo, "commit", "-q", "-m", "add notes")
    result = run_scanner(temp_repo)
    assert result.returncode == 1
    assert "notes.txt" in result.stdout
    assert CANARY not in result.stdout + result.stderr


def test_check_secrets_flags_untracked_file(temp_repo: Path):
    (temp_repo / "scratch.txt").write_text(f"{CANARY}\n")
    result = run_scanner(temp_repo)
    assert result.returncode == 1
    assert "scratch.txt" in result.stdout
    assert CANARY not in result.stdout + result.stderr


def test_check_secrets_flags_gitignored_out_file(temp_repo: Path):
    (temp_repo / "out" / "acme.com").mkdir(parents=True)
    (temp_repo / "out" / "acme.com" / "run.json").write_text(f'{{"leak": "{CANARY}"}}\n')
    result = run_scanner(temp_repo)
    assert result.returncode == 1
    assert "run.json" in result.stdout
    assert CANARY not in result.stdout + result.stderr


def test_check_secrets_flags_history_only_leak(temp_repo: Path):
    leaked = temp_repo / "oops.txt"
    leaked.write_text(f"{CANARY}\n")
    _git(temp_repo, "add", "oops.txt")
    _git(temp_repo, "commit", "-q", "-m", "oops")
    _git(temp_repo, "rm", "-q", "oops.txt")
    _git(temp_repo, "commit", "-q", "-m", "remove oops")
    result = run_scanner(temp_repo)
    assert result.returncode == 1
    assert "history" in result.stdout.lower()
    assert CANARY not in result.stdout + result.stderr


def test_check_secrets_flags_key_shaped_string(temp_repo: Path):
    shaped = "AIza" + "x" * 35  # built at runtime so this source holds no full key shape
    (temp_repo / "config_dump.txt").write_text(f"key: {shaped}\n")
    result = run_scanner(temp_repo, canary=None)
    assert result.returncode == 1
    assert "config_dump.txt" in result.stdout
    assert shaped not in result.stdout + result.stderr


def test_check_secrets_flags_tracked_dotenv(temp_repo: Path):
    # .env must never be tracked: the hygiene check fails even with no key values set.
    (temp_repo / ".env").write_text("GEMINI_API_KEY=\n")
    _git(temp_repo, "add", "-f", ".env")
    _git(temp_repo, "commit", "-q", "-m", "force add env")
    result = run_scanner(temp_repo, canary=None)
    assert result.returncode == 1
    assert "hygiene" in result.stdout.lower()
