"""Cost assumptions model and loader. Rates are Decimal, never float; values live in cost_assumptions.yaml."""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, List, Literal, Optional, Tuple, Union

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictInt,
    field_validator,
    model_validator,
)

from app.decision.rates.provenance import EvidenceKind, Provenance

DEFAULT_COST_PATH = Path(__file__).resolve().parent / "cost_assumptions.yaml"
# Non-duty cost entries that may carry a range_low/range_high (e.g. from an approved market benchmark).
RANGE_FIELDS = ("clearing_inr", "port_cfs_inr", "domestic_transport_inr", "certification_inr")

# Re-exported so the engine can type and compare dates without importing datetime itself.
Date = date
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_as_of(value: str) -> date:
    """Parse a strict ISO date (YYYY-MM-DD); raise a clear error otherwise."""
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        raise ValueError(f"date {value!r} is not an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date {value!r} is not a valid calendar date") from exc


def _check_iso(value: str) -> str:
    parse_as_of(value)
    return value


def reject_float(value: Any) -> Any:
    """Floats (and bools) never reach a Decimal field; use int, str or Decimal."""
    if isinstance(value, (float, bool)):
        raise ValueError("float/bool not allowed for Decimal values; use int, str or Decimal")
    return value


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("value must be finite")
    return value


DecimalIn = Annotated[Decimal, BeforeValidator(reject_float), AfterValidator(_finite)]


class Assumption(BaseModel):
    """One configurable assumption. verified means checked against an official source."""

    model_config = ConfigDict(extra="forbid")

    value: DecimalIn = Field(ge=0)
    source: str
    as_of: str
    verified: bool
    owner: str = "TBD"
    max_age_days: StrictInt = Field(gt=0)
    provenance: Provenance = Provenance.placeholder
    evidence_kind: Optional[EvidenceKind] = None
    evidence_note: Optional[str] = None
    # Optional low/high range, only on RANGE_FIELDS; both bounds or neither, with range_low <= value <= range_high.
    range_low: Optional[DecimalIn] = Field(default=None, ge=0)
    range_high: Optional[DecimalIn] = Field(default=None, ge=0)

    @field_validator("as_of")
    @classmethod
    def _iso_as_of(cls, value: str) -> str:
        return _check_iso(value)

    @model_validator(mode="after")
    def _check_range(self) -> "Assumption":
        if (self.range_low is None) != (self.range_high is None):
            raise ValueError("range_low and range_high must be set together")
        if self.range_low is not None and not (self.range_low <= self.value <= self.range_high):
            raise ValueError("range must satisfy range_low <= value <= range_high")
        return self


class OtherDuty(BaseModel):
    """Additional duty charged on its own base."""

    model_config = ConfigDict(extra="forbid")

    label: str
    rate_pct: DecimalIn = Field(ge=0, le=100)
    base: Literal["cif", "assessable_value", "bcd"]
    source: str
    as_of: str
    verified: bool
    owner: str = "TBD"
    max_age_days: Optional[StrictInt] = Field(default=None, gt=0)  # None: staleness not checked

    @field_validator("as_of")
    @classmethod
    def _iso_as_of(cls, value: str) -> str:
        return _check_iso(value)


_PERCENT_FIELDS = (
    "landing_charge_pct",
    "bcd_pct",
    "sws_pct_of_bcd",
    "igst_pct",
    "insurance_pct_of_goods",
    "fx_variation_pct",
    "freight_variation_pct",
    "bcd_low_pct",
    "bcd_high_pct",
)


class CostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fx_usd_inr: Assumption
    landing_charge_pct: Assumption
    bcd_pct: Assumption
    sws_pct_of_bcd: Assumption
    igst_pct: Assumption
    insurance_pct_of_goods: Assumption
    clearing_inr: Assumption
    port_cfs_inr: Assumption
    domestic_transport_inr: Assumption
    certification_inr: Assumption
    other_duties: List[OtherDuty] = Field(default_factory=list)
    fx_variation_pct: Assumption
    freight_variation_pct: Assumption
    bcd_low_pct: Assumption
    bcd_high_pct: Assumption
    default_freight_low_inr: Assumption
    default_freight_high_inr: Assumption

    # Required in the input but kept out of model_fields; exposed as read-only properties.
    _version: str = PrivateAttr(default="")
    _effective_date: str = PrivateAttr(default="")

    @model_validator(mode="wrap")
    @classmethod
    def _metadata(cls, data: Any, handler: Any) -> "CostAssumptions":
        if not isinstance(data, dict):
            return handler(data)
        data = dict(data)
        version = data.pop("version", None)
        effective_date = data.pop("effective_date", None)
        if not isinstance(version, str) or not version.strip():
            raise ValueError("version is required and must be a non-empty string")
        if not isinstance(effective_date, str):
            raise ValueError("effective_date is required and must be an ISO date string (YYYY-MM-DD)")
        parse_as_of(effective_date)
        obj = handler(data)
        obj._version = version
        obj._effective_date = effective_date
        return obj

    @property
    def version(self) -> str:
        return self._version

    @property
    def effective_date(self) -> str:
        return self._effective_date

    @model_validator(mode="after")
    def _check(self) -> "CostAssumptions":
        for name in _PERCENT_FIELDS:
            if getattr(self, name).value > 100:
                raise ValueError(f"{name} must not exceed 100")
        if self.fx_usd_inr.value <= 0:
            raise ValueError("fx_usd_inr must be greater than 0")
        if self.bcd_low_pct.value > self.bcd_high_pct.value:
            raise ValueError("bcd_low_pct must be <= bcd_high_pct")
        if self.default_freight_low_inr.value > self.default_freight_high_inr.value:
            raise ValueError("default_freight_low_inr must be <= default_freight_high_inr")
        for name in type(self).model_fields:
            if name != "other_duties" and name not in RANGE_FIELDS and getattr(self, name).range_low is not None:
                raise ValueError(f"{name} does not support range_low/range_high")
        return self

    def all_verified(self) -> bool:
        """True only if every assumption (including other duties) is marked verified."""
        entries = [getattr(self, name) for name in type(self).model_fields if name != "other_duties"]
        return all(e.verified for e in entries) and all(d.verified for d in self.other_duties)

    def verified_counts(self) -> Tuple[int, int]:
        """(verified, total) over every assumption, including other duties; same basis as all_verified()."""
        entries = [getattr(self, name) for name in type(self).model_fields if name != "other_duties"]
        entries.extend(self.other_duties)
        return sum(1 for e in entries if e.verified), len(entries)


def _num(value: Any) -> Any:
    """YAML numbers load as float; convert via str so 0.1 becomes exactly Decimal('0.1')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return value


def _prepare_assumption(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    out = dict(item)
    if "value" in out:
        out["value"] = _num(out["value"])
    for key in ("range_low", "range_high"):
        if key in out:
            out[key] = _num(out[key])
    if "as_of" in out:
        out["as_of"] = str(out["as_of"])
    return out


def _prepare_duty(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    out = dict(item)
    if "rate_pct" in out:
        out["rate_pct"] = _num(out["rate_pct"])
    if "as_of" in out:
        out["as_of"] = str(out["as_of"])
    return out


def parse_cost_assumptions(raw: Any) -> CostAssumptions:
    """Convert numeric config values to Decimal(str(v)), then validate."""
    if not isinstance(raw, dict):
        raise ValueError("cost assumptions config must be a mapping")
    prepared = {}
    for key, item in raw.items():
        if key == "other_duties":
            prepared[key] = [_prepare_duty(d) for d in (item or [])]
        elif key == "version":
            prepared[key] = item
        elif key == "effective_date":
            prepared[key] = str(item) if isinstance(item, date) else item
        else:
            prepared[key] = _prepare_assumption(item)
    return CostAssumptions.model_validate(prepared)


def load_cost_assumptions(path: Union[str, Path, None] = None) -> CostAssumptions:
    cfg_path = Path(path) if path is not None else DEFAULT_COST_PATH
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_cost_assumptions(raw)
