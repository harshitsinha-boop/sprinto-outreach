"""ICP qualification: the rubric as data, and a pure interval scorer over validated evidence.

The rubric lives in `config/icp.toml`. `load_rubric` reads the file bytes once, hashes exactly
those bytes (sha256) and validates the parsed result, so a malformed or edited rubric is refused
or at least visible in every run record. The LLM never produces a number: points come only from
these Python rules applied to the `CompanyProfile` that Phase 2's validator already checked
(every kept value's quote is on the page it cites).

Every signal is known (points from evidence) or unknown. `score_min` counts unknown signals as
0 and `score_max` counts them at full weight, penalties lowering both. The module is pure: no
clock, no randomness, no I/O besides reading the rubric file, and it never imports an SDK.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from outreach.models import (
    CompanyProfile,
    Evidence,
    GateResult,
    PageResult,
    PenaltyHit,
    Qualification,
    RubricScore,
    SignalScore,
)
from outreach.pagegate import is_usable
from outreach.scrape import PAGE_KINDS

DEFAULT_RUBRIC_PATH = Path(__file__).resolve().parents[2] / "config" / "icp.toml"


class RubricError(Exception):
    """The rubric file cannot be used as written; the message names the problem."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Thresholds(_Strict):
    qualify_min: int
    reject_max: int
    reference_year: int


class GateRule(_Strict):
    id: str
    label: str
    field: str
    fail_values: list[Any]


class KeywordGroup(_Strict):
    points: int
    keywords: list[str]


class SignalRule(_Strict):
    id: str
    label: str
    group: str
    weight: int
    kind: Literal["map", "best", "count", "keyword", "year_recency", "text_keyword"]
    field: str
    attribute: str | None = None
    points: dict[str, int] = Field(default_factory=dict)
    tiers: list[list[int]] = Field(default_factory=list)
    keyword_groups: list[KeywordGroup] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    observed_on: list[str] = Field(default_factory=list)
    target_kinds: list[str] = Field(default_factory=list)


class PenaltyRule(_Strict):
    id: str
    label: str
    points: int
    requires: list[str]
    excludes: list[str] = Field(default_factory=list)


class Rubric(_Strict):
    version: str
    description: str = ""
    thresholds: Thresholds
    gates: list[GateRule]
    signals: list[SignalRule]
    penalties: list[PenaltyRule] = Field(default_factory=list)


class LoadedRubric(BaseModel):
    rubric: Rubric
    sha256: str
    path: Path


_YEAR_KEYS = ("age_le_1", "age_2", "older")


def _max_points(rule: SignalRule) -> int:
    if rule.kind in ("map", "best", "year_recency", "text_keyword"):
        return max(rule.points.values(), default=0)
    if rule.kind == "count":
        return max((t[1] for t in rule.tiers if len(t) == 2), default=0)
    return max((g.points for g in rule.keyword_groups), default=0)


def _check_signal(rule: SignalRule) -> None:
    """Raise RubricError when a signal lacks the keys its kind needs."""
    missing: str | None = None
    if rule.kind == "map" and not rule.points:
        missing = "points"
    elif rule.kind == "best" and not (rule.points and rule.attribute):
        missing = "points and attribute"
    elif rule.kind == "count" and (not rule.tiers or any(len(t) != 2 for t in rule.tiers)):
        missing = "tiers of [minimum count, points]"
    elif rule.kind == "keyword" and not (rule.keyword_groups and rule.attribute):
        missing = "keyword_groups and attribute"
    elif rule.kind == "year_recency" and any(k not in rule.points for k in _YEAR_KEYS):
        missing = "points with keys " + ", ".join(_YEAR_KEYS)
    elif rule.kind == "text_keyword" and not (rule.keywords and "match" in rule.points):
        missing = "keywords and points.match"
    if missing:
        raise RubricError(f"signal {rule.id} (kind {rule.kind}) needs {missing}")


