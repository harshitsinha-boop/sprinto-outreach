"""Cache-first, budget-capped Hunter Domain Search client (T-01-10, T-01-11).

Hunter's free tier is tiny, so the contract is strict:
- a cache hit costs nothing and never touches the budget;
- a miss costs one live call whose response is written to disk BEFORE it is returned
  (zero-result 200s included), so nothing downstream can force a second credit;
- 401 and 429 are raised and never cached or retried;
- the persistent monthly counter refuses a call beyond the budget with no HTTP request.

The key travels only in the `X-API-KEY` header. Error text carries status and Hunter
error ids only.

The `.cache/hunter/<domain>.json` envelope is read by Phase 4; keep it stable.
"""

from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from outreach.audit import now_iso
from outreach.cache import atomic_write_json, normalize_domain, read_json

BASE = "https://api.hunter.io/v2"
# Free plan rejects limit + offset above 10, so offset is never sent.
SEARCH_PARAMS = {
    "type": "personal",
    "required_field": "full_name,position",
    "seniority": "senior,executive",
    "limit": 10,
}
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "hunter_domain_search.json"


# Per-process live-call counter by month. On Vercel the /tmp usage file is per instance and may be
# reset on a cold start, so this in-memory count is a second, independent brake within an instance.
_INSTANCE_LIVE_CALLS: dict[str, int] = {}


class HunterError(Exception):
    pass


class HunterAuthError(HunterError):
    """401: bad key. Systemic."""


class HunterQuotaError(HunterError):
    """429 usage limit or the local budget. Never retried."""


def _error_ids(r: httpx.Response) -> str:
    try:
        errs = r.json().get("errors") or []
    except ValueError:
        errs = []
    ids = [str(e.get("id")) for e in errs if isinstance(e, dict) and e.get("id")]
    return ", ".join(ids) or "no error id"


class HunterClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        budget: int,
        *,
        http: httpx.Client | None = None,
        month: Callable[[], str] | None = None,
        instance_counter: bool | None = None,
    ):
        self._instance_counter = (
            bool(os.environ.get("VERCEL")) if instance_counter is None else instance_counter
        )
        self._key = api_key
        self.dir = Path(cache_dir)
        self.budget = budget
        self._http = http or httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))
        self._month = month or (lambda: time.strftime("%Y-%m"))
        self.live_calls_this_process = 0

    # -------------------------------------------------------------- errors

    def _raise(self, r: httpx.Response) -> None:
        code = r.status_code
        if code < 400:
            return
        ids = _error_ids(r)
        if code == 401:
            raise HunterAuthError(f"Hunter 401 invalid API key ({ids})")
        if code == 429:
            raise HunterQuotaError(f"Hunter 429 usage limit reached ({ids})")
        if code == 403:
            raise HunterError(f"Hunter 403 rate limit ({ids})")
        if code == 451:
            raise HunterError(f"Hunter 451 person asked not to be processed ({ids})")
        raise HunterError(f"Hunter {code} ({ids})")

    def _get(self, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.get(
                f"{BASE}{path}", headers={"X-API-KEY": self._key}, **kwargs
            )
        except httpx.HTTPError as e:  # type name only: never echo request details
            raise HunterError(f"Hunter request failed: {type(e).__name__}") from None

    # ------------------------------------------------------------- account

    def account(self) -> dict:
        """Free call. The body holds the owner's personal data, so it is never persisted."""
        r = self._get("/account")
        self._raise(r)
        data = (r.json() or {}).get("data") or {}
        requests = data.get("requests") or {}
        credits = (requests.get("credits") or {}).get("remaining")
        searches = (requests.get("searches") or {}).get("remaining")
        # Explicit None checks, never truthiness: a real 0 must stay 0.
        remaining = credits if credits is not None else searches
        return {
            "plan": data.get("plan_name"),
            "reset_date": data.get("reset_date"),
            "remaining": remaining,
        }

    # ------------------------------------------------------- domain search

    def _usage(self) -> dict:
        month = self._month()
        usage = read_json(self.dir / "_usage.json", None)
        if not isinstance(usage, dict) or usage.get("month") != month:
            usage = {"month": month, "live_calls": 0, "credits_used": 0.0}
        return usage

    def domain_search(self, domain: str) -> dict:
        domain = normalize_domain(domain)
        path = self.dir / f"{domain}.json"
        if path.exists():
            entry = json.loads(path.read_text())
            return {**entry, "from_cache": True, "source": "cache"}

        usage = self._usage()
        if usage["live_calls"] >= self.budget:
            raise HunterQuotaError(
                f"local Hunter budget {self.budget} reached for {usage['month']}; "
                "check /v2/account before raising HUNTER_MONTHLY_BUDGET"
            )

        if self._instance_counter and _INSTANCE_LIVE_CALLS.get(usage["month"], 0) >= self.budget:
            raise HunterQuotaError(
                f"per-instance Hunter budget {self.budget} reached for {usage['month']}"
            )

        r = self._get("/domain-search", params={"domain": domain, **SEARCH_PARAMS})
        self._raise(r)  # 401/403/429/451/other errors are never cached

        header = r.headers.get("X-Credits-Used")
        entry = {
            "domain": domain,
            "fetched_at": now_iso(),
            "params": SEARCH_PARAMS,
            "credits_used": header,
            "response": r.json(),
        }
        atomic_write_json(path, entry)  # BEFORE anything downstream, zero results included
        try:
            spent = float(header) if header is not None else 0.0
        except ValueError:
            spent = 0.0
        usage["live_calls"] += 1
        usage["credits_used"] = float(usage.get("credits_used", 0.0)) + spent
        atomic_write_json(self.dir / "_usage.json", usage)
        self.live_calls_this_process += 1
        _INSTANCE_LIVE_CALLS[usage["month"]] = _INSTANCE_LIVE_CALLS.get(usage["month"], 0) + 1
        return {**entry, "from_cache": False, "source": "live"}


class FixtureHunter:
    """Offline stand-in for `--hunter-fixture`. The captured contact belongs to the
    fixture's own domain only; every other domain gets zero emails, so the skeleton stops
    with `no_contact` instead of addressing a real company's mail to a fixture person."""

    def __init__(self, path: Path = FIXTURE_PATH):
        try:
            self._fixture = json.loads(Path(path).read_text())
        except FileNotFoundError:
            # Deployed bundles do not ship tests/; an empty fixture keeps every domain at no_contact.
            self._fixture = {"data": {"domain": "piedpiper.com", "emails": []}, "meta": {"results": 0}}
        self.fixture_domain = normalize_domain(self._fixture["data"]["domain"])
        self.live_calls_this_process = 0

    def domain_search(self, domain: str) -> dict:
        domain = normalize_domain(domain)
        if domain == self.fixture_domain:
            response = copy.deepcopy(self._fixture)
        else:
            response = {
                "data": {"domain": domain, "emails": []},
                "meta": {"results": 0},
            }
        return {"domain": domain, "response": response, "from_cache": False, "source": "fixture"}

    def account(self) -> dict:
        return {"plan": "fixture", "reset_date": None, "remaining": None}
