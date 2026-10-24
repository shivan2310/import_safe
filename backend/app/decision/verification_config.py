"""Verification engine configuration model and loader.

Values live in verification_config.yaml only; see docs/decisions.md section 6.
This module only loads and validates the config. The engine lives in
verification_engine.py; field comparison and the overall result are there, not here.
"""
from pathlib import Path
from typing import Any, List, Union

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "verification_config.yaml"

# The comparison fields named in docs/decisions.md section 6 / PRD B8.
KNOWN_FIELDS = {
    "registration_no",
    "manufacturer",
    "factory_location",
    "category",
    "model_scope",
    "brand",
    "validity",
}


def _check_lowercase_strings(values: List[str], label: str) -> None:
    for v in values:
        if not isinstance(v, str) or not v:
            raise ValueError(f"{label} entries must be non-empty strings")
        if v != v.lower():
            raise ValueError(f"{label} entry {v!r} must be lowercase")


class VerificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuzzy_threshold: float
    legal_suffixes: List[str]
    inactive_statuses: List[str]
    required_fields: List[str]
    optional_fields: List[str]

    @model_validator(mode="after")
    def _check_threshold(self) -> "VerificationConfig":
        if not (0 < self.fuzzy_threshold < 1):
            raise ValueError("fuzzy_threshold must be strictly between 0 and 1")
        return self

    @model_validator(mode="after")
    def _check_suffixes_and_statuses(self) -> "VerificationConfig":
        _check_lowercase_strings(self.legal_suffixes, "legal_suffixes")
        _check_lowercase_strings(self.inactive_statuses, "inactive_statuses")
        return self

    @model_validator(mode="after")
    def _check_fields(self) -> "VerificationConfig":
        if not self.required_fields:
            raise ValueError("required_fields must not be empty")
        unknown = (set(self.required_fields) | set(self.optional_fields)) - KNOWN_FIELDS
        if unknown:
            raise ValueError("unknown field name(s): " + ", ".join(sorted(unknown)))
        overlap = set(self.required_fields) & set(self.optional_fields)
        if overlap:
            raise ValueError("required_fields and optional_fields overlap: " + ", ".join(sorted(overlap)))
        return self


def parse_verification_config(data: Any) -> VerificationConfig:
    return VerificationConfig.model_validate(data)


def load_verification_config(path: Union[str, Path, None] = None) -> VerificationConfig:
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_verification_config(data)