def _validate(rubric: Rubric) -> None:
    profile_fields = set(CompanyProfile.model_fields)
    ids = [s.id for s in rubric.signals]
    if len(set(ids)) != len(ids):
        raise RubricError("signal ids must be unique")
    gate_ids = [g.id for g in rubric.gates]
    if len(set(gate_ids)) != len(gate_ids):
        raise RubricError("gate ids must be unique")
    penalty_ids = [p.id for p in rubric.penalties]
    if len(set(penalty_ids)) != len(penalty_ids):
        raise RubricError("penalty ids must be unique")
    total = sum(s.weight for s in rubric.signals)
    if total != 100:
        raise RubricError(f"signal weights must sum to 100, got {total}")
    if rubric.thresholds.qualify_min <= rubric.thresholds.reject_max:
        raise RubricError(
            f"qualify_min {rubric.thresholds.qualify_min} must be above "
            f"reject_max {rubric.thresholds.reject_max}"
        )
    for gate in rubric.gates:
        if gate.field not in profile_fields:
            raise RubricError(f"gate {gate.id} reads unknown profile field {gate.field}")
    for rule in rubric.signals:
        if rule.field not in profile_fields:
            raise RubricError(f"signal {rule.id} reads unknown profile field {rule.field}")
        _check_signal(rule)
        if _max_points(rule) != rule.weight:
            raise RubricError(
                f"signal {rule.id}: maximum attainable points {_max_points(rule)} "
                f"differ from weight {rule.weight}"
            )
        for label, kinds in (("observed_on", rule.observed_on), ("target_kinds", rule.target_kinds)):
            for kind in kinds:
                if kind not in PAGE_KINDS:
                    raise RubricError(f"signal {rule.id}: {label} kind {kind!r} is not a page kind")


def load_rubric(path: Path | str = DEFAULT_RUBRIC_PATH) -> LoadedRubric:
    """Read the rubric file once, hash those exact bytes and validate the parsed content."""
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
        rubric = Rubric.model_validate(data)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise RubricError(f"{path.name}: invalid TOML: {exc}") from exc
    except ValidationError as exc:
        raise RubricError(f"{path.name}: invalid rubric schema: {exc}") from exc
    _validate(rubric)
    return LoadedRubric(rubric=rubric, sha256=sha, path=path)


def usable_kinds(pages: list[PageResult]) -> set[str]:
    """The page kind of every page that passes the single usability gate."""
    return {p.kind for p in pages if p.kind and is_usable(p)}


# ---- matching helpers ----


@lru_cache(maxsize=512)
def _word_re(keyword: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])")


def _has_word(text: str, keyword: str) -> bool:
    return _word_re(keyword).search(text.lower()) is not None


_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def _evidence(items: list[Any]) -> list[Evidence]:
    pairs = sorted({(i.quote, i.source_url) for i in items})
    return [Evidence(quote=q, source_url=u) for q, u in pairs]


def _known(rule: SignalRule, points: int, basis: str, evidence: list[Evidence]) -> SignalScore:
    return SignalScore(
        id=rule.id,
        label=rule.label,
        group=rule.group,
        weight=rule.weight,
        status="known",
        points_min=points,
        points_max=points,
        basis=basis,
        evidence=evidence,
    )


def _unknown(rule: SignalRule, basis: str) -> SignalScore:
    return SignalScore(
        id=rule.id,
        label=rule.label,
        group=rule.group,
        weight=rule.weight,
        status="unknown",
        points_min=0,
        points_max=rule.weight,
        basis=basis,
        evidence=[],
    )


