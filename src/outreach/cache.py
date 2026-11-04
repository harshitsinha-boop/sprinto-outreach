"""Atomic JSON persistence and domain normalisation shared by caches and run records."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path | str, obj: Any) -> None:
    """Write JSON so a kill mid-write never leaves a half-written file at `path`."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, default=str)
    # A unique temp name per write, so concurrent writers never collide on one `.tmp` file.
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        try:
            os.replace(tmp, target)
        except OSError:
            # Some serverless filesystems refuse the rename (EBUSY); a direct write still works.
            target.write_text(payload)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def read_json(path: Path | str, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text())


def normalize_domain(raw: str) -> str:
    """Strip whitespace, scheme, path, query, port, a leading www. and a trailing dot."""
    value = (raw or "").strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    for sep in ("/", "?", "#"):
        value = value.split(sep, 1)[0]
    value = value.rsplit("@", 1)[-1]
    value = value.split(":", 1)[0]
    value = value.rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    if not value:
        raise ValueError("domain is empty after normalisation")
    return value
