"""Cost assumptions model and loader. Rates are Decimal, never float; values live in cost_assumptions.yaml."""
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, List, Literal, Union

import yaml
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

DEFAULT_COST_PATH = Path(__file__).resolve().parent / "cost_assumptions.yaml"


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
        return self

    def all_verified(self) -> bool:
        """True only if every assumption (including other duties) is marked verified."""
        entries = [getattr(self, name) for name in type(self).model_fields if name != "other_duties"]
        return all(e.verified for e in entries) and all(d.verified for d in self.other_duties)


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
        else:
            prepared[key] = _prepare_assumption(item)
    return CostAssumptions.model_validate(prepared)


def load_cost_assumptions(path: Union[str, Path, None] = None) -> CostAssumptions:
    cfg_path = Path(path) if path is not None else DEFAULT_COST_PATH
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_cost_assumptions(raw)
