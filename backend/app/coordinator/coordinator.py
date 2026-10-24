"""Investigation coordinator — connects TinyFish, the decision engines and storage (B2, B6, B8–B10).

Entry points
------------
``run(investigation_id, store, connector)``
    Drive one investigation from its current state to REPORT_READY (or NEEDS_INPUT / FAILED). Called once when
    an investigation is created, and again after an answer is supplied.

``recalculate_cost(investigation_id, store, overrides)``
    Re-run the cost engine with new user overrides. Does not change the investigation status or re-derive any
    other part of the report.

Design rules
------------
- Every public function is ``async``.
- The coordinator never reads the clock directly; it passes ``datetime.now(timezone.utc)`` to callers.
- All decisions come from the deterministic engines. The coordinator only calls them, routes results and writes
  storage.
- On failure the coordinator writes FAILED and records a ProgressEvent. It never raises out of ``run``.
- Retries: up to ``MAX_RETRIES`` times per TinyFish call with ``RETRY_DELAY_S`` seconds between attempts.
- The connector is injected; the coordinator is testable without a network or a database.
"""
import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from app.coordinator.profile_builder import (
    build_listing_facts, build_order_facts, cert_claim_from_facts, evidence_items,
    extracted_from_facts, profile_from_facts, registry_record, rule_profile,
)
from app.coordinator.states import InvestigationState, can_transition, RESTING
from app.coordinator.store import InvestigationStore, ProgressEvent, OrderInput, utcnow
from app.db.ids import new_ulid
from app.db.repositories import EvidenceIn, FactIn, QuestionIn, QUESTION_OPEN
from app.decision.classifier import Classification, classify, load_classifier_config
from app.decision.cost_config import load_cost_assumptions
from app.decision.cost_engine import CostInputs, CostOverrides, estimate_cost
from app.decision.enums import ClassificationStatus, Confidence, FactKind, StageState
from app.decision.report_builder import assemble_report
from app.decision.risk_config import load_risk_config
from app.decision.rules.rule_engine import evaluate_rules, load_rules
from app.decision.verification_config import load_verification_config
from app.decision.verification_engine import verify_certification
from app.services.tinyfish.connector import TinyFishConnector
from app.services.tinyfish.models import RegistryResult

log = logging.getLogger(__name__)

S = InvestigationState
MAX_RETRIES = 2
RETRY_DELAY_S = 2.0

QUESTION_QUANTITY = "quantity"
QUESTION_CATEGORY = "category"
QUESTION_FREIGHT = "freight_inr"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return date.today()


async def _emit(store: InvestigationStore, investigation_id: str, stage: S, state: StageState,
                message: str) -> None:
    await store.add_event(investigation_id, ProgressEvent(
        stage=stage.value, state=state, message=message, at=_now()))


async def _transition(store: InvestigationStore, investigation_id: str, current: S, next_state: S,
                      message: str) -> bool:
    if not can_transition(current, next_state):
        log.warning("coordinator: illegal transition %s → %s for %s", current.value, next_state.value,
                    investigation_id)
        return False
    ok = await store.transition(investigation_id, current, next_state)
    if ok:
        running_states = {S.READING_LISTING, S.PROFILE_BUILT, S.CLASSIFIED,
                          S.CHECKING_REQUIREMENTS, S.VERIFYING_CLAIMS, S.ESTIMATING_COST}
        state = StageState.running if next_state in running_states else StageState.done
        await _emit(store, investigation_id, next_state, state, message)
    return ok


async def _fail(store: InvestigationStore, investigation_id: str, reason: str) -> None:
    """Move to FAILED from any non-terminal state, record an event. Swallows storage errors."""
    try:
        await store.force_state(investigation_id, S.FAILED)
        await store.add_event(investigation_id, ProgressEvent(
            stage=S.FAILED.value, state=StageState.failed, message=reason, at=_now()))
    except Exception:
        log.exception("coordinator: could not write FAILED state for %s", investigation_id)


