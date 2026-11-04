"""GET /api/health: password-protected config check (booleans only, never values)."""

from __future__ import annotations

import sys
from pathlib import Path

# The function's import path does not include this folder by default on Vercel.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from run import handler as _run_handler  # noqa: E402  (sets the data dir and src path)


class handler(_run_handler):  # noqa: N801
    pass
