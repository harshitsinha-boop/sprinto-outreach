"""Per-domain run record persistence (LOG-01): one atomic flush per stage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from outreach.cache import atomic_write_json, normalize_domain, read_json
from outreach.models import RunRecord


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStore:
    """Sole writer of out/<domain>/run.json."""

    def __init__(self, out_dir: Path | str):
        self.out_dir = Path(out_dir)

    def path_for(self, domain: str) -> Path:
        return self.out_dir / normalize_domain(domain) / "run.json"

    def flush(self, rec: RunRecord) -> Path:
        path = self.path_for(rec.domain)
        atomic_write_json(path, rec.model_dump(mode="json"))
        if rec.status != "running":
            self._write_decision(rec, path.parent)
        return path

    @staticmethod
    def _write_decision(rec: RunRecord, folder: Path) -> None:
        """decision.md beside run.json once the run is finished. Best effort: never fails a run."""
        try:
            from outreach.decision import render_decision

            (folder / "decision.md").write_text(render_decision(rec), encoding="utf-8")
        except Exception:  # noqa: BLE001 - the log is a convenience, run.json is the record
            pass

    def load(self, domain: str) -> RunRecord | None:
        data = read_json(self.path_for(domain))
        return RunRecord.model_validate(data) if data is not None else None
