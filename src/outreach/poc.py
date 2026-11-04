"""Deterministic PoC (point of contact) selection from a Hunter Domain Search response.

Name and title come verbatim from Hunter, in code, never from an LLM. The ranking is a pure
function of (emails, company size band): title category rank by band x seniority bonus x
confidence or verification multiplier, with explicit tie-breakers, so the same response always
picks the same person. People with no ranked title are never picked ("naming a random person is
worse than skipping"), so a response with nobody suitable ends as `no_contact`.
"""

from __future__ import annotations

import re

from outreach.models import CompanyProfile, HunterContact, PocCandidate, PocOutput

# Title category -> regexes (matched on the lowercased position). First matching category wins,
# in this order, so "co-founder and cto" is cofounder_cto before ceo_founder.
CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("security_lead", (r"\bciso\b", r"chief (information )?security", r"(head|director|vp|vice president|lead) (of )?(information )?security",
                       r"security (director|head|lead)")),
    ("compliance", (r"\bgrc\b", r"compliance", r"\bgovernance\b")),
    ("cofounder_cto", (r"(co-?founder|technical founder).*\bcto\b", r"\bcto\b.*co-?founder", r"technical co-?founder")),
    ("cto", (r"\bcto\b", r"chief technology", r"chief technical")),
    ("eng_lead", (r"(vp|vice president|head|director) (of )?engineering", r"engineering (director|head|lead)", r"\bvp eng\b")),
    ("ceo_founder", (r"\bceo\b", r"chief executive", r"\bfounder\b", r"co-?founder", r"\bowner\b", r"\bpresident\b")),
    ("it_lead", (r"(head|director|vp|vice president|manager) (of )?(it|information technology)\b", r"\bit (manager|director|head)\b")),
    ("coo", (r"\bcoo\b", r"chief operating", r"(head|director|vp) (of )?operations")),
    ("sec_eng", (r"security (engineer|manager)", r"(senior|staff|principal) security")),
]

# Negative keywords: a title containing any of these is excluded outright.
NEGATIVE = (
    "sales", "marketing", "hr", "human resources", "recruit", "talent", "people", "customer success",
    "customer support", "support", "finance", "financial", "cfo", "intern", "advisor", "adviser",
    "board", "revenue", "growth", "business development", "partnership", "account executive",
    "brand", "content", "legal", "counsel", "design", "product marketing", "community",
)

# Category order per size band (best first). A real security lead outranks founders at any size.
BAND_ORDER: dict[str, list[str]] = {
    "small": ["security_lead", "cofounder_cto", "cto", "ceo_founder", "eng_lead", "coo", "it_lead", "compliance"],
    "mid": ["security_lead", "eng_lead", "it_lead", "compliance", "cofounder_cto", "cto", "coo", "ceo_founder"],
    "large": ["security_lead", "compliance", "it_lead", "eng_lead", "cto", "cofounder_cto", "sec_eng"],
}
HEADCOUNT_BAND = {
    "1-10": "small",
    "11-50": "small",
    "51-200": "mid",
    "201-500": "large",
    "501-1000": "large",
    "1001+": "large",
}


def size_band(profile: CompanyProfile | None) -> tuple[str, str]:
    """(band, basis). Unknown headcount falls back to the mid band, and says so."""
    hc = profile.headcount if profile is not None else None
    if hc is None:
        return "mid", "headcount unknown, defaulting to the mid band"
    return HEADCOUNT_BAND[hc.value], f"headcount {hc.value}"


def title_category(position: str) -> str | None:
    text = (position or "").lower()
    for category, patterns in CATEGORIES:
        if any(re.search(p, text) for p in patterns):
            return category
    return None


def _negative_hit(position: str) -> str | None:
    text = (position or "").lower()
    for word in NEGATIVE:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return word
    return None


def _confidence_multiplier(entry: dict, notes: list[str]) -> float:
    status = ((entry.get("verification") or {}).get("status") or "").lower()
    confidence = entry.get("confidence") or 0
    if status == "valid":
        notes.append("verified valid")
        return 1.0
    if status == "accept_all" and confidence >= 80:
        notes.append("accept_all, confidence >= 80")
        return 0.9
    if confidence >= 80 and status not in ("invalid", "unknown"):
        notes.append("confidence >= 80")
        return 0.9
    notes.append("low confidence or unverified (risk)")
    return 0.5


def score_candidate(entry: dict, band: str) -> PocCandidate:
    cand = PocCandidate(
        first_name=entry.get("first_name"),
        last_name=entry.get("last_name"),
        email=entry.get("value"),
        position=entry.get("position"),
    )
    if not (cand.first_name and cand.position and cand.email):
        cand.eligible = False
        cand.notes.append("missing name, position or address")
        return cand
    hit = _negative_hit(cand.position)
    if hit is not None:
        cand.eligible = False
        cand.notes.append(f"excluded title keyword: {hit}")
        return cand
    category = title_category(cand.position)
    cand.category = category
    order = BAND_ORDER[band]
    if category is None or category not in order:
        cand.eligible = False
        cand.notes.append("title not on the ranked list for this size band")
        return cand
    rank_score = (len(order) - order.index(category)) * 10
    seniority = (entry.get("seniority") or "").lower()
    bonus = 1.1 if seniority == "executive" else 1.0
    cand.notes.append(f"{category} rank {order.index(category) + 1} of {len(order)} for the {band} band")
    cand.score = round(rank_score * bonus * _confidence_multiplier(entry, cand.notes), 2)
    return cand


def _tiebreak(entry: dict) -> tuple:
    return (
        bool(entry.get("decision_maker")),
        (entry.get("seniority") or "").lower() == "executive",
        bool(entry.get("linkedin")),
        entry.get("confidence") or 0,
    )


def select_contact(result: dict, profile: CompanyProfile | None) -> PocOutput | None:
    """The chosen PoC with its logged reasoning, or None when nobody suitable was returned."""
    emails = ((result.get("response") or {}).get("data") or {}).get("emails") or []
    band, basis = size_band(profile)
    scored = [(score_candidate(e, band), e) for e in emails if isinstance(e, dict)]
    eligible = [(c, e) for c, e in scored if c.eligible]
    if not eligible:
        return None
    eligible.sort(key=lambda ce: (ce[0].score, _tiebreak(ce[1]), ce[0].email or ""), reverse=True)
    winner, entry = eligible[0]
    top = [c for c, _ in eligible[:3]]
    risks = [n for n in winner.notes if "risk" in n]
    reason = (
        f"{winner.first_name} {winner.last_name or ''}".strip()
        + f", {winner.position}: top title match for the {band} band ({basis}), score {winner.score}"
    )
    if len(eligible) > 1:
        runner = eligible[1][0]
        gap = "higher title rank" if winner.score != runner.score else "tie-breakers (decision maker, executive, linkedin, confidence)"
        reason += f"; ahead of {runner.first_name} ({runner.position}, {runner.score}) on {gap}"
    contact = HunterContact(
        first_name=entry["first_name"],
        last_name=entry.get("last_name"),
        email=entry["value"],
        position=entry["position"],
        confidence=entry.get("confidence"),
        source=result["source"],
    )
    return PocOutput(
        contact=contact,
        band=band,
        band_basis=basis,
        reason=reason,
        top_candidates=top,
        candidates_seen=len(scored),
        risks=risks,
    )
