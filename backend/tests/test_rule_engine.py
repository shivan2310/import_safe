"""Rule engine tests: loading, validation, three-valued evaluation, evidence."""
import ast
import copy
from pathlib import Path

import pytest
import yaml

from app.decision.enums import CheckStatus
from app.decision.rules.rule_engine import (
    DEFAULT_RULES_DIR,
    EvidenceRef,
    RuleValidationError,
    evaluate_condition,
    evaluate_rules,
    load_rules,
    parse_rule_file,
)

RULES_FILE = DEFAULT_RULES_DIR / "bluetooth_speaker_rules.yaml"
DEMO_PROFILE = {"category": "bluetooth_speaker", "has_bluetooth": True, "has_wifi": False, "has_battery": True}
CONTENT_STATUS = "requires human verification against official sources before demo"


def raw_rules():
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


def with_condition(condition):
    data = raw_rules()
    data["rules"][0]["condition"] = condition
    return data


def by_area(checks):
    return {c.area: c for c in checks}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_bluetooth_speaker_rules_load():
    rules = load_rules("bluetooth_speaker")
    assert [r.area for r in rules] == ["import_policy", "bis", "wireless", "battery", "labelling"]
    for rule in rules:
        assert rule.category == "bluetooth_speaker"
        assert rule.mandatory is True and rule.prohibition is False
        assert rule.content_status == CONTENT_STATUS
        assert rule.source_urls and all(u.startswith("https://") for u in rule.source_urls)
        assert rule.requires_evidence
        assert rule.version and rule.effective_date and rule.last_reviewed


def test_rules_file_is_marked_for_human_verification():
    data = raw_rules()
    assert data["content_status"] == CONTENT_STATUS
    assert "REQUIRES HUMAN VERIFICATION AGAINST OFFICIAL SOURCES BEFORE DEMO" in RULES_FILE.read_text(encoding="utf-8")


def test_unknown_category_returns_empty_list():
    assert load_rules("toaster") == []


def test_unknown_category_in_profile_evaluates_nothing():
    rules = load_rules("bluetooth_speaker")
    assert evaluate_rules({"category": "toaster"}, rules) == []
    assert evaluate_rules({}, rules) == []


@pytest.mark.parametrize("category", ["../rules", "bluetooth/speaker", "Bluetooth", "", "a b"])
def test_category_name_cannot_reach_other_files(category):
    with pytest.raises(RuleValidationError):
        load_rules(category)


def test_load_from_explicit_directory(tmp_path):
    (tmp_path / "bluetooth_speaker_rules.yaml").write_text(RULES_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    assert len(load_rules("bluetooth_speaker", tmp_path)) == 5
    assert load_rules("bluetooth_speaker", tmp_path / "missing") == []


def test_file_category_must_match_requested_category(tmp_path):
    (tmp_path / "toaster_rules.yaml").write_text(RULES_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(RuleValidationError):
        load_rules("toaster", tmp_path)


# ---------------------------------------------------------------------------
# Validation: bad rules are rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("condition", [
    "category == 'bluetooth_speaker'",                                  # expression string
    {"field": "category", "op": "matches", "value": "x"},               # unknown op
    {"field": "category", "op": "eq"},                                  # missing value
    {"field": "category", "op": "eq", "value": "x", "extra": 1},        # extra key
    {"field": "Category", "op": "eq", "value": "x"},                    # bad field name
    {"field": "__class__", "op": "eq", "value": "x"},                   # dunder field
    {"field": "price", "op": "eq", "value": 1.5},                       # float
    {"field": "quantity", "op": "gte", "value": "50"},                  # gte needs int
    {"field": "quantity", "op": "gte", "value": True},                  # bool is not int
    {"field": "category", "op": "in", "value": []},                     # empty list
    {"field": "category", "op": "in", "value": "bluetooth_speaker"},    # in needs list
    {"all": []},                                                        # empty combinator
    {"any": {"field": "a", "op": "eq", "value": 1}},                    # combinator needs list
    {"all": [{"field": "a", "op": "eq", "value": 1}], "any": []},       # two combinators
    {"not": "a == 1"},                                                  # string under not
    {},                                                                 # empty node
    ["category"],                                                       # list at top level
])
def test_bad_condition_is_rejected(condition):
    with pytest.raises(RuleValidationError):
        parse_rule_file(with_condition(condition))


def test_condition_too_deep_is_rejected():
    node = {"field": "a", "op": "eq", "value": 1}
    for _ in range(8):
        node = {"not": node}
    with pytest.raises(RuleValidationError):
        parse_rule_file(with_condition(node))


