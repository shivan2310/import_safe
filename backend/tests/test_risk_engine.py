"""Risk engine tests: precedence (decisions.md s2), score (s3), interpretations (s8)."""
import ast
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.decision.classifier import Classification
from app.decision.cost_engine import CostEstimate
from app.decision.enums import CheckStatus, ClassificationStatus, Confidence, IdentityResult, Outcome, RiskLevel
from app.decision.risk_config import DEFAULT_CONFIG_PATH, parse_risk_config
from app.decision.risk_engine import compute_risk
from app.decision.rules.rule_engine import RequirementCheck, evaluate_rules, load_rules

PA = CheckStatus.potentially_applicable
V = CheckStatus.verified


def check(area, status, mandatory=True, prohibition=False, evidence_ids=None):
    return RequirementCheck(
        rule_id=f"bt_speaker_{area}_v1", rule_version="1.0", area=area, status=status,
        reasoning="test", evidence_ids=evidence_ids or [], mandatory=mandatory,
        prohibition_applies=prohibition, requires_evidence=[f"{area}_record"],
    )


def classification(status=ClassificationStatus.confirmed):
    confidence = Confidence.high if status is ClassificationStatus.confirmed else Confidence.low
    return Classification(category="bluetooth_speaker" if status is not ClassificationStatus.unsupported else None,
                          confidence=confidence, status=status, candidate_hs_codes=[], reasoning="test",
                          score=Decimal("0.9"), config_version="test")


def risk(checks, identity=IdentityResult.verified, cls=None, quantity=10, purpose="personal", cost=None, **kw):
    return compute_risk(checks, identity, classification() if cls is None else cls, quantity, purpose, cost, **kw)


def demo():
    return compute_risk(
        [check("bis", PA), check("wireless", PA)],
        IdentityResult.unverified,
        classification(ClassificationStatus.needs_confirmation),
        100,
        "resale",
        None,
    )


# ---------------------------------------------------------------------------
# The worked demo (decisions.md section 3)
# ---------------------------------------------------------------------------

def test_demo_case_scores_7_and_is_conditional_import_high():
    result = demo()
    assert result.score == 7
    assert result.outcome is Outcome.conditional_import
    assert result.risk_level is RiskLevel.high


def test_demo_case_reasons_and_actions():
    result = demo()
    assert result.reasons[0] == "certification identity: unverified (+2)"  # highest points first
    assert "bis (rule bt_speaker_bis_v1 v1.0): potentially_applicable (+1)" in result.reasons
    assert "purpose is resale (+1)" in result.reasons
    assert "quantity 100 is at or above 50 (+1)" in result.reasons
    assert "classification needs confirmation (+1)" in result.reasons
    assert len(result.reasons) == 6
    assert "Obtain bis_record to confirm bis (rule bt_speaker_bis_v1 v1.0)." in result.next_actions
    assert any("certification registration record" in a for a in result.next_actions)
    assert "Confirm the product category (suggested: bluetooth_speaker)." in result.next_actions
    assert result.rule_versions == ["bt_speaker_bis_v1@1.0", "bt_speaker_wireless_v1@1.0"]


def test_full_five_rule_run_on_demo_profile_scores_higher_than_7():
    # decisions.md section 8: the section 3 score of 7 is a risk-engine input example.
    profile = {"category": "bluetooth_speaker", "has_bluetooth": True, "has_wifi": False, "has_battery": True}
    checks = evaluate_rules(profile, load_rules("bluetooth_speaker"))
    result = compute_risk(checks, IdentityResult.unverified, classification(ClassificationStatus.needs_confirmation),
                          100, "resale", None)
    assert result.score == 10
    assert result.outcome is Outcome.conditional_import and result.risk_level is RiskLevel.high


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------

def test_contradiction_forces_high_regardless_of_score():
    result = risk([check("bis", CheckStatus.contradiction_detected), check("wireless", V)])
    assert result.score == 3  # medium by range
    assert result.outcome is Outcome.conditional_import and result.risk_level is RiskLevel.high
    assert result.next_actions[0].startswith("Obtain correct evidence for bis")


def test_identity_contradiction_forces_high():
    result = risk([check("bis", V)], identity=IdentityResult.contradiction_detected)
    assert result.score == 3
    assert result.outcome is Outcome.conditional_import and result.risk_level is RiskLevel.high
    assert any("potential certification mismatch" in a for a in result.next_actions)


def test_contradiction_forces_high_even_when_weights_are_zero():
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data["weights"]["contradiction_detected"] = 0
    result = risk([check("bis", CheckStatus.contradiction_detected)], config=parse_risk_config(data))
    assert result.score == 0 and result.risk_level is RiskLevel.high


def test_all_verified_is_likely_importable_low():
    result = risk([check(a, V) for a in ("import_policy", "bis", "wireless", "battery", "labelling")])
    assert result.score == 0
    assert result.outcome is Outcome.likely_importable and result.risk_level is RiskLevel.low


def test_likely_importable_is_low_even_with_bonuses():
    # decisions.md section 2 rule 5: likely_importable, risk low; the score is still reported.
    result = risk([check("bis", V)], quantity=100, purpose="resale")
    assert result.score == 2
    assert result.outcome is Outcome.likely_importable and result.risk_level is RiskLevel.low


def test_not_applicable_checks_do_not_block_likely_importable():
    result = risk([check("bis", V), check("battery", CheckStatus.not_applicable)])
    assert result.outcome is Outcome.likely_importable


def test_missing_classification_is_insufficient_information():
    result = compute_risk([check("bis", V)], IdentityResult.verified, None, 10, "personal", None)
    assert result.outcome is Outcome.insufficient_information
    assert "What is the product category?" in result.next_actions


