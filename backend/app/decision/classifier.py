"""Product classification by keyword and attribute matching (PRD B7).

See docs/decisions.md section 8. Deterministic: no LLM, no I/O in classify().
Extracted page text is untrusted data; it is only lowercased, tokenised and
compared against configured keywords. HS codes are suggestions, never verified.
"""
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decision.cost_config import DecimalIn
from app.decision.enums import ClassificationStatus, Confidence

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "classifier_config.yaml"

HS_NOTE_MARKER = "suggested, not verified"

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # same form the rule loader accepts


class Signal(BaseModel):
    """Either keywords searched in fields, or a non-empty attribute."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: DecimalIn = Field(gt=0, le=1)
    keywords: List[str] = []
    fields: List[str] = []
    attribute_present: Optional[str] = None

    @model_validator(mode="after")
    def _check_form(self) -> "Signal":
        keyword_form = bool(self.keywords) or bool(self.fields)
        if keyword_form == (self.attribute_present is not None):
            raise ValueError(f"signal {self.name!r} needs either keywords+fields or attribute_present")
        if keyword_form and not (self.keywords and self.fields):
            raise ValueError(f"signal {self.name!r} needs both keywords and fields")
        return self


class HsSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    note: str

    @model_validator(mode="after")
    def _check_note(self) -> "HsSuggestion":
        if HS_NOTE_MARKER not in self.note:
            raise ValueError(f"HS suggestion {self.code} must be marked {HS_NOTE_MARKER!r}")
        return self


class CategoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_keywords: List[str] = Field(min_length=1)
    anchor_fields: List[str] = Field(min_length=1)
    signals: List[Signal] = Field(min_length=1)
    hs_suggestions: List[HsSuggestion] = []


class ClassifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    confidence_threshold: DecimalIn = Field(gt=0, le=1)
    high_confidence_threshold: DecimalIn = Field(gt=0, le=1)
    categories: Dict[str, CategoryConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_thresholds(self) -> "ClassifierConfig":
        if self.high_confidence_threshold < self.confidence_threshold:
            raise ValueError("high_confidence_threshold must be >= confidence_threshold")
        bad = [name for name in self.categories if not _CATEGORY_RE.match(name)]
        if bad:
            raise ValueError("invalid category name(s): " + ", ".join(bad))
        return self


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: Optional[str]
    confidence: Confidence
    status: ClassificationStatus
    candidate_hs_codes: List[str]  # suggestions only, never verified
    reasoning: str
    score: Decimal
    config_version: str


def parse_classifier_config(data: Any) -> ClassifierConfig:
    return ClassifierConfig.model_validate(data)


def load_classifier_config(path: Union[str, Path, None] = None) -> ClassifierConfig:
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_classifier_config(data)


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(_NON_ALNUM_RE.sub(" ", folded.lower()).split())


def _field_text(extracted: Mapping[str, Any], field: str) -> str:
    value = extracted.get(field)
    parts: List[str] = []
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, Mapping):
        parts.extend(str(k) for k in value.keys() if isinstance(k, str))
        parts.extend(v for v in value.values() if isinstance(v, str))
    elif isinstance(value, (list, tuple)):
        parts.extend(v for v in value if isinstance(v, str))
    return _normalise(" ".join(parts))


def _has_keyword(texts: List[str], keywords: List[str]) -> Optional[str]:
    for keyword in keywords:
        needle = f" {_normalise(keyword)} "
        if any(needle in f" {text} " for text in texts if text):
            return keyword
    return None


def _score_category(extracted: Mapping[str, Any], cfg: CategoryConfig):
    anchor = _has_keyword([_field_text(extracted, f) for f in cfg.anchor_fields], cfg.anchor_keywords)
    if anchor is None:
        return None
    score = Decimal(0)
    matched: List[str] = []
    for signal in cfg.signals:
        if signal.attribute_present is not None:
            value = extracted.get(signal.attribute_present)
            hit = isinstance(value, str) and bool(value.strip())
        else:
            hit = _has_keyword([_field_text(extracted, f) for f in signal.fields], signal.keywords) is not None
        if hit:
            score += signal.weight
            matched.append(signal.name)
    return min(score, Decimal(1)), matched


def classify(extracted: Mapping[str, Any], config: ClassifierConfig) -> Classification:
    """Map extracted listing fields to a supported category. Pure: no I/O."""
    scored = {}
    for name in sorted(config.categories):
        result = _score_category(extracted, config.categories[name])
        if result is not None:
            scored[name] = result

    if not scored:
        return Classification(
            category=None,
            confidence=Confidence.low,
            status=ClassificationStatus.unsupported,
            candidate_hs_codes=[],
            reasoning="Could not match the product to a supported category.",
            score=Decimal(0),
            config_version=config.version,
        )

    best = max(scored.values(), key=lambda r: r[0])[0]
    top = [name for name in sorted(scored) if scored[name][0] == best]
    category = top[0]
    score, matched = scored[category]
    hs_codes = [s.code for s in config.categories[category].hs_suggestions]
    signals = ", ".join(matched) if matched else "anchor keyword only"
    hs_text = f" Candidate HS codes {', '.join(hs_codes)} are suggested, not verified." if hs_codes else ""

    if len(top) > 1:
        status, confidence = ClassificationStatus.needs_confirmation, Confidence.low
        reasoning = (f"Several categories scored {score} ({', '.join(top)}); the category needs "
                     f"confirmation.{hs_text}")
    elif score >= config.confidence_threshold:
        status = ClassificationStatus.confirmed
        confidence = Confidence.high if score >= config.high_confidence_threshold else Confidence.medium
        reasoning = f"Matched {category} with score {score} (signals: {signals}).{hs_text}"
    else:
        status, confidence = ClassificationStatus.needs_confirmation, Confidence.low
        reasoning = (f"Possible {category}, score {score} is below the threshold "
                     f"{config.confidence_threshold} (signals: {signals}); the category needs confirmation.{hs_text}")

    return Classification(
        category=category,
        confidence=confidence,
        status=status,
        candidate_hs_codes=hs_codes,
        reasoning=reasoning,
        score=score,
        config_version=config.version,
    )
