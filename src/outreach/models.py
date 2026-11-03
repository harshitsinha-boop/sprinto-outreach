"""Pydantic contracts shared by every stage, the run record and the LLM schemas.

Fields the LLM fills have NO defaults on purpose: the generated JSON schema then
marks them required, so the model must state null or [] explicitly ("unknown stays
unknown"). Never name a field `default`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    quote: str
    source_url: str


class PageResult(BaseModel):
    url: str
    status: Literal["ok", "unavailable", "error"]
    text: str | None = None
    chars: int = 0
    error: str | None = None
    from_cache: bool = False


class ScrapeOutput(BaseModel):
    pages: list[PageResult]
    usable: int


class CompanyProfileLite(BaseModel):
    name: str | None
    is_b2b_saas: bool | None
    headcount_band: str | None
    compliance_mentions: list[Evidence]
    hiring_signals: list[Evidence]
    enterprise_customer_signals: list[Evidence]


class ExtractOutput(BaseModel):
    profile: CompanyProfileLite
    quotes_total: int
    quotes_found_in_text: int


class ScoreItem(BaseModel):
    signal: str
    weight: int
    present: bool | None
    points: int


class ScoreBreakdown(BaseModel):
    items: list[ScoreItem]
    total: int
    threshold: int
    gate_applied: bool = False


class HunterContact(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str
    position: str
    confidence: int | None = None
    source: Literal["live", "cache", "fixture"]


class EmailDraft(BaseModel):
    subject: str
    body: str


class DraftOutput(BaseModel):
    draft: EmailDraft
    greets_by_first_name: bool


class SendResult(BaseModel):
    mode: Literal["dry_run", "sent"]
    payload: dict
    id: str | None = None


class StageRecord(BaseModel):
    name: str
    status: Literal["ok", "stopped", "failed"]
    started_at: str
    finished_at: str | None = None
    output: dict | None = None
    error: str | None = None


class RunRecord(BaseModel):
    domain: str
    status: Literal["running", "dry_run", "sent", "stopped", "failed"]
    started_at: str
    finished_at: str | None = None
    failed_stage: str | None = None
    stop_reason: str | None = None
    stages: list[StageRecord] = Field(default_factory=list)
    models: dict[str, str] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)


# ---- batch runner contracts (Phase 2): the closed outcome vocabulary ----

OUTCOMES = (
    "qualified",
    "disqualified",
    "insufficient_data",
    "no_contact",
    "rejected_draft",
    "sent",
    "failed",
)

Outcome = Literal[
    "qualified",
    "disqualified",
    "insufficient_data",
    "no_contact",
    "rejected_draft",
    "sent",
    "failed",
]


class BatchRow(BaseModel):
    domain: str
    outcome: Outcome
    detail: str = ""
    run_record: str | None = None


class BatchSummary(BaseModel):
    mode: Literal["dry_run", "send"]
    hunter: str
    started_at: str
    finished_at: str | None = None
    rows: list[BatchRow] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    aborted: bool = False
    abort_reason: str | None = None
