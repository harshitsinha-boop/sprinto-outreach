---
phase: 01-foundation-and-walking-skeleton
plan: 01
subsystem: infra
tags: [python, pydantic, python-dotenv, secret-hygiene, gitignore, pytest]
status: complete

requires: []
provides:
  - ".gitignore and .env.example committed before any code (first Phase 1 commit)"
  - "Installable package sprinto-outreach with 12 human-approved packages, pinned in requirements.lock.txt"
  - "outreach.config: Settings (SecretStr keys), load_settings, ConfigError, redact, configure_logging, ENV_MAP, SECRET_VARS, REQUIRED_VARS"
  - "scripts/check_secrets.py: value, history, shape and hygiene scanner"
affects: [01-02, 01-03, 01-04, phase-2, phase-3, phase-4, phase-5, phase-6]

actuals:
  tokens: 9700
  tasks: 3
  commits: 2
plan_head_before: 16ef22b07023b6f25fe9e96947ad6de165569ec6
plan_head_after: 75131cec5fcc9372bd1e255d0d51deafc5631270

tech-stack:
  added: [google-genai 2.34.0, pydantic 2.14.2, httpx 0.28.1, trafilatura 2.3.1, beautifulsoup4 4.15.0, lxml 6.1.3, resend 2.50.1, typer 0.27.3, python-dotenv 1.2.4, pytest 9.2.0, respx 0.23.1, setuptools build backend]
  patterns:
    - "Settings is a frozen pydantic BaseModel with SecretStr keys; no pydantic-settings"
    - ".env read via dotenv_values (never load_dotenv) layered under the process env; per-variable source recorded"
    - "Errors name variables only, never values"

key-files:
  created:
    - .gitignore
    - .env.example
    - pyproject.toml
    - requirements.lock.txt
    - src/outreach/__init__.py
    - src/outreach/config.py
    - scripts/check_secrets.py
    - tests/test_config.py
    - tests/test_hygiene.py
  modified:
    - CLAUDE.md
    - .planning/research/STACK.md

key-decisions:
  - "OWNER_EMAIL replaces RECIPIENT_EMAIL everywhere (CLAUDE.md x3, STACK.md x4); Phases 2-6 use OWNER_EMAIL"
  - "Env variable names and Settings field names are the contract for all later phases and the user's local .env"

requirements-completed: [FND-01, FND-02]

coverage:
  - id: D1
    description: ".gitignore and .env.example are the first Phase 1 commit, ignore rules hold"
    requirement: FND-01
    verification:
      - kind: unit
        ref: "tests/test_hygiene.py#test_gitignore_rules"
        status: pass
  - id: D2
    description: "Typed Settings loads every variable from env or .env with names-only errors and masked keys"
    requirement: FND-02
    verification:
      - kind: unit
        ref: "tests/test_config.py"
        status: pass
  - id: D3
    description: "Secret scanner fails on every planted leak and passes on the real repo"
    requirement: FND-01
    verification:
      - kind: integration
        ref: "tests/test_hygiene.py#test_check_secrets_*"
        status: pass
      - kind: other
        ref: ".venv/bin/python scripts/check_secrets.py"
        status: pass
---

# Phase 1 Plan 1: Secret hygiene and typed configuration Summary

**`.gitignore` + `.env.example` committed first, then a pydantic `Settings` loader (SecretStr keys, names-only errors, env-over-.env precedence) and a four-check secret scanner covering files, `out/`, `.cache/` and git history, with 12 human-approved packages pinned.**

## Accomplishments