def _key(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _score_signal(rule: SignalRule, profile: CompanyProfile, kinds: set[str]) -> SignalScore:
    obj = getattr(profile, rule.field)

    if rule.kind in ("map", "text_keyword"):
        if obj is None:
            return _unknown(rule, f"unknown: {rule.field} not stated")
        evidence = _evidence([obj])
        if rule.kind == "map":
            key = _key(obj.value)
            return _known(rule, rule.points.get(key, 0), f"{rule.field}={key}", evidence)
        if rule.kind == "text_keyword":
            matched = [k for k in rule.keywords if _has_word(str(obj.value), k)]
            points = rule.points["match"] if matched else 0
            basis = f"matches {sorted(matched)[0]}" if matched else "no vertical keyword"
            return _known(rule, points, basis, evidence)

    items: list[Any] = list(obj)
    if not items:
        read = [k for k in rule.observed_on if k in kinds]
        names = " or ".join(rule.observed_on)
        if read:
            return _known(rule, 0, f"no item; {read[0]} page read", [])
        return _unknown(rule, f"unknown: no {names} page read")

    if rule.kind == "best":
        attr = rule.attribute or ""
        best = max(rule.points.get(getattr(i, attr), 0) for i in items)
        tied = sorted(
            (i for i in items if rule.points.get(getattr(i, attr), 0) == best),
            key=lambda i: (i.quote, i.source_url),
        )
        top = tied[0]
        return _known(rule, best, f"{attr}={getattr(top, attr)}", _evidence([top]))

    if rule.kind == "count":
        n = len(items)
        points = next((pts for minimum, pts in rule.tiers if minimum <= n), 0)
        return _known(rule, points, f"{n} customer{'s' if n != 1 else ''}", _evidence(items))

    attr = rule.attribute or ""  # keyword
    best = 0
    matching: list[Any] = []
    for item in items:
        text = str(getattr(item, attr))
        for group in rule.keyword_groups:
            if any(_has_word(text, k) for k in group.keywords):
                best = max(best, group.points)
                matching.append(item)
                break
    basis = f"{len(matching)} matching role{'s' if len(matching) != 1 else ''}"
    if not matching:
        basis = f"{len(items)} role{'s' if len(items) != 1 else ''}, none match"
    return _known(rule, best, basis, _evidence(matching))


def _score_recency(
    rule: SignalRule, year: int, evidence: list[Evidence], reference_year: int
) -> SignalScore:
    age = max(0, reference_year - year)
    key = "age_le_1" if age <= 1 else "age_2" if age == 2 else "older"
    return _known(rule, rule.points[key], f"funding year {year}, age {age}", evidence)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower()).replace("type2", "typeii")


def _gate(rule: GateRule, profile: CompanyProfile) -> GateResult:
    obj = getattr(profile, rule.field)
    if obj is None:
        return GateResult(
            id=rule.id, label=rule.label, status="unknown", basis=f"{rule.field} not stated"
        )
    value = obj.value
    failed = any(value == fv and type(value) is type(fv) for fv in rule.fail_values)
    return GateResult(
        id=rule.id,
        label=rule.label,
        status="fail" if failed else "pass",
        basis=f"{rule.field}={_key(value)}",
        evidence=_evidence([obj]),
    )


def _penalties(rubric: Rubric, profile: CompanyProfile) -> list[PenaltyHit]:
    certified = [m for m in profile.compliance_mentions if m.status == "certified"]
    normalised = [(_normalise(f"{m.framework} {m.quote}"), m) for m in certified]
    hits: list[PenaltyHit] = []
    for rule in rubric.penalties:
        if not all(any(tok in text for text, _ in normalised) for tok in rule.requires):
            continue
        if any(tok in text for tok in rule.excludes for text, _ in normalised):
            continue
        cited = [m for text, m in normalised if any(tok in text for tok in rule.requires)]
        hits.append(
            PenaltyHit(id=rule.id, label=rule.label, points=rule.points, evidence=_evidence(cited))
        )
    return hits


