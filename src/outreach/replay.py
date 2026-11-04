"""`--replay`: re-run a batch purely from the on-disk caches, with no network and no send.

Each seam is the real, cache-first client with its network path replaced by one that raises
`ReplayMiss`, so an uncached call is a recorded per-domain failure instead of a silent live call.
"""

from __future__ import annotations

import json

import httpx

from outreach.audit import RunStore
from outreach.cache import normalize_domain
from outreach.config import Settings
from outreach.fetch import PageFetcher
from outreach.hunter import FixtureHunter
from outreach.llm import LLMClient
from outreach.skeleton import Context


class ReplayMiss(Exception):
    """Replay needed something that is not in the caches."""


def _no_http(request: httpx.Request) -> httpx.Response:
    raise ReplayMiss(f"not cached (replay makes no network calls): {request.url.host}")


class _NoGenai:
    class models:  # noqa: N801 - mimics genai.Client().models
        @staticmethod
        def generate_content(**kwargs):
            raise ReplayMiss("LLM response not cached (replay makes no network calls)")


class ReplayHunter:
    """Reads `.cache/hunter/<domain>.json` only."""

    live_calls_this_process = 0

    def __init__(self, cache_dir):
        self.dir = cache_dir

    def domain_search(self, domain: str) -> dict:
        domain = normalize_domain(domain)
        path = self.dir / f"{domain}.json"
        if not path.exists():
            raise ReplayMiss(f"Hunter result for {domain} not cached")
        return {**json.loads(path.read_text()), "from_cache": True, "source": "cache"}

    def account(self) -> dict:
        return {"plan": "replay", "reset_date": None, "remaining": None}


def build_replay_context(settings: Settings, *, live_hunter: bool = False, out=None) -> Context:
    hunter = ReplayHunter(settings.cache_dir / "hunter") if live_hunter else FixtureHunter()
    return Context(
        settings=settings,
        llm=LLMClient("replay-no-key", settings.cache_dir / "llm", client=_NoGenai()),
        hunter=hunter,
        fetcher=PageFetcher(
            settings.cache_dir / "pages", http=httpx.Client(transport=httpx.MockTransport(_no_http))
        ),
        store=RunStore(settings.out_dir),
        dry_run=True,
        sender=None,
        out=out,
    )
