"""The six skeleton stages. Every external call goes through `ctx`; stages never import
an SDK. Each stage is `(ctx, domain, prev) -> BaseModel` and `prev` holds the typed
outputs of the earlier stages.

No prompt may contain a timestamp, run id or random value: it would change the LLM
cache key and break "second run makes no new Gemini calls".
"""

from __future__ import annotations

import functools
import hashlib
from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel

from outreach.agent import run_research
from outreach.extract import extract_profile
from outreach.models import (
    CompanyProfile,
    DraftOutput,
    EmailDraft,
    ExtractOutput,
    HunterContact,
    PageResult,
    Qualification,
    ResearchOutcome,
    RubricScore,
    ScrapeOutput,
    SendResult,
)
from outreach.pagegate import is_usable, page_gate
from outreach.qualify import qualify
from outreach.scrape import scrape_domain
from outreach.send import send_email

if TYPE_CHECKING:  # avoid an import cycle with skeleton.py
    from outreach.skeleton import Context


class StopStage(Exception):
    """An expected, logged stop (not a failure): the run ends with status `stopped`."""

    def __init__(self, reason: str, detail: str = "", output: BaseModel | None = None):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.output = output  # a typed record stored with the stopped stage (e.g. Qualification)


class DomainUnreachable(Exception):
    """Every fetch for the domain failed at transport level (dead DNS, timeout, 5xx). A plain
    failure, never a StopStage: the batch records the domain as `failed` and carries on."""


DRAFT_PROMPT_VERSION = "draft.1"

DRAFT_SYSTEM = (
    "You write one short cold email in plain text.\n"
    "Under 90 words. Greet the recipient by the given first name. Include one specific "
    "hook drawn only from the supplied evidence. End with one small question as the ask. "
    "Do not include any URLs. Do not invent facts that are not in the evidence."
)


def usable_pages(pages: list[PageResult]) -> list[PageResult]:
    """The single usability filter, applied at the extract call site for any fetcher: status ok,
    at least MIN_PAGE_CHARS of text and no block or challenge signature (`pagegate.is_usable`)."""
    return [p for p in pages if is_usable(p)]


def _evidence_block(profile: CompanyProfile, limit: int = 3) -> str:
    items = (
        list(profile.compliance_mentions)
        + list(profile.enterprise_customers)
        + list(profile.hiring_signals)
    )[:limit]
    return "\n".join(f'- "{i.quote}" ({i.source_url})' for i in items) or "- (none)"


def build_draft_prompt(profile: CompanyProfile, contact: HunterContact) -> str:
    company = profile.name.value if profile.name is not None else "unknown"
    return (
        f"Recipient first name: {contact.first_name}\n"
        f"Recipient position: {contact.position}\n"
        f"Company: {company}\n"
        "<evidence>\n"
        f"{_evidence_block(profile)}\n"
        "</evidence>\n\n"
        "Write the email. Return a subject and a body."
    )


def pick_contact(result: dict) -> HunterContact | None:
    emails = ((result.get("response") or {}).get("data") or {}).get("emails") or []
    named = [e for e in emails if e.get("first_name") and e.get("position")]
    if not named:
        return None
    named.sort(key=lambda e: e.get("confidence") or 0, reverse=True)
    best = named[0]
    return HunterContact(
        first_name=best["first_name"],
        last_name=best.get("last_name"),
        email=best["value"],
        position=best["position"],
        confidence=best.get("confidence"),
        source=result["source"],
    )


def _page_reason(page: PageResult) -> str:
    return page.reason or page_gate(page.text) or page.status


def stage_scrape(ctx: Context, domain: str, prev: dict) -> ScrapeOutput:
    out = scrape_domain(ctx.fetcher, domain)
    if out.usable == 0:
        if out.pages and all(p.status == "error" for p in out.pages):
            raise DomainUnreachable(f"all {len(out.pages)} fetches failed: {out.pages[0].error}")
        counts = Counter(_page_reason(p) for p in out.pages)
        breakdown = ", ".join(f"{reason}={n}" for reason, n in sorted(counts.items()))
        raise StopStage("insufficient_data", f"0 usable of {len(out.pages)} pages ({breakdown})")
    return out


def stage_extract(ctx: Context, domain: str, prev: dict) -> ExtractOutput:
    return extract_profile(ctx.llm, ctx.settings.gemini_model_fast, usable_pages(prev["scrape"].pages))


def _research(
    ctx: Context,
    domain: str,
    profile: CompanyProfile,
    pages: list[PageResult],
    score: RubricScore,
) -> ResearchOutcome:
    """The bounded research loop, bound to this run's LLM, fetcher, domain and models."""
    return run_research(
        ctx.llm,
        ctx.fetcher,
        domain=domain,
        smart_model=ctx.settings.gemini_model_smart,
        fast_model=ctx.settings.gemini_model_fast,
        profile=profile,
        pages=pages,
        loaded=ctx.rubric,
        score=score,
    )


def stage_qualify(ctx: Context, domain: str, prev: dict) -> Qualification:
    """Score the validated profile with the hashed rubric; a gray-band company gets the bounded
    research loop first. Anything but `qualified` stops the run here, so Hunter is never called
    for a rejected or undecided company."""
    q = qualify(
        prev["extract"].profile,
        prev["scrape"].pages,
        ctx.rubric,
        research=functools.partial(_research, ctx, domain),
    )
    if q.verdict != "qualified":
        raise StopStage(q.verdict, q.reason[:200], output=q)
    return q


def stage_hunter(ctx: Context, domain: str, prev: dict) -> HunterContact:
    contact = pick_contact(ctx.hunter.domain_search(domain))
    if contact is None:
        raise StopStage("no_contact", "Hunter returned no person with a name and position")
    return contact


def stage_draft(ctx: Context, domain: str, prev: dict) -> DraftOutput:
    contact: HunterContact = prev["hunter"]
    draft = ctx.llm.generate_structured(
        model=ctx.settings.gemini_model_smart,
        system=DRAFT_SYSTEM,
        prompt=build_draft_prompt(prev["qualify"].profile, contact),
        schema=EmailDraft,
        purpose="draft",
        thinking_level="LOW",
        prompt_version=DRAFT_PROMPT_VERSION,
    )
    return DraftOutput(draft=draft, greets_by_first_name=contact.first_name in draft.body)


def stage_send(ctx: Context, domain: str, prev: dict) -> SendResult:
    draft: EmailDraft = prev["draft"].draft
    digest = hashlib.sha256((draft.subject + draft.body).encode()).hexdigest()[:16]
    return send_email(
        ctx.settings,
        draft.subject,
        draft.body,
        dry_run=ctx.dry_run,
        intended=prev["hunter"],
        idempotency_key=f"outreach-{domain}-{digest}",
        sender=ctx.sender,
        out=ctx.out,
    )


STAGES = [
    ("scrape", stage_scrape),
    ("extract", stage_extract),
    ("qualify", stage_qualify),
    ("hunter", stage_hunter),
    ("draft", stage_draft),
    ("send", stage_send),
]