def score_profile(
    profile: CompanyProfile, kinds_usable: set[str], rubric: Rubric
) -> RubricScore:
    """Pure and deterministic: the same evidence, in any list order, gives the same score."""
    signals: list[SignalScore] = []
    for rule in rubric.signals:
        if rule.kind == "year_recency":
            signals.append(_score_year(rule, profile, rubric.thresholds.reference_year))
        else:
            signals.append(_score_signal(rule, profile, kinds_usable))
    gates = [_gate(g, profile) for g in rubric.gates]
    penalties = _penalties(rubric, profile)
    cut = sum(p.points for p in penalties)
    score_min = max(0, sum(s.points_min for s in signals) - cut)
    score_max = max(0, sum(s.points_max for s in signals) - cut)
    unknown = sorted((s for s in signals if s.status == "unknown"), key=lambda s: (-s.weight, s.id))
    return RubricScore(
        signals=signals,
        gates=gates,
        penalties=penalties,
        score_min=score_min,
        score_max=score_max,
        unknown_signals=[s.id for s in unknown],
    )


def _score_year(rule: SignalRule, profile: CompanyProfile, reference_year: int) -> SignalScore:
    obj = getattr(profile, rule.field)
    if obj is None:
        return _unknown(rule, f"unknown: {rule.field} not stated")
    as_of = getattr(obj, "as_of", None)
    if as_of is None:
        return _unknown(rule, "unknown: funding date not stated")
    found = _YEAR.search(as_of)
    if found is None:
        return _unknown(rule, "unknown: no year in funding date")
    return _score_recency(rule, int(found.group(0)), _evidence([obj]), reference_year)


# ---- verdicts ----


def _failed_gate(score: RubricScore) -> GateResult | None:
    return next((g for g in score.gates if g.status == "fail"), None)


def initial_verdict(
    score: RubricScore, rubric: Rubric
) -> Literal["qualified", "disqualified", "loop"]:
    t = rubric.thresholds
    if _failed_gate(score) is not None:
        return "disqualified"
    if score.score_min >= t.qualify_min:
        return "qualified"
    if score.score_max < t.reject_max:
        return "disqualified"
    return "loop"


def final_verdict(score: RubricScore, rubric: Rubric) -> tuple[str, str]:
    t = rubric.thresholds
    failed = _failed_gate(score)
    if failed is not None:
        return "disqualified", f"gate {failed.id} failed: {failed.basis}"
    if score.score_min >= t.qualify_min:
        return "qualified", f"score_min {score.score_min} >= qualify_min {t.qualify_min}"
    if score.score_max < t.reject_max:
        return "disqualified", f"score_max {score.score_max} < reject_max {t.reject_max}"
    if not score.unknown_signals:
        return (
            "disqualified",
            f"score {score.score_min} known on every signal is below qualify_min {t.qualify_min}",
        )
    return (
        "insufficient_data",
        f"score {score.score_min}..{score.score_max} straddles reject_max {t.reject_max} "
        f"and qualify_min {t.qualify_min}; unknown: {', '.join(score.unknown_signals)}",
    )


def qualify(
    profile: CompanyProfile, pages: list[PageResult], loaded: LoadedRubric
) -> Qualification:
    """Score the validated profile against the rubric and record the verdict."""
    rubric = loaded.rubric
    kinds = usable_kinds(pages)
    score = score_profile(profile, kinds, rubric)
    initial = initial_verdict(score, rubric)
    verdict, reason = final_verdict(score, rubric)
    t = rubric.thresholds
    return Qualification(
        verdict=verdict,  # type: ignore[arg-type]
        initial_verdict=initial,
        reason=reason,
        rubric_version=rubric.version,
        rubric_sha256=loaded.sha256,
        thresholds={
            "qualify_min": t.qualify_min,
            "reject_max": t.reject_max,
            "reference_year": t.reference_year,
        },
        initial_score=score,
        score=score,
        decided_with_unknowns=[] if verdict == "qualified" else list(score.unknown_signals),
        kinds_usable=sorted(kinds),
        profile=profile,
    )