def test_unsupported_classification_is_insufficient_information():
    result = risk([check("bis", V)], cls=classification(ClassificationStatus.unsupported))
    assert result.outcome is Outcome.insufficient_information


def test_needs_confirmation_does_not_trigger_insufficient_information():
    result = risk([check("bis", V)], cls=classification(ClassificationStatus.needs_confirmation))
    assert result.outcome is Outcome.likely_importable and result.score == 1


@pytest.mark.parametrize("quantity, purpose, question", [
    (None, "personal", "How many units do you plan to import?"),
    (10, None, "Is the import for resale or personal use?"),
])
def test_skipped_key_fact_is_insufficient_information(quantity, purpose, question):
    result = risk([check("bis", V)], quantity=quantity, purpose=purpose)
    assert result.outcome is Outcome.insufficient_information
    assert question in result.next_actions


def test_no_mandatory_checks_is_insufficient_information():
    result = risk([check("bis", V, mandatory=False)])
    assert result.outcome is Outcome.insufficient_information
    assert any("No requirement rules were evaluated" in a for a in result.next_actions)


def test_insufficient_information_risk_follows_score_and_contradiction():
    result = compute_risk([check("bis", CheckStatus.contradiction_detected)], IdentityResult.verified, None, 10,
                          "personal", None)
    assert result.outcome is Outcome.insufficient_information and result.risk_level is RiskLevel.high


def test_prohibition_is_high_risk_do_not_proceed():
    result = risk([check("import_policy", PA, prohibition=True), check("bis", V)])
    assert result.outcome is Outcome.high_risk_do_not_proceed and result.risk_level is RiskLevel.high
    assert result.next_actions[0].startswith("Do not proceed until an official source is checked")


def test_prohibition_wins_over_missing_classification():
    result = compute_risk([check("import_policy", PA, prohibition=True)], IdentityResult.verified, None, 10,
                          "personal", None)
    assert result.outcome is Outcome.high_risk_do_not_proceed


# ---------------------------------------------------------------------------
# Score and levels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("statuses, expected_score, expected_level", [
    ([PA], 1, RiskLevel.low),
    ([PA, PA], 2, RiskLevel.medium),
    ([CheckStatus.unverified, PA, PA], 4, RiskLevel.medium),
    ([CheckStatus.unverified, CheckStatus.unverified, PA], 5, RiskLevel.high),
])
def test_conditional_import_risk_follows_score_ranges(statuses, expected_score, expected_level):
    result = risk([check(f"area{i}", s) for i, s in enumerate(statuses)])
    assert result.outcome is Outcome.conditional_import
    assert result.score == expected_score and result.risk_level is expected_level


@pytest.mark.parametrize("quantity, bonus", [(49, 0), (50, 1), (51, 1)])
def test_quantity_threshold_is_inclusive(quantity, bonus):
    assert risk([check("bis", V)], quantity=quantity).score == bonus


@pytest.mark.parametrize("purpose, bonus", [("resale", 1), (" Resale ", 1), ("personal", 0), ("sample", 0)])
def test_only_resale_adds_a_point(purpose, bonus):
    assert risk([check("bis", V)], purpose=purpose).score == bonus


def test_missing_identity_result_counts_as_unverified():
    result = risk([check("bis", V)], identity=None)
    assert result.score == 2 and result.outcome is Outcome.conditional_import
    assert "certification identity: not checked, counted as unverified (+2)" in result.reasons


def test_non_mandatory_checks_are_not_scored():
    result = risk([check("bis", V), check("extra", CheckStatus.unverified, mandatory=False)])
    assert result.score == 0 and result.outcome is Outcome.likely_importable


def test_weights_come_from_config():
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data["weights"]["potentially_applicable"] = 4
    data["resale_bonus"] = 0
    result = risk([check("bis", PA)], purpose="resale", config=parse_risk_config(data))
    assert result.score == 4


def test_evidence_ids_and_rule_versions_are_carried():
    result = risk([check("bis", V, evidence_ids=["ev_2", "ev_1"]), check("wireless", V, evidence_ids=["ev_1"])])
    assert result.evidence_ids == ["ev_1", "ev_2"]
    assert result.rule_versions == ["bt_speaker_bis_v1@1.0", "bt_speaker_wireless_v1@1.0"]


def test_cost_estimate_never_changes_the_score():
    unverified = CostEstimate.model_construct(rates_verified=False, any_stale=False)
    verified = CostEstimate.model_construct(rates_verified=True, any_stale=False)
    with_note = risk([check("bis", V)], cost=unverified)
    without = risk([check("bis", V)], cost=verified)
    assert with_note.score == without.score == 0
    assert any("illustrative" in a for a in with_note.next_actions)
    assert not any("illustrative" in a for a in without.next_actions)


def test_no_forbidden_words_in_output():
    results = [
        demo(),
        risk([check("bis", CheckStatus.contradiction_detected)], identity=IdentityResult.contradiction_detected),
        risk([check("import_policy", PA, prohibition=True)]),
        compute_risk([], None, None, None, None, None),
    ]
    for result in results:
        text = result.model_dump_json().lower()
        assert "fraud" not in text and "fake" not in text


def test_risk_engine_has_no_hardcoded_weights_or_forbidden_calls():
    source = (Path(__file__).resolve().parent.parent / "app" / "decision" / "risk_engine.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"eval", "exec", "compile", "__import__", "getattr", "random", "time"}
    numbers = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) is int}
    assert numbers <= {0}, f"numeric literals in risk_engine.py: {numbers}"
