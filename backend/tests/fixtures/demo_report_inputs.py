"""Inputs for the 100-speaker demo report (decisions.md sections 3, 8 and 9).

Five-rule run on the demo product, identity unverified (no registry record), resale,
quantity 100, classification needs_confirmation, golden-case cost (USD 10 x 100,
freight 12,000, insurance 0). Expected: conditional_import, high, score 10,
per-unit cost 1542.88.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.decision.classifier import Classification
from app.decision.cost_config import load_cost_assumptions
from app.decision.cost_engine import CostInputs, estimate_cost
from app.decision.enums import ClassificationStatus, Confidence, FactKind
from app.decision.report_schema import EvidenceItem, ProductFact, ProductProfile
from app.decision.rules.rule_engine import evaluate_rules, load_rules
from app.decision.verification_config import load_verification_config
from app.decision.verification_engine import CertClaim, verify_certification

INVESTIGATION_ID = "inv_demo_100_speakers"
AS_OF = date(2026, 10, 24)
LISTING_EVIDENCE_ID = "ev_listing_1"

RULE_PROFILE = {"category": "bluetooth_speaker", "has_bluetooth": True, "has_wifi": False, "has_battery": True}


def demo_evidence():
    return [
        EvidenceItem(
            id=LISTING_EVIDENCE_ID,
            source_url="https://seller.example/listing/bt-100",
            retrieved_at=datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc),
            excerpt="Portable Bluetooth Speaker BT-100, 10W, built-in 2000mAh battery. BIS R-41234567.",
            source_type="listing",
        )
    ]


def demo_profile(quantity=100, purpose="resale"):
    user_supplied = []
    if quantity is not None:
        user_supplied.append(ProductFact(field="quantity", value=quantity, kind=FactKind.user_supplied))
    if purpose is not None:
        user_supplied.append(ProductFact(field="purpose", value=purpose, kind=FactKind.user_supplied))
    return ProductProfile(
        confirmed=[
            ProductFact(field="title", value="Portable Bluetooth Speaker BT-100", kind=FactKind.confirmed,
                        evidence_id=LISTING_EVIDENCE_ID),
            ProductFact(field="bluetooth", value="5.0", kind=FactKind.confirmed, evidence_id=LISTING_EVIDENCE_ID),
            ProductFact(field="battery", value="2000mAh", kind=FactKind.confirmed, evidence_id=LISTING_EVIDENCE_ID),
        ],
        seller_claims=[
            ProductFact(field="bis_registration_no", value="R-41234567", kind=FactKind.seller_claim,
                        evidence_id=LISTING_EVIDENCE_ID),
        ],
        user_supplied=user_supplied,
    )


def demo_classification():
    return Classification(
        category="bluetooth_speaker",
        confidence=Confidence.low,
        status=ClassificationStatus.needs_confirmation,
        candidate_hs_codes=["8518.21", "8518.22"],
        reasoning="Possible bluetooth_speaker; the category needs confirmation.",
        score=Decimal("0.4"),
        config_version="test",
    )


def demo_checks():
    return evaluate_rules(RULE_PROFILE, load_rules("bluetooth_speaker"))


def demo_identity():
    claim = CertClaim(registration_no="R-41234567", manufacturer="Shenzhen Example Audio Co", model="BT-100")
    return verify_certification(claim, None, AS_OF, load_verification_config())


def demo_cost():
    inputs = CostInputs(unit_price=Decimal("10"), price_currency="USD", quantity=100,
                        freight_inr=Decimal("12000"), insurance_inr=Decimal("0"))
    return estimate_cost(inputs, load_cost_assumptions())


def demo_inputs(**overrides):
    """Keyword arguments for assemble_report; override any of them."""
    inputs = dict(
        investigation_id=INVESTIGATION_ID,
        classification=demo_classification(),
        checks=demo_checks(),
        identity_result=demo_identity(),
        cost_estimate=demo_cost(),
        profile=demo_profile(),
        evidence=demo_evidence(),
        questions_skipped=[],
    )
    inputs.update(overrides)
    return inputs
