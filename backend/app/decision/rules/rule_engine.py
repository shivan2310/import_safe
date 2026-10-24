"""Requirement rule engine (PRD B7). See docs/decisions.md section 8.

Rules are versioned YAML data. A condition is a structured dict that a hand-written
matcher walks; it is never an expression string and is never passed to eval/exec.
Evaluation is three-valued: a missing fact makes a leaf unknown, and an unknown
condition yields `unverified`, never `not_applicable`.
"""
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.decision.enums import CheckStatus

DEFAULT_RULES_DIR = Path(__file__).resolve().parent

MAX_CONDITION_DEPTH = 8
MAX_CONDITION_NODES = 64

LEAF_OPS = ("eq", "ne", "in", "not_in", "gte", "lte", "contains")
COMBINATORS = ("all", "any", "not")

# A rule may not claim verified or contradiction_detected on its own: those need evidence.
ALLOWED_RESULTS = (CheckStatus.potentially_applicable, CheckStatus.unverified, CheckStatus.not_applicable)
EVIDENCE_STATUSES = (CheckStatus.verified, CheckStatus.unverified, CheckStatus.contradiction_detected)

_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class RuleValidationError(ValueError):
    """A rules file or a rule condition failed validation."""


# ---------------------------------------------------------------------------
# Condition validation
# ---------------------------------------------------------------------------

def _is_scalar(value: Any) -> bool:
    # float is rejected on purpose: rule values are str, bool or int.
    return isinstance(value, (str, bool, int)) and not isinstance(value, float)