- Task 1 (commit 5296f62): `.gitignore` and `.env.example` landed alone as the first Phase 1 commit. `.env.example` has empty secret values and `OWNER_EMAIL`; `RECIPIENT_EMAIL` does not appear.
- Task 2: package-legitimacy checkpoint resolved with "approved" for all 12 packages (11 plus setuptools); no `.venv` existed beforehand. Installed into `.venv` only after approval.
- Task 3 (commit 75131ce): `pyproject.toml`, editable install, `pip check` clean, `requirements.lock.txt` frozen (`google-genai==2.34.0`, `resend==2.50.1`, `pydantic==2.14.2`, `httpx==0.28.1`, no `-e` line), `config.py`, `check_secrets.py`, 37 passing tests, and the `RECIPIENT_EMAIL` to `OWNER_EMAIL` rename.
- `scripts/check_secrets.py` on the real repo prints `OK: no secrets found (29 files scanned)`; in temp repos it exits 1 for tracked, untracked, gitignored `out/`, history-only and key-shaped leaks and for a tracked `.env`, naming files but never the value.

## Task Commits

1. Task 1: `5296f62` chore(01-01): add .gitignore and .env.example before any code (FND-01)
2. Task 2: checkpoint (no commit)
3. Task 3: `75131ce` feat(01-01): add typed Settings loader, secret scanner and pinned deps (FND-01, FND-02)

## Deviations from Plan

### Auto-fixed Issues

None - no bugs surfaced; behavior matched the plan.

### Process notes

**1. [TDD cadence] RED observed, single commit for Task 3**
- Tests were written first and run before `config.py` existed: collection failed with `ModuleNotFoundError: No module named 'outreach.config'`. By the strict `tdd.md` classifier that is an import-level failure (INVALID_RED style), not an assertion-level RED, so it was not used to authorize anything beyond writing the implementation.
- The plan is `type: execute` with one commit per task, and a separate RED commit would leave a broken-collection commit in history. Tests and implementation were committed together in 75131ce, which the plan's success criteria ("Task 3 committed") expect. The plan frontmatter's own gate is the green run (37 passed).

**2. [Scanner detail] Shape regex applied per line**
- The plan gives the third shape regex with `\s*` after the separator; applied across a whole file that could span a newline (for example `GEMINI_API_KEY=` followed by the next line). The scanner applies each regex line by line, which keeps the intended behavior without cross-line false positives. No effect on the specified detections.

**3. [Ledger] Plan commit ledger created after Task 1**
- The head-before ledger file was created at Task 3 time, but it was seeded with 16ef22b (parent of Task 1's commit), so `git rev-list --count 16ef22b..HEAD` is 2 and matches the two code commits.

**4. [Tests] Extra tests beyond the plan's count**
- 37 tests versus the 15 minimum: parametrised ignore-rule and OWNER_EMAIL cases, a non-integer budget test, a no-os.environ-mutation test and a tracked-`.env` scanner test. Tests named in the plan (`test_gitignore_rules`, `test_env_example_shape`, `test_check_secrets_*`) exist.

## Authentication Gates

None. Task 2 was a package-legitimacy human-verify checkpoint, not an auth gate; resolved with "approved".

## Known Stubs

None. The `outreach = "outreach.cli:app"` console-script entry in `pyproject.toml` points at a module that arrives in Plan 01-03; it is metadata only (documented in the plan), not wired UI or data.

## Threat Flags

None. No new network endpoints, auth paths or trust-boundary file access beyond the plan's threat model (T-01-01 to T-01-04, T-01-SC all mitigated as specified).

## Verification

- `.venv/bin/python -m pytest -q`: 37 passed
- `.venv/bin/python -m pip check`: No broken requirements found
- `.venv/bin/python scripts/check_secrets.py`: OK, exit 0
- `git diff-tree` on the commit that added `.gitignore`: exactly `.env.example` and `.gitignore`
- `grep -c RECIPIENT_EMAIL` is 0 in `CLAUDE.md` and `.planning/research/STACK.md`; `OWNER_EMAIL` count is 3 and 4
- `git status --short`: no `.env`, no `*.egg-info`

## Self-Check: PASSED

- FOUND: pyproject.toml, requirements.lock.txt, src/outreach/__init__.py, src/outreach/config.py, scripts/check_secrets.py, tests/test_config.py, tests/test_hygiene.py
- FOUND commits: 5296f62, 75131ce (both ancestors of HEAD)
