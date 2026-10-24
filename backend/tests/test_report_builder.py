"""Report schema and assembly tests (decisions.md section 9)."""
import ast
import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.decision.enums import CheckStatus, ClassificationStatus, FactKind, IdentityResult, Outcome, RiskLevel
from app.decision.report_builder import assemble_report
from app.decision.report_schema import DISCLAIMER, EvidenceItem, FullReport, ProductFact, ProductProfile
from tests.fixtures.demo_report_inputs import (
    INVESTIGATION_ID,
    LISTING_EVIDENCE_ID,
    demo_inputs,
    demo_profile,
)


@pytest.fixture(scope="module")
def report():
    return assemble_report(**demo_inputs())


# ---------------------------------------------------------------------------
# Demo case
# ---------------------------------------------------------------------------

def test_demo_outcome_risk_and_score(report):
    assert report.id == INVESTIGATION_ID
    assert report.outcome is Outcome.conditional_import
    assert report.risk_level is RiskLevel.high
    assert report.score == 10


def test_demo_disclaimer_present(report):
    assert report.disclaimer == DISCLAIMER == "Decision support only. Not legal clearance or customs approval."
    assert report.to_frontend()["disclaimer"] == DISCLAIMER


def test_demo_cost_per_unit(report):
    assert report.cost.per_unit_expected == Decimal("1542.88")
    assert report.cost.expected == Decimal("154287.59")
    assert report.summary.illustrative_cost_per_unit.expected == Decimal("1542.88")
    assert report.summary.illustrative_cost_per_unit.currency == "INR"
    assert report.cost.label == "Illustrative estimate, not a quote."


def test_demo_has_no_forbidden_words_anywhere(report):
    text = json.dumps(report.to_frontend()).lower()
    assert "fraud" not in text and "fake" not in text


def test_demo_summary(report):
    s = report.summary
    assert s.quantity == 100
    assert s.classification.value == "bluetooth_speaker"
    assert s.classification.status is ClassificationStatus.needs_confirmation
    assert s.bis is CheckStatus.potentially_applicable
    assert s.wireless is CheckStatus.potentially_applicable
    assert s.seller_claims_bis is True
    assert s.identity_match is IdentityResult.unverified


def test_demo_checks_and_comparison(report):
    assert [c.area for c in report.checks] == ["import_policy", "bis", "wireless", "battery", "labelling"]
    assert all(c.rule_version == "1.0" for c in report.checks)
    assert report.rule_versions == [f"{c.rule_id}@1.0" for c in report.checks]
    comparison = report.certification_comparison
    assert comparison.result is IdentityResult.unverified and comparison.record_reliable is False
    assert comparison.conflicts == []


def test_demo_next_actions_are_numbered_and_top_one_is_next_action(report):
    assert [a.priority for a in report.next_actions] == list(range(1, len(report.next_actions) + 1))
    assert report.next_action == report.next_actions[0].text
    assert any("Confirm the product category" in a.text for a in report.next_actions)


def test_demo_profile_and_evidence_carried(report):
    assert report.profile == demo_profile()
    assert [e.id for e in report.evidence] == [LISTING_EVIDENCE_ID]
    assert report.questions_skipped == []


# ---------------------------------------------------------------------------
# Frontend contract shape
# ---------------------------------------------------------------------------

def test_json_keys_are_camel_case(report):
    data = report.to_frontend()
    for key in ("id", "outcome", "riskLevel", "nextAction", "nextActions", "summary", "profile", "checks",
                "certificationComparison", "cost", "evidence", "ruleVersions", "questionsSkipped", "disclaimer"):
        assert key in data
    assert set(data["profile"]) == {"confirmed", "sellerClaims", "userSupplied"}
    assert "sellerClaimsBis" in data["summary"] and "illustrativeCostPerUnit" in data["summary"]
    assert "ruleVersion" in data["checks"][0] and "evidenceIds" in data["checks"][0]
    assert "perUnitExpected" in data["cost"]

    def snake_keys(node):
        if isinstance(node, dict):
            return [k for k in node if "_" in k] + [k for v in node.values() for k in snake_keys(v)]
        if isinstance(node, list):
            return [k for v in node for k in snake_keys(v)]
        return []

    assert snake_keys(data) == []


def test_enum_values_are_lowercase(report):
    data = report.to_frontend()
    assert data["outcome"] == "conditional_import" and data["riskLevel"] == "high"
    assert data["summary"]["identityMatch"] == "unverified"
    assert data["checks"][1]["status"] == "potentially_applicable"


def test_money_is_serialised_as_strings_not_floats(report):
    data = report.to_frontend()
    assert data["cost"]["perUnitExpected"] == "1542.88"
    assert data["summary"]["illustrativeCostPerUnit"]["expected"] == "1542.88"
    assert not any(isinstance(v, float) for v in _walk(data))