def test_condition_with_too_many_nodes_is_rejected():
    leaf = {"field": "a", "op": "eq", "value": 1}
    with pytest.raises(RuleValidationError):
        parse_rule_file(with_condition({"any": [copy.deepcopy(leaf) for _ in range(64)]}))


@pytest.mark.parametrize("result", ["verified", "contradiction_detected", "probably_fine"])
def test_rule_cannot_claim_a_result_that_needs_evidence(result):
    data = raw_rules()
    data["rules"][0]["result_if_true"] = result
    with pytest.raises(RuleValidationError):
        parse_rule_file(data)


@pytest.mark.parametrize("mutate", [
    lambda d: d["rules"][0].pop("source_urls"),
    lambda d: d["rules"][0].pop("content_status"),
    lambda d: d["rules"][0].update(effective_date="24/10/2026"),
    lambda d: d["rules"][0].update(category="toaster"),
    lambda d: d["rules"][1].update(id=d["rules"][0]["id"]),
    lambda d: d["rules"][0].update(unexpected="x"),
])
def test_bad_rule_fields_are_rejected(mutate):
    data = raw_rules()
    mutate(data)
    with pytest.raises(RuleValidationError):
        parse_rule_file(data)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def test_bis_rule_is_potentially_applicable_for_bluetooth_speaker():
    checks = by_area(evaluate_rules({"category": "bluetooth_speaker"}, load_rules("bluetooth_speaker")))
    bis = checks["bis"]
    assert bis.status is CheckStatus.potentially_applicable
    assert bis.rule_id == "bt_speaker_bis_v1" and bis.rule_version == "1.0"
    assert bis.requires_evidence == ["registration_record"] and bis.evidence_ids == []
    assert "registration_record" in bis.reasoning and CONTENT_STATUS in bis.reasoning


def test_demo_profile_gives_five_potentially_applicable_checks():
    checks = evaluate_rules(DEMO_PROFILE, load_rules("bluetooth_speaker"))
    assert [c.status for c in checks] == [CheckStatus.potentially_applicable] * 5
    assert all(c.mandatory and not c.prohibition_applies for c in checks)


def test_false_condition_is_not_applicable():
    profile = dict(DEMO_PROFILE, has_battery=False)
    assert by_area(evaluate_rules(profile, load_rules("bluetooth_speaker")))["battery"].status \
        is CheckStatus.not_applicable


def test_missing_fact_is_unverified_never_not_applicable():
    checks = by_area(evaluate_rules({"category": "bluetooth_speaker"}, load_rules("bluetooth_speaker")))
    for area, field in (("battery", "has_battery"), ("wireless", "has_bluetooth")):
        assert checks[area].status is CheckStatus.unverified
        assert field in checks[area].reasoning and "Could not verify" in checks[area].reasoning


def test_any_is_true_when_one_branch_is_true_even_if_another_is_unknown():
    check = by_area(evaluate_rules({"category": "bluetooth_speaker", "has_bluetooth": True},
                                   load_rules("bluetooth_speaker")))["wireless"]
    assert check.status is CheckStatus.potentially_applicable


def test_any_is_false_only_when_every_branch_is_false():
    profile = dict(DEMO_PROFILE, has_bluetooth=False, has_wifi=False)
    assert by_area(evaluate_rules(profile, load_rules("bluetooth_speaker")))["wireless"].status \
        is CheckStatus.not_applicable


A = {"field": "a", "op": "eq", "value": 1}
B = {"field": "b", "op": "eq", "value": 1}


@pytest.mark.parametrize("condition, profile, expected", [
    ({"all": [A, B]}, {"a": 1, "b": 1}, True),
    ({"all": [A, B]}, {"a": 1, "b": 2}, False),
    ({"all": [A, B]}, {"a": 2}, False),            # one False decides all
    ({"all": [A, B]}, {"a": 1}, None),
    ({"any": [A, B]}, {"a": 2, "b": 2}, False),
    ({"any": [A, B]}, {"a": 2}, None),
    ({"not": A}, {"a": 2}, True),
    ({"not": A}, {}, None),
    ({"field": "a", "op": "ne", "value": 1}, {"a": 2}, True),
    ({"field": "a", "op": "in", "value": [1, 2]}, {"a": 2}, True),
    ({"field": "a", "op": "not_in", "value": [1, 2]}, {"a": 3}, True),
    ({"field": "a", "op": "gte", "value": 50}, {"a": 50}, True),
    ({"field": "a", "op": "lte", "value": 50}, {"a": 51}, False),
    ({"field": "a", "op": "contains", "value": "Li-ion"}, {"a": "Built-in li-ion battery"}, True),
    ({"field": "a", "op": "contains", "value": "x"}, {"a": ["x", "y"]}, True),
    ({"field": "a", "op": "contains", "value": "z"}, {"a": []}, False),
    ({"field": "a.b", "op": "eq", "value": "x"}, {"a": {"b": "x"}}, True),
    ({"field": "a.b", "op": "eq", "value": "x"}, {"a": "not a dict"}, None),
])
def test_three_valued_evaluation(condition, profile, expected):
    result, _ = evaluate_condition(condition, profile)
    assert result is expected