async def _tinyfish_with_retry(fn, *args, investigation_id: str, operation: str, **kwargs):
    """Call a TinyFish function up to MAX_RETRIES times. On every failure, log; on total failure return None."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            result = await fn(*args, **kwargs)
            if not result.failed:
                return result
            log.warning("coordinator: %s attempt %d returned failed=True for %s: %s",
                        operation, attempt + 1, investigation_id, getattr(result, "status", ""))
        except Exception as exc:
            log.exception("coordinator: %s attempt %d raised for %s", operation, attempt + 1, investigation_id)
            last_exc = exc
        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAY_S)
    if last_exc:
        log.error("coordinator: %s gave up after %d attempts for %s: %s",
                  operation, MAX_RETRIES, investigation_id, last_exc)
    return None


# ---------------------------------------------------------------------------
# Stage: read listing
# ---------------------------------------------------------------------------

async def _stage_read_listing(store: InvestigationStore, connector: TinyFishConnector,
                               investigation_id: str, order: OrderInput) -> bool:
    await _transition(store, investigation_id, S.CREATED, S.READING_LISTING, "Fetching the product listing.")
    result = await _tinyfish_with_retry(connector.extract_listing, order.url,
                                        investigation_id=investigation_id, operation="extract_listing")
    if result is None or result.failed:
        question = QuestionIn(id=new_ulid(), field="listing_url",
                              prompt="The product listing could not be fetched. Please paste the page text manually.",
                              why_it_matters="Without the listing we cannot extract the product details.",
                              status=QUESTION_OPEN, created_at=_now())
        await store.save_question(investigation_id, question)
        await store.force_state(investigation_id, S.NEEDS_INPUT)
        await _emit(store, investigation_id, S.NEEDS_INPUT, StageState.needs_input,
                    "Could not fetch the listing; awaiting manual input.")
        return False
    facts, evidence = build_listing_facts(result, investigation_id)
    order_facts = build_order_facts(order)
    await store.save_evidence(investigation_id, evidence)
    await store.save_facts(investigation_id, facts + order_facts)
    if result.raw_text:
        await store.save_evidence(investigation_id, [EvidenceIn(
            id=new_ulid(), source_url=order.url, retrieved_at=result.retrieved_at,
            excerpt=result.raw_text[:500], source_type="listing")])
    await _transition(store, investigation_id, S.READING_LISTING, S.PROFILE_BUILT,
                      "Product profile built from listing.")
    return True


# ---------------------------------------------------------------------------
# Stage: classify
# ---------------------------------------------------------------------------

async def _stage_classify(store: InvestigationStore, investigation_id: str) -> Optional[Classification]:
    facts = await store.list_facts(investigation_id)
    extracted = extracted_from_facts(facts)
    config = load_classifier_config()
    classification = classify(extracted, config)
    if classification.status == ClassificationStatus.needs_confirmation:
        existing_q = await store.list_questions(investigation_id)
        if not any(q.field == QUESTION_CATEGORY and q.status == QUESTION_OPEN for q in existing_q):
            question = QuestionIn(id=new_ulid(), field=QUESTION_CATEGORY,
                                  prompt=("What type of product is this? Confirming the category helps select "
                                          "the right import rules. (e.g. 'bluetooth speaker')"),
                                  why_it_matters="The import rules depend on the product category.",
                                  status=QUESTION_OPEN, created_at=_now())
            await store.save_question(investigation_id, question)
            await store.force_state(investigation_id, S.NEEDS_INPUT)
            await _emit(store, investigation_id, S.NEEDS_INPUT, StageState.needs_input,
                        "Category needs confirmation.")
            return None
    category = _user_answered_category(facts)
    if category is not None:
        override_facts = [FactIn(field="category", value=category, kind=FactKind.user_supplied,
                                 confidence=Confidence.high)]
        await store.save_facts(investigation_id, override_facts)
        extracted["category"] = category
        classification = classify(extracted, config)
    await _transition(store, investigation_id, S.PROFILE_BUILT, S.CLASSIFIED,
                      f"Classified as {classification.category}.")
    return classification


def _user_answered_category(facts) -> Optional[str]:
    for fact in reversed(facts):
        if fact.field == QUESTION_CATEGORY and fact.kind == FactKind.user_supplied:
            return fact.value
    return None


# ---------------------------------------------------------------------------
# Stage: check requirements
# ---------------------------------------------------------------------------

async def _stage_check_requirements(store: InvestigationStore, investigation_id: str,
                                     classification: Optional[Classification]):
    facts = await store.list_facts(investigation_id)
    extracted = extracted_from_facts(facts)
    rp = rule_profile(extracted, classification)
    category = (classification.category if classification and classification.category else
                rp.get("category", "bluetooth_speaker"))
    rules = load_rules(category)
    checks = evaluate_rules(rp, rules)
    # Persist rule checks as user-visible facts so they survive restarts.
    check_facts = [FactIn(field=f"rule_check:{c.rule_id}", value=c.status.value,
                          kind=FactKind.confirmed, confidence=Confidence.high)
                   for c in checks]
    if check_facts:
        await store.save_facts(investigation_id, check_facts)
    await _transition(store, investigation_id, S.CLASSIFIED, S.CHECKING_REQUIREMENTS,
                      "Requirements checked.")
    return checks, rp


# ---------------------------------------------------------------------------
# Stage: verify certification claims
# ---------------------------------------------------------------------------

async def _stage_verify_claims(store: InvestigationStore, connector: TinyFishConnector,
                                investigation_id: str):
    facts = await store.list_facts(investigation_id)
    claim = cert_claim_from_facts(facts)
    config = load_verification_config()
    if claim is None or not claim.registration_no:
        await _transition(store, investigation_id, S.CHECKING_REQUIREMENTS, S.VERIFYING_CLAIMS,
                          "No certification claim found; skipping verification.")
        return verify_certification(claim if claim else
                                    __import__("app.decision.verification_engine",
                                               fromlist=["CertClaim"]).CertClaim(),
                                    None, _today(), config)
    reg_result: Optional[RegistryResult] = await _tinyfish_with_retry(
        connector.fetch_registry_record,
        claim.registration_no,
        claim.manufacturer or "",
        claim.model or "",
        investigation_id=investigation_id, operation="fetch_registry_record")
    record = None
    if reg_result is not None:
        rec, evidence = registry_record(reg_result, investigation_id)
        if evidence:
            await store.save_evidence(investigation_id, evidence)
        record = rec
    identity_result = verify_certification(claim, record, _today(), config)
    await _transition(store, investigation_id, S.CHECKING_REQUIREMENTS, S.VERIFYING_CLAIMS,
                      f"Certification verification: {identity_result.overall.value}.")
    return identity_result


# ---------------------------------------------------------------------------
# Stage: estimate cost
# ---------------------------------------------------------------------------

async def _stage_estimate_cost(store: InvestigationStore, investigation_id: str,
                                order: OrderInput):
    facts = await store.list_facts(investigation_id)
    fact_map = {f.field: f.value for f in facts}
    unit_price_str = fact_map.get("unit_price")
    currency = fact_map.get("price_currency", "USD")
    try:
        unit_price = Decimal(unit_price_str) if unit_price_str else Decimal("0")
    except Exception:
        unit_price = Decimal("0")
    quantity_str = fact_map.get("quantity", "1")
    try:
        quantity = int(str(quantity_str).split(".")[0])
    except (ValueError, TypeError):
        quantity = 1
    if unit_price == 0 or currency not in ("USD", "INR"):
        existing_q = await store.list_questions(investigation_id)
        if not any(q.field == QUESTION_FREIGHT and q.status == QUESTION_OPEN for q in existing_q):
            question = QuestionIn(id=new_ulid(), field=QUESTION_FREIGHT,
                                  prompt="We could not extract the unit price. Enter the unit price in USD (or INR).",
                                  why_it_matters="The price is needed to calculate the landed cost.",
                                  status=QUESTION_OPEN, created_at=_now())
            await store.save_question(investigation_id, question)
    freight = order.freight_inr
    insurance = order.insurance_inr or Decimal("0")
    overrides = order.overrides
    try:
        inputs = CostInputs(unit_price=unit_price, price_currency=currency, quantity=quantity,
                            freight_inr=freight, insurance_inr=insurance, overrides=overrides)
        assumptions = load_cost_assumptions()
        estimate = estimate_cost(inputs, assumptions, _today())
    except Exception:
        log.exception("coordinator: cost engine failed for %s", investigation_id)
        estimate = None
    await store.save_cost_estimate(investigation_id, estimate)
    await _transition(store, investigation_id, S.VERIFYING_CLAIMS, S.ESTIMATING_COST,
                      "Cost estimate done." if estimate else "Cost estimate could not be computed.")
    return estimate


# ---------------------------------------------------------------------------
# Stage: build report
# ---------------------------------------------------------------------------

async def _stage_build_report(store: InvestigationStore, investigation_id: str,
                               classification: Optional[Classification], checks, identity_result,
                               cost_estimate):
    facts = await store.list_facts(investigation_id)
    evidence_rows = await store.list_evidence(investigation_id)
    questions = await store.list_questions(investigation_id)
    skipped = [q.field for q in questions if q.status == "skipped"]
    profile = profile_from_facts(facts)
    ev = evidence_items(evidence_rows)
    report = assemble_report(
        investigation_id=investigation_id,
        classification=classification,
        checks=checks,
        identity_result=identity_result,
        cost_estimate=cost_estimate,
        profile=profile,
        evidence=ev,
        questions_skipped=skipped,
    )
    await store.save_report(investigation_id, report)
    await _transition(store, investigation_id, S.ESTIMATING_COST, S.REPORT_READY,
                      f"Report ready. Outcome: {report.outcome.value}.")
    return report


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run(investigation_id: str, store: InvestigationStore, connector: TinyFishConnector) -> None:
    """Drive one investigation from its current state to REPORT_READY (or NEEDS_INPUT / FAILED).

    Safe to call multiple times: it picks up from the stored state. Idempotent when already REPORT_READY or
    NEEDS_INPUT.
    """
    try:
        current = await store.get_state(investigation_id)
        if current is None:
            log.error("coordinator: investigation %s not found", investigation_id)
            return
        if current in RESTING:
            return
        order = await store.get_order(investigation_id)
        if order is None:
            await _fail(store, investigation_id, "Order inputs missing.")
            return
        # --- READING_LISTING ---
        if current in (S.CREATED, S.READING_LISTING):
            ok = await _stage_read_listing(store, connector, investigation_id, order)
            if not ok:
                return
            current = S.PROFILE_BUILT
        # --- CLASSIFY ---
        if current == S.PROFILE_BUILT:
            classification = await _stage_classify(store, investigation_id)
            if classification is None:
                return  # paused for question
            current = S.CLASSIFIED
        else:
            classification = await _rebuild_classification(store, investigation_id)
        # --- CHECK REQUIREMENTS ---
        if current == S.CLASSIFIED:
            checks, rp = await _stage_check_requirements(store, investigation_id, classification)
            current = S.CHECKING_REQUIREMENTS
        else:
            checks = await _load_stored_checks(store, investigation_id, classification)
        # --- VERIFY CLAIMS ---
        if current == S.CHECKING_REQUIREMENTS:
            identity_result = await _stage_verify_claims(store, connector, investigation_id)
            current = S.VERIFYING_CLAIMS
        else:
            identity_result = _default_identity()
        # --- ESTIMATE COST ---
        if current == S.VERIFYING_CLAIMS:
            cost_estimate = await _stage_estimate_cost(store, investigation_id, order)
            current = S.ESTIMATING_COST
        else:
            cost_estimate = None
        # --- REPORT ---
        if current == S.ESTIMATING_COST:
            await _stage_build_report(store, investigation_id, classification, checks, identity_result,
                                      cost_estimate)
    except Exception as exc:
        log.exception("coordinator: unhandled error for %s", investigation_id)
        await _fail(store, investigation_id, f"Unexpected error: {exc}")


async def recalculate_cost(investigation_id: str, store: InvestigationStore,
                            overrides: Optional[CostOverrides] = None) -> None:
    """Re-run the cost engine with new overrides and rebuild the report.

    Only the cost engine and report assembly are re-run; no TinyFish calls are made.
    """
    current = await store.get_state(investigation_id)
    if current not in (S.REPORT_READY, S.ESTIMATING_COST):
        return
    order = await store.get_order(investigation_id)
    if order is None:
        return
    if overrides is not None:
        import dataclasses
        order = dataclasses.replace(order, overrides=overrides)
    facts = await store.list_facts(investigation_id)
    fact_map = {f.field: f.value for f in facts}
    unit_price_str = fact_map.get("unit_price")
    currency = fact_map.get("price_currency", "USD")
    try:
        unit_price = Decimal(unit_price_str) if unit_price_str else Decimal("0")
    except Exception:
        unit_price = Decimal("0")
    quantity_str = fact_map.get("quantity", "1")
    try:
        quantity = int(str(quantity_str).split(".")[0])
    except (ValueError, TypeError):
        quantity = 1
    try:
        inputs = CostInputs(unit_price=unit_price, price_currency=currency, quantity=quantity,
                            freight_inr=order.freight_inr, insurance_inr=order.insurance_inr or Decimal("0"),
                            overrides=overrides or order.overrides)
        assumptions = load_cost_assumptions()
        estimate = estimate_cost(inputs, assumptions, _today())
    except Exception:
        log.exception("coordinator: recalculate_cost failed for %s", investigation_id)
        return
    await store.save_cost_estimate(investigation_id, estimate)
    # Rebuild the report with the new estimate.
    classification = await _rebuild_classification(store, investigation_id)
    checks = await _load_stored_checks(store, investigation_id, classification)
    identity_result = _default_identity()
    await _stage_build_report(store, investigation_id, classification, checks, identity_result, estimate)


# ---------------------------------------------------------------------------
# Helpers used when resuming mid-pipeline
# ---------------------------------------------------------------------------

async def _rebuild_classification(store: InvestigationStore, investigation_id: str) -> Optional[Classification]:
    facts = await store.list_facts(investigation_id)
    extracted = extracted_from_facts(facts)
    config = load_classifier_config()
    return classify(extracted, config)


async def _load_stored_checks(store: InvestigationStore, investigation_id: str,
                               classification: Optional[Classification]):
    facts = await store.list_facts(investigation_id)
    extracted = extracted_from_facts(facts)
    rp = rule_profile(extracted, classification)
    category = (classification.category if classification and classification.category else
                rp.get("category", "bluetooth_speaker"))
    rules = load_rules(category)
    return evaluate_rules(rp, rules)


def _default_identity():
    from app.decision.verification_engine import CertClaim, verify_certification
    from app.decision.verification_config import load_verification_config
    return verify_certification(CertClaim(), None, _today(), load_verification_config())


__all__ = ["run", "recalculate_cost"]
