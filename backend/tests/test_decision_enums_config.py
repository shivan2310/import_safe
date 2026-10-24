import copy
import re
from enum import Enum

import pytest
from pydantic import ValidationError

from app.decision import enums
from app.decision.enums import CheckStatus
from app.decision.risk_config import load_risk_config, parse_risk_config

ALL_ENUMS = [
    enums.CheckStatus,
    enums.ClassificationStatus,
    enums.FieldMatch,
    enums.IdentityResult,
    enums.FactKind,
    enums.Confidence,
    enums.Outcome,
    enums.RiskLevel,
    enums.StageState,
]
SNAKE = re.compile(r"^[a-z]+(_[a-z]+)*$")


@pytest.mark.parametrize("enum_cls", ALL_ENUMS)
def test_enum_values_snake_case_and_unique(enum_cls):
    assert issubclass(enum_cls, str) and issubclass(enum_cls, Enum)
    values = [m.value for m in enum_cls]
    assert all(SNAKE.match(v) for v in values)
    assert len(values) == len(set(values))
    assert all(m.name == m.value for m in enum_cls)


def test_enum_exact_values():
    assert [m.value for m in enums.Outcome] == [
        "likely_importable",
        "conditional_import",
        "high_risk_do_not_proceed",
        "insufficient_information",
    ]
    assert [m.value for m in enums.StageState] == ["pending", "running", "done", "needs_input", "failed"]


def test_yaml_loads_and_validates():
    cfg = load_risk_config()
    assert cfg.weights[CheckStatus.contradiction_detected] == 3
    assert cfg.weights[CheckStatus.unverified] == 2
    assert cfg.weights[CheckStatus.potentially_applicable] == 1
    assert cfg.quantity_threshold == 50
    assert cfg.ranges.high.max is None


def _raw():
    cfg = load_risk_config()
    return {
        "weights": {k.value: v for k, v in cfg.weights.items()},
        "resale_bonus": cfg.resale_bonus,
        "quantity_threshold": cfg.quantity_threshold,
        "quantity_bonus": cfg.quantity_bonus,
        "needs_confirmation_bonus": cfg.needs_confirmation_bonus,
        "contradiction_forces_high": cfg.contradiction_forces_high,
        "ranges": {
            "low": {"min": 0, "max": 1},
            "medium": {"min": 2, "max": 4},
            "high": {"min": 5, "max": None},
        },
    }


def test_valid_raw_config_parses():
    parse_risk_config(_raw())


def test_ranges_contiguous():
    r = load_risk_config().ranges
    assert r.low.min == 0
    assert r.medium.min == r.low.max + 1
    assert r.high.min == r.medium.max + 1
    assert r.high.max is None


def test_rejects_gap():
    raw = _raw()
    raw["ranges"]["medium"]["min"] = 3
    with pytest.raises(ValidationError):
        parse_risk_config(raw)


def test_rejects_overlap():
    raw = _raw()
    raw["ranges"]["medium"]["min"] = 1
    with pytest.raises(ValidationError):
        parse_risk_config(raw)


def test_rejects_negative_weight():
    raw = copy.deepcopy(_raw())
    raw["weights"]["unverified"] = -1
    with pytest.raises(ValidationError):
        parse_risk_config(raw)


def test_rejects_closed_high_range():
    raw = _raw()
    raw["ranges"]["high"]["max"] = 9
    with pytest.raises(ValidationError):
        parse_risk_config(raw)


def test_rejects_missing_weight():
    raw = _raw()
    del raw["weights"]["verified"]
    with pytest.raises(ValidationError):
        parse_risk_config(raw)
