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


class Link(BaseModel):
    url: str
    text: str = ""


class PageResult(BaseModel):
    url: str
    status: Literal["ok", "unavailable", "error"]
    text: str | None = None
    chars: int = 0
    error: str | None = None
    from_cache: bool = False
    kind: str | None = None
    reason: str | None = None
    final_url: str | None = None
    links: list[Link] = Field(default_factory=list)


class ScrapeOutput(BaseModel):
    pages: list[PageResult]
    usable: int
    kinds_found: list[str] = Field(default_factory=list)
    fetches: int = 0
    skipped_kinds: list[str] = Field(default_factory=list)


class EvidencedText(BaseModel):
    value: str
    quote: str
    source_url: str


class EvidencedBool(BaseModel):
    value: bool
    quote: str
    source_url: str


class StageFact(BaseModel):
    value: Literal[
        "pre_seed",
        "seed",
        "series_a",
        "series_b",
        "series_c",
        "series_d_or_later",
        "public",
        "bootstrapped",
    ]
    as_of: str | None
    quote: str
    source_url: str


class HeadcountFact(BaseModel):
    value: Literal["1-10", "11-50", "51-200", "201-500", "501-1000", "1001+"]
    quote: str
    source_url: str


class ComplianceMention(BaseModel):
    framework: str
    status: Literal["certified", "in_progress", "planned", "mentioned"]
    as_of: str | None
    quote: str
    source_url: str


class HiringSignal(BaseModel):
    role: str
    quote: str
    source_url: str


class EnterpriseCustomer(BaseModel):
    name: str
    quote: str
    source_url: str


class CompanyProfile(BaseModel):
    """What the pages state about a company, each value with its own quote and page url.

    No defaults: every field is required in the schema, so the model must say null or [].
    `is_b2b` is tri-state by construction (true, false, or null when unknown)."""

    name: EvidencedText | None
    offering: EvidencedText | None
    is_b2b: EvidencedBool | None
    stage: StageFact | None
    headcount: HeadcountFact | None
    compliance_mentions: list[ComplianceMention]
    hiring_signals: list[HiringSignal]
    enterprise_customers: list[EnterpriseCustomer]


class DroppedEvidence(BaseModel):
    field: str
    quote: str
    source_url: str
    reason: str


class ExtractOutput(BaseModel):
    profile: CompanyProfile
    pages_used: list[str]
    evidence_total: int
    evidence_kept: int
    evidence_dropped: list[DroppedEvidence] = Field(default_factory=list)
    injection_suspected_pages: list[str] = Field(default_factory=list)


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


class SignalScore(BaseModel):
    """One rubric signal scored from validated evidence. `known` means points_min equals
    points_max; `unknown` means 0 in the minimum and the full weight in the maximum."""

    id: str
    label: str
    group: str
    weight: int
    status: Literal["known", "unknown"]
    points_min: int
    points_max: int
    basis: str
    evidence: list[Evidence] = Field(default_factory=list)


class GateResult(BaseModel):
    id: str
    label: str
    status: Literal["pass", "fail", "unknown"]
    basis: str
    evidence: list[Evidence] = Field(default_factory=list)


class PenaltyHit(BaseModel):
    id: str
    label: str
    points: int
    evidence: list[Evidence] = Field(default_factory=list)


class RubricScore(BaseModel):
    signals: list[SignalScore]
    gates: list[GateResult]
    penalties: list[PenaltyHit]
    score_min: int
    score_max: int
    unknown_signals: list[str]


class Qualification(BaseModel):
    """The stored verdict: stage output of `qualify` (or `result` inside a stopped stage)."""

    verdict: Literal["qualified", "disqualified", "insufficient_data"]
    initial_verdict: Literal["qualified", "disqualified", "loop"]
    reason: str
    rubric_version: str
    rubric_sha256: str
    thresholds: dict[str, int]
    initial_score: RubricScore
    score: RubricScore
    decided_with_unknowns: list[str] = Field(default_factory=list)
    kinds_usable: list[str] = Field(default_factory=list)
    profile: CompanyProfile


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
    rubric: dict[str, str] = Field(default_factory=dict)


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
    rubric: dict[str, str] = Field(default_factory=dict)
