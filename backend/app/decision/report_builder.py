"""Assemble the full report (PRD B5) from the decision-layer outputs.

See docs/decisions.md section 9. Pure apart from compute_risk loading the default
risk_weights.yaml: no clock, no network, no randomness, no eval/exec.
"""
from typing import Any, Collection, List, Optional, Sequence, Type

from app.decision.classifier import Classification
from app.decision.cost_engine import CostEstimate
from app.decision.enums import ClassificationStatus, IdentityResult
from app.decision.report_schema import (
    CertificationComparisonReport,
    EvidenceItem,
    FullReport,
    NextAction,
    ProductProfile,
    ReportAssumption,
    ReportCost,
    ReportCostLine,
    ReportFieldComparison,
    ReportSummary,
    RequirementCheckReport,
    SummaryClassification,
    SummaryCost,
)
from app.decision.risk_engine import compute_risk
from app.decision.rules.rule_engine import RequirementCheck
from app.decision.verification_engine import VerificationResult

QUANTITY_FIELD = "quantity"
PURPOSE_FIELD = "purpose"
CATEGORY_FIELD = "category"
BIS_CLAIM_FIELDS = ("bis_registration_no", "certification_claims")


def _user_value(profile: ProductProfile, field: str, expected: Type, skipped: Collection[str]) -> Any:
    if field in skipped:
        return None
    for fact in profile.user_supplied:
        if fact.field == field:
            # bool is a subclass of int; a bool is never a quantity.
            if not isinstance(fact.value, expected) or isinstance(fact.value, bool):
                raise ValueError(f"user-supplied {field} must be {expected.__name__}")
            return fact.value
    return None


def _seller_claims_bis(profile: ProductProfile) -> bool:
    for fact in profile.seller_claims:
        if fact.field in BIS_CLAIM_FIELDS:
            if isinstance(fact.value, bool):
                if fact.value:
                    return True
            elif isinstance(fact.value, str):
                if fact.value.strip():
                    return True
    return False


def _check_report(check: RequirementCheck) -> RequirementCheckReport:
    return RequirementCheckReport(
        rule_id=check.rule_id,
        area=check.area,
        status=check.status,
        reasoning=check.reasoning,
        rule_version=check.rule_version,
        evidence_ids=list(check.evidence_ids),
        mandatory=check.mandatory,
        requires_evidence=list(check.requires_evidence),
    )


def _comparison_report(result: VerificationResult) -> CertificationComparisonReport:
    return CertificationComparisonReport(
        result=result.overall,
        field_results=[
            ReportFieldComparison(field=f.field, claim_value=f.claim_value, record_value=f.record_value,
                                  result=f.result, reason=f.reason)
            for f in result.field_results
        ],
        conflicts=list(result.conflicts),
        record_reliable=result.record_reliable,
        evidence_ids=list(result.evidence_ids),
        reasoning=result.reasoning,
        seller_request_list=list(result.seller_request_list),
    )


def _cost_report(est: CostEstimate) -> ReportCost:
    return ReportCost(
        label=est.label,
        currency=est.currency,
        quantity=est.quantity,
        low=est.low,
        expected=est.expected,
        high=est.high,
        per_unit_low=est.per_unit_low,
        per_unit_expected=est.per_unit_expected,
        per_unit_high=est.per_unit_high,
        breakdown=[ReportCostLine(**line.model_dump()) for line in est.breakdown],
        assumptions=[ReportAssumption(**entry.model_dump()) for entry in est.assumptions],
        breakdown_note=est.breakdown_note,
        rates_verified=est.rates_verified,
        methodology_unverified=est.methodology_unverified,
        unverified_assumptions=est.unverified_assumptions,
        any_stale=est.any_stale,
        staleness_checked=est.staleness_checked,
        any_human_approved=est.any_human_approved,
        rates_verified_count=est.rates_verified_count,
        rates_total=est.rates_total,
        assumptions_version=est.assumptions_version,
        assumptions_effective_date=est.assumptions_effective_date,
    )


def _area_status(checks: Sequence[RequirementCheck], area: str):
    for check in checks:
        if check.area == area:
            return check.status
    return None


def assemble_report(
    investigation_id: str,
    classification: Optional[Classification],
    checks: Sequence[RequirementCheck],
    identity_result: Optional[VerificationResult],
    cost_estimate: Optional[CostEstimate],
    profile: ProductProfile,
    evidence: Sequence[EvidenceItem],
    questions_skipped: Sequence[str],
) -> FullReport:
    """Build the FullReport. Quantity and purpose come from the profile's user-supplied facts;
    a field listed in `questions_skipped` counts as missing."""
    skipped = list(questions_skipped)
    quantity = _user_value(profile, QUANTITY_FIELD, int, skipped)
    purpose = _user_value(profile, PURPOSE_FIELD, str, skipped)
    cls = None if CATEGORY_FIELD in skipped else classification
    identity = identity_result.overall if identity_result is not None else None

    risk = compute_risk(checks, identity, cls, quantity, purpose, cost_estimate)

    actions: List[NextAction] = [NextAction(priority=i, text=text) for i, text in enumerate(risk.next_actions, 1)]

    summary_cls = None
    if cls is not None:
        summary_cls = SummaryClassification(
            value=cls.category,
            status=cls.status,
            confidence=cls.confidence,
            candidate_hs_codes=list(cls.candidate_hs_codes) if cls.status is not ClassificationStatus.unsupported
            else [],
        )
    summary_cost = None
    if cost_estimate is not None:
        summary_cost = SummaryCost(currency=cost_estimate.currency, expected=cost_estimate.per_unit_expected)

    summary = ReportSummary(
        quantity=quantity,
        classification=summary_cls,
        bis=_area_status(checks, "bis"),
        wireless=_area_status(checks, "wireless"),
        seller_claims_bis=_seller_claims_bis(profile),
        identity_match=identity if identity is not None else IdentityResult.unverified,
        illustrative_cost_per_unit=summary_cost,
    )

    return FullReport(
        id=investigation_id,
        outcome=risk.outcome,
        risk_level=risk.risk_level,
        score=risk.score,
        next_action=actions[0].text if actions else None,
        next_actions=actions,
        reasons=list(risk.reasons),
        summary=summary,
        profile=profile,
        checks=[_check_report(c) for c in checks],
        certification_comparison=_comparison_report(identity_result) if identity_result is not None else None,
        cost=_cost_report(cost_estimate) if cost_estimate is not None else None,
        evidence=list(evidence),
        rule_versions=list(risk.rule_versions),
        questions_skipped=skipped,
    )