def _validate_node(node: Any, depth: int, count: List[int]) -> None:
    count[0] += 1
    if count[0] > MAX_CONDITION_NODES:
        raise ValueError(f"condition has more than {MAX_CONDITION_NODES} nodes")
    if depth > MAX_CONDITION_DEPTH:
        raise ValueError(f"condition is nested deeper than {MAX_CONDITION_DEPTH}")
    if isinstance(node, str):
        raise ValueError("condition must be a structured dict, not an expression string")
    if not isinstance(node, dict):
        raise ValueError(f"condition node must be a dict, got {type(node).__name__}")

    keys = set(node)
    if keys & set(COMBINATORS):
        if len(keys) != 1:
            raise ValueError(f"combinator node must have exactly one key, got {sorted(keys)}")
        (key,) = keys
        child = node[key]
        if key == "not":
            _validate_node(child, depth + 1, count)
            return
        if not isinstance(child, list) or not child:
            raise ValueError(f"'{key}' needs a non-empty list of conditions")
        for item in child:
            _validate_node(item, depth + 1, count)
        return

    if keys != {"field", "op", "value"}:
        raise ValueError(f"leaf node must have exactly the keys field, op, value; got {sorted(keys)}")
    field, op, value = node["field"], node["op"], node["value"]
    if not isinstance(field, str) or not _FIELD_RE.match(field):
        raise ValueError(f"invalid field name {field!r}")
    if op not in LEAF_OPS:
        raise ValueError(f"unknown op {op!r}; allowed: {', '.join(LEAF_OPS)}")
    if op in ("in", "not_in"):
        if not isinstance(value, list) or not value or not all(_is_scalar(v) for v in value):
            raise ValueError(f"'{op}' needs a non-empty list of str, bool or int values")
    elif op in ("gte", "lte"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{op}' needs an int value")
    elif not _is_scalar(value):
        raise ValueError(f"'{op}' needs a str, bool or int value, got {type(value).__name__}")


def validate_condition(condition: Any) -> None:
    _validate_node(condition, 1, [0])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _parse_iso_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("date must be an ISO string (YYYY-MM-DD)")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    category: str
    area: str = Field(min_length=1)
    condition: Dict[str, Any]
    result_if_true: CheckStatus
    requires_evidence: List[str]
    source_urls: List[str]
    version: str = Field(min_length=1)
    effective_date: date
    last_reviewed: date
    mandatory: bool = True
    prohibition: bool = False
    content_status: str = Field(min_length=1)

    @field_validator("condition", mode="before")
    @classmethod
    def _check_condition(cls, value: Any) -> Any:
        validate_condition(value)
        return value

    @field_validator("effective_date", "last_reviewed", mode="before")
    @classmethod
    def _check_dates(cls, value: Any) -> date:
        return _parse_iso_date(value)

    @field_validator("result_if_true")
    @classmethod
    def _check_result(cls, value: CheckStatus) -> CheckStatus:
        if value not in ALLOWED_RESULTS:
            raise ValueError(f"result_if_true {value.value!r} needs evidence and cannot come from a rule alone")
        return value

    @field_validator("category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if not _CATEGORY_RE.match(value):
            raise ValueError(f"invalid category {value!r}")
        return value


class RuleFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    rules_version: str = Field(min_length=1)
    content_status: str = Field(min_length=1)
    rules: List[Rule]

    @model_validator(mode="after")
    def _check_rules(self) -> "RuleFile":
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule id")
        wrong = [r.id for r in self.rules if r.category != self.category]
        if wrong:
            raise ValueError("rule category differs from the file category: " + ", ".join(wrong))
        return self


class EvidenceRef(BaseModel):
    """One piece of evidence, keyed by evidence type in the `evidence` mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    status: CheckStatus

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: CheckStatus) -> CheckStatus:
        if value not in EVIDENCE_STATUSES:
            raise ValueError("evidence status must be verified, unverified or contradiction_detected")
        return value


class RequirementCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    rule_version: str
    area: str
    status: CheckStatus
    reasoning: str
    evidence_ids: List[str]
    mandatory: bool
    prohibition_applies: bool
    requires_evidence: List[str]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def parse_rule_file(data: Any) -> RuleFile:
    try:
        return RuleFile.model_validate(data)
    except ValueError as exc:
        raise RuleValidationError(str(exc)) from exc


def load_rules(category: str, path: Union[str, Path, None] = None) -> List[Rule]:
    """Load the rules for `category` from `<path>/<category>_rules.yaml`.

    A category with no rules file returns an empty list. Any invalid rule rejects the
    whole file with RuleValidationError.
    """
    if not isinstance(category, str) or not _CATEGORY_RE.match(category):
        raise RuleValidationError(f"invalid category {category!r}")
    rules_dir = Path(path) if path is not None else DEFAULT_RULES_DIR
    rules_path = rules_dir / f"{category}_rules.yaml"
    if not rules_path.is_file():
        return []
    with rules_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rule_file = parse_rule_file(data)
    if rule_file.category != category:
        raise RuleValidationError(f"file category {rule_file.category!r} does not match {category!r}")
    return list(rule_file.rules)


# ---------------------------------------------------------------------------
# Evaluation (pure)
# ---------------------------------------------------------------------------

def _kind(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "str"
    return None


def _lookup(profile: Mapping[str, Any], field: str) -> Any:
    current: Any = profile
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _eval_leaf(node: Mapping[str, Any], profile: Mapping[str, Any]) -> Optional[bool]:
    actual = _lookup(profile, node["field"])
    op, value = node["op"], node["value"]
    if actual is None:
        return None
    if op == "contains":
        if isinstance(actual, str) and isinstance(value, str):
            return value.lower() in actual.lower()
        if isinstance(actual, (list, tuple)):
            same = [a for a in actual if _kind(a) == _kind(value)]
            if actual and not same:
                return None  # a list of other types says nothing about this value
            return value in same
        return None
    kind = _kind(actual)
    if kind is None:
        return None
    if op in ("eq", "ne"):
        if kind != _kind(value):
            return None
        return (actual == value) if op == "eq" else (actual != value)
    if op in ("in", "not_in"):
        same = [v for v in value if _kind(v) == kind]
        if not same:
            return None
        return (actual in same) if op == "in" else (actual not in same)
    # gte / lte
    if kind != "int":
        return None
    return actual >= value if op == "gte" else actual <= value


def _eval_node(node: Mapping[str, Any], profile: Mapping[str, Any], unknown: Set[str]) -> Optional[bool]:
    if "all" in node:
        results = [_eval_node(child, profile, unknown) for child in node["all"]]
        if False in results:
            return False
        return None if None in results else True
    if "any" in node:
        results = [_eval_node(child, profile, unknown) for child in node["any"]]
        if True in results:
            return True
        return None if None in results else False
    if "not" in node:
        inner = _eval_node(node["not"], profile, unknown)
        return None if inner is None else not inner
    result = _eval_leaf(node, profile)
    if result is None:
        unknown.add(node["field"])
    return result


def evaluate_condition(condition: Mapping[str, Any], profile: Mapping[str, Any]) -> Tuple[Optional[bool], List[str]]:
    """Return (True | False | None, sorted unknown fields)."""
    unknown: Set[str] = set()
    result = _eval_node(condition, profile, unknown)
    return result, sorted(unknown)


def _coerce_evidence(evidence: Optional[Mapping[str, Any]]) -> Dict[str, EvidenceRef]:
    if not evidence:
        return {}
    return {k: v if isinstance(v, EvidenceRef) else EvidenceRef.model_validate(v) for k, v in evidence.items()}


def _check_for_rule(rule: Rule, profile: Mapping[str, Any], evidence: Dict[str, EvidenceRef]) -> RequirementCheck:
    result, unknown_fields = evaluate_condition(rule.condition, profile)
    present = {name: evidence[name] for name in rule.requires_evidence if name in evidence}
    evidence_ids = [ref.evidence_id for ref in present.values()]
    note = f" Rule content status: {rule.content_status}."

    if result is False:
        status = CheckStatus.not_applicable
        reasoning = "The rule's condition is not met by the product details, so this requirement does not apply."
        evidence_ids = []
    elif result is None:
        status = CheckStatus.unverified
        reasoning = ("Could not verify: the product details are missing facts this rule needs ("
                     + ", ".join(unknown_fields) + ").")
        evidence_ids = []
    else:
        contradicting = [n for n, ref in present.items() if ref.status is CheckStatus.contradiction_detected]
        verified = [n for n, ref in present.items() if ref.status is CheckStatus.verified]
        not_confirmed = [n for n, ref in present.items() if ref.status is CheckStatus.unverified]
        if contradicting:
            status = CheckStatus.contradiction_detected
            reasoning = "Potential mismatch: evidence " + ", ".join(contradicting) + " conflicts with the claim."
            evidence_ids = [present[n].evidence_id for n in contradicting]
        elif rule.requires_evidence and len(verified) == len(rule.requires_evidence):
            status = CheckStatus.verified
            reasoning = "The required evidence (" + ", ".join(verified) + ") supports this check."
        else:
            status = rule.result_if_true
            reasoning = "The product details indicate this requirement may apply."
            unconfirmed = [n for n in rule.requires_evidence if n not in verified]
            if unconfirmed:
                reasoning += " Evidence needed: " + ", ".join(unconfirmed) + "."
            if not_confirmed:
                reasoning += " Could not verify the evidence supplied: " + ", ".join(not_confirmed) + "."

    return RequirementCheck(
        rule_id=rule.id,
        rule_version=rule.version,
        area=rule.area,
        status=status,
        reasoning=reasoning + note,
        evidence_ids=evidence_ids,
        mandatory=rule.mandatory,
        prohibition_applies=rule.prohibition and result is True,
        requires_evidence=list(rule.requires_evidence),
    )


def evaluate_rules(
    product_profile: Mapping[str, Any],
    rules: Sequence[Rule],
    evidence: Optional[Mapping[str, Any]] = None,
) -> List[RequirementCheck]:
    """Evaluate every rule for the profile's category, in rule order. Pure: no I/O."""
    category = product_profile.get("category")
    refs = _coerce_evidence(evidence)
    return [_check_for_rule(rule, product_profile, refs) for rule in rules if rule.category == category]
