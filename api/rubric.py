"""GET /api/rubric: public, non-secret ICP rubric parsed from config/icp.toml."""

from __future__ import annotations

from run import handler as _run_handler  # noqa: F401  (sets path and data dir)


class handler(_run_handler):  # noqa: N801
    pass