def _walk(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    else:
        yield node


def test_report_round_trips_from_frontend_json(report):
    assert FullReport.model_validate(report.to_frontend()) == report


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_disclaimer_cannot_be_changed(report):
    data = report.to_frontend()
    data["disclaimer"] = "Cleared for import."
    with pytest.raises(ValidationError):
        FullReport.model_validate(data)


def test_dangling_evidence_id_is_rejected():
    with pytest.raises(ValidationError, match="ev_listing_1"):
        assemble_report(**demo_inputs(evidence=[]))


def test_dangling_evidence_id_in_a_check_is_rejected(report):
    data = report.to_frontend()
    data["checks"][0]["evidenceIds"] = ["ev_missing"]
    with pytest.raises(ValidationError, match="ev_missing"):
        FullReport.model_validate(data)


def test_duplicate_evidence_id_is_rejected():
    ev = demo_inputs()["evidence"]
    with pytest.raises(ValidationError, match="duplicate"):
        assemble_report(**demo_inputs(evidence=ev + ev))


def test_fact_kind_must_match_its_list():
    with pytest.raises(ValidationError):
        ProductProfile(seller_claims=[ProductFact(field="x", value="y", kind=FactKind.confirmed, evidence_id="e")])


def test_confirmed_fact_needs_evidence_id():
    with pytest.raises(ValidationError):
        ProductProfile(confirmed=[ProductFact(field="title", value="Speaker", kind=FactKind.confirmed)])


@pytest.mark.parametrize("value", [1.5, None, [1], {"a": 1}])
def test_fact_value_rejects_float_and_non_scalars(value):
    with pytest.raises(ValidationError):
        ProductFact(field="x", value=value, kind=FactKind.user_supplied)


def test_evidence_retrieved_at_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        EvidenceItem(id="e", source_url="https://x.example", retrieved_at=datetime(2026, 10, 24),
                     source_type="listing")


def test_unknown_evidence_source_type_is_rejected():
    with pytest.raises(ValidationError):
        EvidenceItem(id="e", source_url="https://x.example", retrieved_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
                     source_type="forum")


def test_extra_fields_are_rejected(report):
    data = report.to_frontend()
    data["verdict"] = "ok"
    with pytest.raises(ValidationError):
        FullReport.model_validate(data)


def test_quantity_of_wrong_type_is_rejected():
    profile = ProductProfile(user_supplied=[ProductFact(field="quantity", value="100", kind=FactKind.user_supplied)])
    with pytest.raises(ValueError):
        assemble_report(**demo_inputs(profile=profile))


# ---------------------------------------------------------------------------
# Skipped and missing inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("skipped, question", [
    (["quantity"], "How many units do you plan to import?"),
    (["purpose"], "Is the import for resale or personal use?"),
    (["category"], "What is the product category?"),
])
def test_skipped_key_fact_gives_insufficient_information(skipped, question):
    result = assemble_report(**demo_inputs(questions_skipped=skipped))
    assert result.outcome is Outcome.insufficient_information
    assert question in [a.text for a in result.next_actions]
    assert result.questions_skipped == skipped


def test_skipped_category_drops_the_classification():
    result = assemble_report(**demo_inputs(questions_skipped=["category"]))
    assert result.summary.classification is None


@pytest.mark.parametrize("quantity, purpose", [(None, "resale"), (100, None)])
def test_missing_user_fact_gives_insufficient_information(quantity, purpose):
    result = assemble_report(**demo_inputs(profile=demo_profile(quantity=quantity, purpose=purpose)))
    assert result.outcome is Outcome.insufficient_information


def test_no_cost_estimate_gives_null_cost():
    result = assemble_report(**demo_inputs(cost_estimate=None))
    assert result.cost is None and result.summary.illustrative_cost_per_unit is None
    assert result.to_frontend()["cost"] is None
    assert result.score == 10


def test_no_identity_result_gives_null_comparison_and_is_still_scored():
    result = assemble_report(**demo_inputs(identity_result=None))
    assert result.certification_comparison is None
    assert result.summary.identity_match is IdentityResult.unverified
    assert result.score == 10


def test_no_seller_bis_claim():
    profile = demo_profile()
    profile = profile.model_copy(update={"seller_claims": []})
    result = assemble_report(**demo_inputs(profile=profile))
    assert result.summary.seller_claims_bis is False


def test_missing_bis_and_wireless_checks_are_null():
    result = assemble_report(**demo_inputs(checks=[]))
    assert result.summary.bis is None and result.summary.wireless is None
    assert result.outcome is Outcome.insufficient_information


# ---------------------------------------------------------------------------
# Determinism and purity
# ---------------------------------------------------------------------------

def test_deterministic_and_inputs_not_mutated():
    inputs = demo_inputs()
    before = copy.deepcopy(inputs)
    first = assemble_report(**inputs)
    assert assemble_report(**inputs) == first
    assert inputs == before


@pytest.mark.parametrize("module", ["report_builder.py", "report_schema.py"])
def test_no_eval_exec_clock_random_or_network(module):
    source = (Path(__file__).resolve().parent.parent / "app" / "decision" / module).read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    assert not names & {"eval", "exec", "compile", "__import__", "random", "socket", "requests", "httpx", "time"}
    for call in (".now(", ".utcnow(", ".today(", "time.time("):
        assert call not in source
