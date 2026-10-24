"""Classifier tests: keyword/attribute scoring, thresholds, HS suggestions."""
import ast
import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.decision.classifier import DEFAULT_CONFIG_PATH, classify, load_classifier_config, parse_classifier_config
from app.decision.enums import ClassificationStatus, Confidence

CONFIG = load_classifier_config()


def raw_config():
    return yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def test_config_loads_with_decimal_numbers():
    assert CONFIG.confidence_threshold == Decimal("0.6")
    assert CONFIG.high_confidence_threshold == Decimal("0.85")
    weights = [s.weight for s in CONFIG.categories["bluetooth_speaker"].signals]
    assert all(isinstance(w, Decimal) for w in weights)


def test_hs_suggestions_are_marked_not_verified():
    for suggestion in CONFIG.categories["bluetooth_speaker"].hs_suggestions:
        assert "suggested, not verified" in suggestion.note


def test_strong_bluetooth_keywords_are_confirmed_high():
    result = classify({"title": "Portable Bluetooth Speaker 10W", "bluetooth": "5.0"}, CONFIG)
    assert result.status is ClassificationStatus.confirmed
    assert result.confidence is Confidence.high
    assert result.category == "bluetooth_speaker"
    assert result.score == Decimal(1)
    assert result.candidate_hs_codes == ["8518.21", "8518.22"]
    assert "suggested, not verified" in result.reasoning


def test_medium_score_is_confirmed_medium():
    data = raw_config()
    data["high_confidence_threshold"] = "0.95"
    cfg = parse_classifier_config(data)
    result = classify({"title": "Bluetooth Speaker"}, cfg)  # 0.5 + 0.2 + 0.2 = 0.9
    assert result.score == Decimal("0.9")
    assert result.status is ClassificationStatus.confirmed and result.confidence is Confidence.medium


def test_weak_keywords_need_confirmation():
    result = classify({"title": "BT-100 Mini Speaker", "description": "Pairs over bluetooth."}, CONFIG)
    assert result.score == Decimal("0.4")
    assert result.status is ClassificationStatus.needs_confirmation
    assert result.confidence is Confidence.low
    assert result.category == "bluetooth_speaker"
    assert result.candidate_hs_codes  # still suggested, flagged for confirmation
    assert "needs confirmation" in result.reasoning


def test_below_threshold_needs_confirmation():
    result = classify({"title": "Speaker"}, CONFIG)  # anchor + speaker keyword only: 0.2
    assert result.score < CONFIG.confidence_threshold
    assert result.status is ClassificationStatus.needs_confirmation


def test_exactly_at_threshold_is_confirmed():
    data = raw_config()
    data["confidence_threshold"] = "0.5"
    cfg = parse_classifier_config(data)
    # speaker (0.2) + bluetooth keyword (0.2) + bluetooth attribute (0.1) = 0.5
    result = classify({"title": "Speaker", "description": "bluetooth", "bluetooth": "yes"}, cfg)
    assert result.score == Decimal("0.5")
    assert result.status is ClassificationStatus.confirmed


def test_just_below_threshold_needs_confirmation():
    data = raw_config()
    data["confidence_threshold"] = "0.51"
    cfg = parse_classifier_config(data)
    result = classify({"title": "Speaker", "description": "bluetooth", "bluetooth": "yes"}, cfg)
    assert result.status is ClassificationStatus.needs_confirmation


@pytest.mark.parametrize("extracted", [
    {"title": "Stainless Steel Water Bottle 1L"},
    {"title": "Bluetooth Headphones"},          # bluetooth alone is not an anchor
    {"title": "Loudspeakerstand"},              # whole-word match only
    {},
    {"title": None, "description": 42},
])
def test_unknown_product_is_unsupported(extracted):
    result = classify(extracted, CONFIG)
    assert result.status is ClassificationStatus.unsupported
    assert result.category is None and result.candidate_hs_codes == []
    assert result.confidence is Confidence.low
    assert "Could not match" in result.reasoning


def test_matching_ignores_case_punctuation_and_accents():
    result = classify({"title": "PORTABLE  bluetooth-SPÉAKER!!", "bluetooth": "v5"}, CONFIG)
    assert result.status is ClassificationStatus.confirmed
    assert "speaker_phrase_in_title" in result.reasoning


def test_specifications_are_searched_for_bluetooth():
    result = classify({"title": "Speaker", "specifications": {"Connectivity": "Bluetooth 5.3"}}, CONFIG)
    assert result.score == Decimal("0.4")


def test_blank_attribute_does_not_count():
    with_attr = classify({"title": "Speaker", "bluetooth": "5.0"}, CONFIG)
    blank = classify({"title": "Speaker", "bluetooth": "   "}, CONFIG)
    assert with_attr.score - blank.score == Decimal("0.1")


def test_tie_between_categories_needs_confirmation():
    data = raw_config()
    data["categories"]["portable_speaker"] = copy.deepcopy(data["categories"]["bluetooth_speaker"])
    cfg = parse_classifier_config(data)
    result = classify({"title": "Portable Bluetooth Speaker", "bluetooth": "5.0"}, cfg)
    assert result.status is ClassificationStatus.needs_confirmation
    assert result.category == "bluetooth_speaker"  # alphabetical, and flagged
    assert "portable_speaker" in result.reasoning


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(confidence_threshold=0.6),                      # float
    lambda d: d.update(confidence_threshold="0"),
    lambda d: d.update(high_confidence_threshold="0.5"),               # below confidence threshold
    lambda d: d["categories"]["bluetooth_speaker"]["hs_suggestions"][0].update(note="8518"),
    lambda d: d["categories"]["bluetooth_speaker"]["signals"][0].update(attribute_present="bluetooth"),
    lambda d: d["categories"]["bluetooth_speaker"]["signals"][0].pop("fields"),
    lambda d: d["categories"]["bluetooth_speaker"].update(anchor_keywords=[]),
    lambda d: d["categories"].update({"Bad Name": d["categories"]["bluetooth_speaker"]}),
    lambda d: d.update(extra="x"),
])
def test_bad_config_is_rejected(mutate):
    data = raw_config()
    mutate(data)
    with pytest.raises(ValueError):
        parse_classifier_config(data)


def test_classify_is_deterministic_and_does_not_change_input():
    extracted = {"title": "Portable Bluetooth Speaker", "specifications": {"Battery": "2000mAh"}}
    before = copy.deepcopy(extracted)
    assert classify(extracted, CONFIG) == classify(extracted, CONFIG)
    assert extracted == before


def test_no_forbidden_words_in_reasoning():
    for extracted in ({"title": "Portable Bluetooth Speaker"}, {"title": "Speaker"}, {"title": "Kettle"}):
        text = classify(extracted, CONFIG).reasoning.lower()
        assert "fraud" not in text and "fake" not in text


def test_classifier_never_uses_eval_or_exec():
    source = (Path(__file__).resolve().parent.parent / "app" / "decision" / "classifier.py").read_text(
        encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    assert not names & {"eval", "exec", "compile", "__import__", "random", "socket", "requests", "httpx"}
