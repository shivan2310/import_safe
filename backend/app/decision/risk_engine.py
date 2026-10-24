"""Risk engine: outcome, risk level and score (PRD B10).

Precedence: docs/decisions.md section 2. Score and weights: section 3, values in
risk_weights.yaml (via risk_config). Interpretations: section 8. Pure apart from
loading the default config when none is passed in.
"""
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

from app.decision.classifier import Classification
from app.decision.cost_engine import CostEstimate
from app.decision.enums import CheckStatus, ClassificationStatus, IdentityResult, Outcome, RiskLevel
from app.decision.risk_config import RiskConfig, load_risk_config
from app.decision.rules.rule_engine import RequirementCheck

RESALE_PURPOSE = "resale"

_OPEN_STATUSES = (CheckStatus.potentially_applicable, CheckStatus.unverified)


class RiskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    risk_level: RiskLevel
    score: int
    reasons: List[str]
    next_actions: List[str]
    evidence_ids: List[str]
    rule_versions: List[str]


def _level_for(score: int, config: RiskConfig) -> RiskLevel:
    ranges = ((RiskLevel.low, config.ranges.low), (RiskLevel.medium, config.ranges.medium),
              (RiskLevel.high, config.ranges.high))
    for level, rng in ranges:
        if score >= rng.min and (rng.max is None or score <= rng.max):
            return level
    return RiskLevel.high


def _label(check: RequirementCheck) -> str:
    return f"{check.area} (rule {check.rule_id} v{check.rule_version})"


def compute_risk(
    checks: Sequence[RequirementCheck],
    identity_result: Optional[IdentityResult],
    classification: Optional[Classification],
    quantity: Optional[int],
    purpose: Optional[str],
    cost_estimate: Optional[CostEstimate],
    config: Optional[RiskConfig] = None,
) -> RiskResult:
    cfg = config if config is not None else load_risk_config()
    mandatory = [c for c in checks if c.mandatory]

    score = 0
    scored: List[Tuple[int, str]] = []  # (points, reason), sorted by points later

    for check in mandatory:
        points = cfg.weights[check.status]
        score += points
        if points:
            scored.append((points, f"{_label(check)}: {check.status.value} (+{points})"))

    identity_status = CheckStatus(identity_result.value) if identity_result is not None else CheckStatus.unverified
    identity_points = cfg.weights[identity_status]
    score += identity_points
    if identity_points:
        detail = identity_status.value if identity_result is not None else "not checked, counted as unverified"
        scored.append((identity_points, f"certification identity: {detail} (+{identity_points})"))

    if purpose is not None and purpose.strip().lower() == RESALE_PURPOSE and cfg.resale_bonus:
        score += cfg.resale_bonus
        scored.append((cfg.resale_bonus, f"purpose is resale (+{cfg.resale_bonus})"))
    if quantity is not None and quantity >= cfg.quantity_threshold and cfg.quantity_bonus:
        score += cfg.quantity_bonus
        scored.append((cfg.quantity_bonus,
                       f"quantity {quantity} is at or above {cfg.quantity_threshold} (+{cfg.quantity_bonus})"))
    needs_confirmation = (classification is not None
                          and classification.status is ClassificationStatus.needs_confirmation)
    if needs_confirmation and cfg.needs_confirmation_bonus:
        score += cfg.needs_confirmation_bonus
        scored.append((cfg.needs_confirmation_bonus,
                       f"classification needs confirmation (+{cfg.needs_confirmation_bonus})"))

    # Stable sort: highest points first, ties keep the order above.
    reasons = [text for _, text in sorted(scored, key=lambda item: -item[0])]

    contradictions = [c for c in mandatory if c.status is CheckStatus.contradiction_detected]
    identity_contradiction = identity_result is IdentityResult.contradiction_detected
    any_contradiction = bool(contradictions) or identity_contradiction
    prohibitions = [c for c in checks if c.prohibition_applies]

    level = _level_for(score, cfg)
    if any_contradiction and cfg.contradiction_forces_high:
        level = RiskLevel.high

    # ---- next actions, most urgent first ----
    actions: List[str] = []
    for check in prohibitions:
        actions.append(f"Do not proceed until an official source is checked: {_label(check)} indicates an "
                       "import prohibition.")
    for check in contradictions:
        actions.append(f"Obtain correct evidence for {_label(check)}: "
                       + ", ".join(check.requires_evidence or ["supporting evidence"]) + ".")
    if identity_contradiction:
        actions.append("Obtain correct certification evidence: potential certification mismatch between the "
                       "registry record and the seller's claim.")
    for check in mandatory:
        if check.status is CheckStatus.unverified:
            actions.append(f"Supply the missing product facts for {_label(check)}.")
    for check in mandatory:
        if check.status is CheckStatus.potentially_applicable:
            needed = ", ".join(check.requires_evidence) if check.requires_evidence else "evidence"
            actions.append(f"Obtain {needed} to confirm {_label(check)}.")
    if identity_status is CheckStatus.unverified:
        actions.append("Ask the seller for the certification registration record so it can be checked.")
    if needs_confirmation:
        actions.append(f"Confirm the product category (suggested: {classification.category}).")

    questions: List[str] = []
    if classification is None or classification.status is ClassificationStatus.unsupported:
        questions.append("What is the product category?")
    if quantity is None:
        questions.append("How many units do you plan to import?")
    if purpose is None:
        questions.append("Is the import for resale or personal use?")
    if classification is not None and classification.status is not ClassificationStatus.unsupported \
            and not mandatory:
        questions.append("No requirement rules were evaluated for this category; which requirements apply?")
    actions.extend(questions)

    if cost_estimate is not None and (not cost_estimate.rates_verified or cost_estimate.any_stale):
        actions.append("Treat the cost estimate as illustrative: it uses unverified or stale assumptions.")

    # ---- outcome precedence (decisions.md section 2) ----
    if prohibitions:
        outcome, level = Outcome.high_risk_do_not_proceed, RiskLevel.high
    elif questions:
        outcome = Outcome.insufficient_information
    elif any_contradiction:
        outcome, level = Outcome.conditional_import, RiskLevel.high
    elif any(c.status in _OPEN_STATUSES for c in mandatory) or identity_status is CheckStatus.unverified:
        outcome = Outcome.conditional_import
    else:
        outcome, level = Outcome.likely_importable, RiskLevel.low

    evidence_ids = sorted({eid for c in checks for eid in c.evidence_ids})
    rule_versions = [f"{c.rule_id}@{c.rule_version}" for c in checks]

    return RiskResult(
        outcome=outcome,
        risk_level=level,
        score=score,
        reasons=reasons,
        next_actions=actions,
        evidence_ids=evidence_ids,
        rule_versions=rule_versions,
    )
