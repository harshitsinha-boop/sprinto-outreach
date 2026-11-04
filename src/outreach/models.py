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
    score_expected: float | None = None  # score_min + unknown_credit x (score_max - score_min)


class ToolSpec(BaseModel):
    """One function the agent loop may call. `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict


class ToolCall(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Code-generated answer to one ToolCall. Never carries page text."""

    name: str
    response: dict


class ToolReply(BaseModel):
    calls: list[ToolCall] = Field(default_factory=list)
    text: str | None = None
    from_cache: bool = False


class Candidate(BaseModel):
    """A same-domain URL the loop may fetch, with the unknown signals it could resolve."""

    url: str
    kind: str
    signals: list[str] = Field(default_factory=list)


StopReason = Literal[
    "not_needed",
    "disabled",
    "sufficient_data",
    "max_iters",
    "no_missing_fields",
    "no_candidates",
    "no_progress",
    "tool_errors",
    "model_done",
]


class AgentStep(BaseModel):
    """One logged model turn: what it asked for, why, what happened and the new interval."""

    iteration: int
    tool: str
    url: str | None = None
    reason: str | None = None
    outcome: Literal["fetched", "unavailable", "error", "refused"]
    refusal: str | None = None
    page_kind: str | None = None
    page_status: str | None = None
    resolved_signals: list[str] = Field(default_factory=list)
    score_min: int
    score_max: int


class AgentRun(BaseModel):
    """The research record every Qualification carries, whether or not the loop ran."""

    stop_reason: StopReason
    iterations: int = 0
    fetches: int = 0
    llm_turns: int = 0
    steps: list[AgentStep] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    error: str | None = None


class ResearchOutcome(BaseModel):
    profile: CompanyProfile
    pages: list[PageResult]
    agent: AgentRun


class Qualification(BaseModel):
    """The stored verdict: stage output of `qualify` (or `result` inside a stopped stage)."""

    verdict: Literal["qualified", "disqualified", "insufficient_data"]
    initial_verdict: Literal["qualified", "disqualified", "loop"]
    reason: str
    rubric_version: str
    rubric_sha256: str
    thresholds: dict[str, int | float]
    initial_score: RubricScore
    score: RubricScore
    decided_with_unknowns: list[str] = Field(default_factory=list)
    kinds_usable: list[str] = Field(default_factory=list)
    profile: CompanyProfile
    research: AgentRun | None = None


class HunterContact(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str
    position: str
    confidence: int | None = None
    source: Literal["live", "cache", "fixture"]


class PocCandidate(BaseModel):
    """One ranked Hunter person. `score` is deterministic; `eligible` False means excluded."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    position: str | None = None
    category: str | None = None
    score: float = 0.0
    eligible: bool = True
    notes: list[str] = Field(default_factory=list)


class PocOutput(BaseModel):
    """The chosen contact plus the deterministic reasoning that picked them."""

    contact: HunterContact
    band: Literal["small", "mid", "large"]
    band_basis: str
    reason: str
    top_candidates: list[PocCandidate]
    candidates_seen: int
    risks: list[str] = Field(default_factory=list)


class EmailDraft(BaseModel):
    subject: str
    body: str


class EvidenceItem(BaseModel):
    """One citable fact from the validated CompanyProfile, with a stable id (E1, E2, ...)."""

    id: str
    kind: str
    fact: str
    quote: str
    source_url: str


class PainPoint(BaseModel):
    pain: str
    role_link: str
    evidence_id: str


class PainPointSet(BaseModel):
    pain_points: list[PainPoint]


class ClaimUsed(BaseModel):
    """A statement in the email and the id it rests on: an evidence id (E1..) or a whitelisted
    Sprinto claim id (S1, S2)."""

    claim: str
    evidence_id: str


class DraftLLM(BaseModel):
    subject: str
    body: str
    claims_used: list[ClaimUsed]


class HookLink(BaseModel):
    claim: str
    evidence_id: str
    quote: str
    source_url: str


class DraftValidation(BaseModel):
    ok: bool
    failures: list[str] = Field(default_factory=list)
    attempts: int = 1
    attempt_failures: list[list[str]] = Field(default_factory=list)


class DraftOutput(BaseModel):
    draft: EmailDraft  # subject and the final body, compliance footer included
    greets_by_first_name: bool
    core_body: str = ""  # the validated 50-90 word body, before the footer
    claims_used: list[ClaimUsed] = Field(default_factory=list)
    pain_points: list[PainPoint] = Field(default_factory=list)
    pain_points_source: str = ""
    hook_map: list[HookLink] = Field(default_factory=list)
    evidence_pack: list[EvidenceItem] = Field(default_factory=list)
    validation: DraftValidation | None = None


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
