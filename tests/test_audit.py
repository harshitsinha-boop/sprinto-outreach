"""LOG-01: the run record is flushed before stage 1 and after every stage, atomically."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import CANARY_ENV, FakeLLM
from outreach.audit import RunStore
from outreach.cache import atomic_write_json, normalize_domain
from outreach.skeleton import run_one

DOMAIN = CANARY_ENV["SKELETON_DOMAIN"]
REPO_ROOT = Path(__file__).resolve().parent.parent
STAGE_ORDER = ["scrape", "extract", "qualify", "hunter", "draft", "send"]


class SnapshotStore(RunStore):
    """Records the stage names present at every flush."""

    def __init__(self, out_dir):
        super().__init__(out_dir)
        self.snapshots: list[list[str]] = []

    def flush(self, rec):
        self.snapshots.append([s.name for s in rec.stages])
        return super().flush(rec)


def test_per_stage_flush_snapshots(ctx):
    ctx.store = SnapshotStore(ctx.settings.out_dir)

    run_one(DOMAIN, ctx)

    expected = [STAGE_ORDER[:n] for n in range(0, 7)] + [STAGE_ORDER]
    assert ctx.store.snapshots == expected


def test_per_stage_failure_keeps_prior_stages(ctx):
    ctx.llm = FakeLLM(raise_on={"draft": RuntimeError("draft exploded")})

    with pytest.raises(RuntimeError):
        run_one(DOMAIN, ctx)

    data = json.loads(ctx.store.path_for(DOMAIN).read_text())
    assert data["status"] == "failed"
    assert data["failed_stage"] == "draft"
    assert [(s["name"], s["status"]) for s in data["stages"]] == [
        ("scrape", "ok"),
        ("extract", "ok"),
        ("qualify", "ok"),
        ("hunter", "ok"),
        ("draft", "failed"),
    ]
    assert "draft exploded" in data["stages"][-1]["error"]


HARD_KILL_SCRIPT = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[2])  # the repo's tests directory
    from conftest import CANARY_ENV, FakeFetcher, FakeHunter, FakeLLM
    from outreach.audit import RunStore
    from outreach.config import load_settings
    from outreach.skeleton import Context, run_one

    out_dir = Path(sys.argv[1])
    settings = load_settings(env=CANARY_ENV).model_copy(
        update={"out_dir": out_dir, "cache_dir": out_dir.parent / ".cache"}
    )

    def hook(purpose, call):
        if purpose == "draft":
            os._exit(17)  # no finally block, no atexit: only per-stage flushes can survive

    ctx = Context(
        settings=settings,
        llm=FakeLLM(on_call=hook),
        hunter=FakeHunter(),
        fetcher=FakeFetcher(),
        store=RunStore(out_dir),
    )
    run_one(CANARY_ENV["SKELETON_DOMAIN"], ctx)
    """
)


def test_hard_kill_leaves_partial_trail(tmp_path):
    script = tmp_path / "kill_run.py"
    script.write_text(HARD_KILL_SCRIPT)
    out_dir = tmp_path / "out"

    proc = subprocess.run(
        [sys.executable, str(script), str(out_dir), str(REPO_ROOT / "tests")],
        env={**os.environ, "PYTHONPATH": "src" + os.pathsep + "tests"},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 17, proc.stderr
    data = json.loads((out_dir / DOMAIN / "run.json").read_text())
    assert data["status"] == "running"
    assert [s["name"] for s in data["stages"]] == ["scrape", "extract", "qualify", "hunter"]


def test_atomic_write_leaves_no_tmp(ctx, tmp_path):
    run_one(DOMAIN, ctx)
    run_dir = ctx.store.path_for(DOMAIN).parent
    assert [p.name for p in run_dir.iterdir()] == ["run.json"]

    target = tmp_path / "nested" / "dir" / "obj.json"
    atomic_write_json(target, {"a": 1})
    atomic_write_json(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 2}
    assert list(target.parent.glob("*.tmp")) == []


def test_normalize_domain_variants():
    for raw in ("HTTPS://WWW.Example.com/about?x=1", "example.com.", "  Example.COM:443 "):
        assert normalize_domain(raw) == "example.com"
    with pytest.raises(ValueError):
        normalize_domain("   ")
