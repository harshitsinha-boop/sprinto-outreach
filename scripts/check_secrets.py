"""Secret scanner (FND-01). Exits 1 on any hit; prints paths and reasons only.

Checks: (1) configured key values in files, (2) key values anywhere in git history,
(3) key-shaped strings in files, (4) repo hygiene (.env ignored/untracked, empty
.env.example secrets, .gitignore commit precedes the first src/ commit).
Never prints a key value or the matched text.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

SECRET_VARS = ("GEMINI_API_KEY", "HUNTER_API_KEY", "RESEND_API_KEY")
MIN_SECRET_LEN = 8
SHAPES = (
    ("google-key-shape", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("resend-key-shape", re.compile(r"\bre_[A-Za-z0-9_]{20,}\b")),
    (
        "generic-key-shape",
        re.compile(r"(api[_-]?key|authorization)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{24,}", re.IGNORECASE),
    ),
)
SKIP_PARTS = {".git", ".venv"}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False
    )


def _git_lines(root: Path, *args: str) -> list[str]:
    result = _git(root, *args)
    if result.returncode != 0:
        return []
    return [ln for ln in result.stdout.decode("utf-8", "replace").splitlines() if ln]


def _collect_files(root: Path) -> list[Path]:
    rels: set[str] = set()
    rels.update(_git_lines(root, "ls-files"))
    rels.update(_git_lines(root, "ls-files", "-o", "--exclude-standard"))
    for extra in ("out", ".cache"):
        base = root / extra
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file():
                    rels.add(p.relative_to(root).as_posix())
    files = []
    for rel in sorted(rels):
        parts = Path(rel).parts
        if rel == ".env" or SKIP_PARTS.intersection(parts):
            continue
        p = root / rel
        if p.is_file():
            files.append(p)
    return files


def _secret_values(root: Path) -> dict[str, str]:
    """Configured secret values (name -> value) from <root>/.env and os.environ."""
    found: dict[str, str] = {}
    env_file = root / ".env"
    if env_file.is_file():
        for name, value in dotenv_values(env_file).items():
            if name in SECRET_VARS and value and len(value) >= MIN_SECRET_LEN:
                found[name] = value
    for name in SECRET_VARS:
        value = os.environ.get(name, "")
        if value and len(value) >= MIN_SECRET_LEN:
            found[name] = value
    return found


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def check_values(root: Path, files: list[Path], secrets: dict[str, str]) -> list[str]:
    fails = []
    needles = [v.encode() for v in secrets.values()]
    if not needles:
        return fails
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(n in data for n in needles):
            fails.append(f"FAIL value: {_rel(root, path)}")
    return fails


def check_history(root: Path, secrets: dict[str, str]) -> list[str]:
    if not secrets:
        return []
    result = _git(root, "log", "--all", "-p")
    if result.returncode != 0:
        return []
    history = result.stdout
    return [
        f"FAIL history: git history contains the configured value of {name}"
        for name, value in secrets.items()
        if value.encode() in history
    ]


def check_shapes(root: Path, files: list[Path]) -> list[str]:
    fails = []
    for path in files:
        try:
            text = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        hit = None
        for line in text.splitlines():
            for label, pattern in SHAPES:
                if pattern.search(line):
                    hit = label
                    break
            if hit:
                break
        if hit:
            fails.append(f"FAIL shape ({hit}): {_rel(root, path)}")
    return fails


def check_hygiene(root: Path) -> list[str]:
    fails = []
    if _git(root, "check-ignore", "-q", ".env").returncode != 0:
        fails.append("FAIL hygiene: .env is not ignored by .gitignore")
    if _git_lines(root, "ls-files", ".env"):
        fails.append("FAIL hygiene: .env is tracked by git")
    if _git_lines(root, "log", "--all", "--oneline", "--", ".env"):
        fails.append("FAIL hygiene: .env appears in git history")

    example = root / ".env.example"
    if example.is_file():
        values = dotenv_values(example)
        for name in (*SECRET_VARS, "OWNER_EMAIL"):
            if values.get(name):
                fails.append(f"FAIL hygiene: .env.example has a non-empty value for {name}")

    ignore_commits = _git_lines(
        root, "log", "--all", "--diff-filter=A", "--reverse", "--format=%H", "--", ".gitignore"
    )
    src_commits = _git_lines(
        root, "log", "--all", "--diff-filter=A", "--reverse", "--format=%H", "--", "src/"
    )
    if src_commits:
        if not ignore_commits:
            fails.append("FAIL hygiene: src/ is committed but .gitignore never was")
        else:
            ancestor = _git(root, "merge-base", "--is-ancestor", ignore_commits[0], src_commits[0])
            if ancestor.returncode != 0:
                fails.append("FAIL hygiene: .gitignore commit does not precede the first src/ commit")
    return fails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan the repo for leaked secrets.")
    parser.add_argument("--root", type=Path, default=None, help="repository root")
    args = parser.parse_args(argv)

    if args.root is not None:
        root = args.root.resolve()
    else:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, check=False
        )
        if top.returncode != 0:
            print("FAIL hygiene: not inside a git repository")
            return 1
        root = Path(top.stdout.decode().strip())

    files = _collect_files(root)
    secrets = _secret_values(root)

    fails: list[str] = []
    fails += check_values(root, files, secrets)
    fails += check_history(root, secrets)
    fails += check_shapes(root, files)
    fails += check_hygiene(root)

    if fails:
        print("\n".join(fails))
        return 1
    print(f"OK: no secrets found ({len(files)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
