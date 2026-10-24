"""Rate evidence policy: bounds, change limits, trusted domains and benchmark rules per rate_key.

Values live in policy.yaml (all proposed, to confirm); nothing here hardcodes them. Numbers are converted with
Decimal(str(value)) before validation, the same as cost_config.
"""
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.decision.cost_config import RANGE_FIELDS, DecimalIn
from app.decision.rates.models import RANGE_KEYS, RateKind, target_fields

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "policy.yaml"
_DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
_DECIMAL_KEYS = ("min_value", "max_value", "max_change_pct", "max_spread_ratio")
_BENCHMARK_ONLY = ("min_samples", "min_distinct_domains", "max_spread_ratio")
_FX_KEY = re.compile(r"^fx_[a-z]{3}_[a-z]{3}$")  # exchange-rate keys such as fx_usd_inr (not fx_variation_pct)


def _domain(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"domain {value!r} must be a string")
    domain = value.strip().lower().rstrip(".")
    if not _DOMAIN.match(domain):
        raise ValueError(f"invalid domain {value!r}; use a bare host name such as cbic.gov.in")
    return domain


class RatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RateKind
    required_unit: str
    currency_terms: List[str] = Field(default_factory=list)  # FX: the excerpt must name the currency
    min_value: DecimalIn = Field(ge=0)
    max_value: DecimalIn = Field(ge=0)
    max_change_pct: DecimalIn = Field(ge=0)
    tier1_domains: List[str] = Field(default_factory=list)
    tier2_domains: List[str] = Field(default_factory=list)
    min_samples: Optional[StrictInt] = Field(default=None, ge=1)
    min_distinct_domains: Optional[StrictInt] = Field(default=None, ge=1)
    max_spread_ratio: Optional[DecimalIn] = Field(default=None, ge=1)
    max_effective_date_future_days: StrictInt = Field(default=1, ge=0)
    proposal_expiry_days: StrictInt = Field(default=14, ge=1)

    @field_validator("tier1_domains", "tier2_domains")
    @classmethod
    def _domains(cls, value: List[Any]) -> List[str]:
        domains = [_domain(v) for v in value]
        if len(set(domains)) != len(domains):
            raise ValueError("duplicate domain in list")
        return domains

    @field_validator("currency_terms")
    @classmethod
    def _terms(cls, value: List[str]) -> List[str]:
        terms = [t.strip() for t in value]
        if any(not t for t in terms):
            raise ValueError("currency_terms must not contain empty strings")
        return terms

    @field_validator("required_unit")
    @classmethod
    def _unit(cls, value: str) -> str:
        unit = value.strip().lower()
        if not unit:
            raise ValueError("required_unit must not be empty")
        return unit

    @model_validator(mode="after")
    def _check(self) -> "RatePolicy":
        if self.min_value > self.max_value:
            raise ValueError("min_value must be <= max_value")
        if set(self.tier1_domains) & set(self.tier2_domains):
            raise ValueError("a domain cannot be in both tier1_domains and tier2_domains")
        benchmark_values = [getattr(self, name) for name in _BENCHMARK_ONLY]
        if self.kind is RateKind.benchmark and any(v is None for v in benchmark_values):
            raise ValueError("benchmark policy needs min_samples, min_distinct_domains and max_spread_ratio")
        if self.kind is RateKind.statutory:
            if any(v is not None for v in benchmark_values):
                raise ValueError("min_samples, min_distinct_domains and max_spread_ratio are for benchmarks only")
            if not self.tier1_domains:
                raise ValueError("a statutory rate needs at least one tier-1 domain")
        if self.required_unit == "percent" and self.max_value > 100:
            raise ValueError("a percent rate cannot have max_value above 100")
        return self


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    max_runs_per_refresh: StrictInt = Field(ge=1)
    max_domains_per_refresh: StrictInt = Field(ge=1)
    rates: Dict[str, RatePolicy]

    @model_validator(mode="after")
    def _keys(self) -> "Policy":
        if not self.version.strip():
            raise ValueError("version must not be empty")
        for key, rp in self.rates.items():
            try:
                target_fields(key)
            except KeyError as exc:
                raise ValueError(str(exc.args[0])) from exc
            if key in RANGE_KEYS and rp.kind is not RateKind.benchmark:
                raise ValueError(f"{key} must be a benchmark (it feeds a low/high range)")
            if rp.kind is RateKind.benchmark and key not in RANGE_KEYS and key not in RANGE_FIELDS:
                raise ValueError(
                    f"{key}: benchmarks must target {', '.join(RANGE_KEYS)} or a non-duty cost entry "
                    f"({', '.join(RANGE_FIELDS)})"
                )
            if _FX_KEY.match(key) and not rp.currency_terms:
                raise ValueError(f"{key} needs currency_terms so the excerpt check can find the currency")
        return self


def _to_decimal(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return value


def parse_policy(raw: Any) -> Policy:
    """Convert numeric Decimal fields with Decimal(str(v)), then validate."""
    if not isinstance(raw, dict):
        raise ValueError("rate policy must be a mapping")
    prepared = dict(raw)
    rates = prepared.get("rates")
    if isinstance(rates, dict):
        converted = {}
        for key, item in rates.items():
            if isinstance(item, dict):
                item = dict(item)
                for name in _DECIMAL_KEYS:
                    if name in item:
                        item[name] = _to_decimal(item[name])
            converted[key] = item
        prepared["rates"] = converted
    return Policy.model_validate(prepared)


def load_policy(path: Union[str, Path, None] = None) -> Policy:
    policy_path = Path(path) if path is not None else DEFAULT_POLICY_PATH
    with policy_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_policy(raw)