@pytest.mark.parametrize("actual", [True, "1", 1.0, None, ["1"], {"x": 1}])
def test_type_mismatch_is_unknown_not_false(actual):
    # bool never equals int, and a string never equals a number.
    result, unknown = evaluate_condition(A, {"a": actual})
    assert result is None and unknown == ["a"]


def test_gte_on_a_string_is_unknown():
    assert evaluate_condition({"field": "q", "op": "gte", "value": 50}, {"q": "100"})[0] is None


def test_verified_evidence_makes_the_check_verified():
    evidence = {"registration_record": EvidenceRef(evidence_id="ev_reg_1", status=CheckStatus.verified)}
    bis = by_area(evaluate_rules(DEMO_PROFILE, load_rules("bluetooth_speaker"), evidence))["bis"]
    assert bis.status is CheckStatus.verified and bis.evidence_ids == ["ev_reg_1"]


def test_contradicting_evidence_makes_the_check_a_contradiction():
    evidence = {"registration_record": {"evidence_id": "ev_reg_2", "status": "contradiction_detected"}}
    bis = by_area(evaluate_rules(DEMO_PROFILE, load_rules("bluetooth_speaker"), evidence))["bis"]
    assert bis.status is CheckStatus.contradiction_detected and bis.evidence_ids == ["ev_reg_2"]
    assert "Potential mismatch" in bis.reasoning


def test_unverified_evidence_keeps_the_rule_result():
    evidence = {"registration_record": EvidenceRef(evidence_id="ev_reg_3", status=CheckStatus.unverified)}
    bis = by_area(evaluate_rules(DEMO_PROFILE, load_rules("bluetooth_speaker"), evidence))["bis"]
    assert bis.status is CheckStatus.potentially_applicable and bis.evidence_ids == ["ev_reg_3"]
    assert "Could not verify the evidence supplied: registration_record" in bis.reasoning


def test_evidence_does_not_matter_when_the_condition_is_unknown():
    evidence = {"battery_certification_record": {"evidence_id": "ev_b", "status": "contradiction_detected"}}
    battery = by_area(evaluate_rules({"category": "bluetooth_speaker"}, load_rules("bluetooth_speaker"),
                                     evidence))["battery"]
    assert battery.status is CheckStatus.unverified and battery.evidence_ids == []


@pytest.mark.parametrize("ref", [
    {"evidence_id": "", "status": "verified"},
    {"evidence_id": "ev", "status": "potentially_applicable"},
    {"evidence_id": "ev", "status": "not_applicable"},
])
def test_bad_evidence_is_rejected(ref):
    with pytest.raises(ValueError):
        evaluate_rules(DEMO_PROFILE, load_rules("bluetooth_speaker"), {"registration_record": ref})


def test_prohibition_applies_only_when_the_condition_is_true():
    data = raw_rules()
    data["rules"][0]["prohibition"] = True
    rules = parse_rule_file(data).rules
    assert evaluate_rules(DEMO_PROFILE, rules)[0].prohibition_applies is True
    data["rules"][0]["condition"] = {"field": "has_radio", "op": "eq", "value": True}
    rules = parse_rule_file(data).rules
    assert evaluate_rules(DEMO_PROFILE, rules)[0].prohibition_applies is False


def test_evaluation_is_deterministic_and_does_not_change_inputs():
    rules = load_rules("bluetooth_speaker")
    profile = copy.deepcopy(DEMO_PROFILE)
    first = evaluate_rules(profile, rules)
    assert evaluate_rules(profile, rules) == first
    assert profile == DEMO_PROFILE


def test_no_forbidden_words_in_reasoning():
    evidence = {"registration_record": {"evidence_id": "e", "status": "contradiction_detected"}}
    for profile in (DEMO_PROFILE, {"category": "bluetooth_speaker"}):
        for check in evaluate_rules(profile, load_rules("bluetooth_speaker"), evidence):
            text = check.reasoning.lower()
            assert "fraud" not in text and "fake" not in text


def test_rule_engine_never_uses_eval_or_exec():
    source = (Path(__file__).resolve().parent.parent / "app" / "decision" / "rules" / "rule_engine.py").read_text(
        encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    assert not names & {"eval", "exec", "compile", "__import__", "getattr", "globals", "locals"}


def test_rules_init_has_no_logic():
    source = (DEFAULT_RULES_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Expr)) for n in tree.body)
