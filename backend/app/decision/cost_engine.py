from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Dict, List, NamedTuple, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.decision.cost_config import CostAssumptions, Date, DecimalIn, parse_as_of
from app.decision.rates.provenance import EvidenceKind, Provenance

LABEL = "Illustrative estimate, not a quote."
BREAKDOWN_NOTE = (
    "Line figures are rounded individually and may differ by a cent from the total; "
    "use the engine total (low, expected, high), not the sum of the lines."
)
# Methodology choices still marked "to verify" in docs/decisions.md section 5. Flip a name out of
# this set only after someone checks it against an official source.
METHODOLOGY_TO_VERIFY = {
    "landing_charge_treatment": (
        "Landing charge is a notional addition to the assessable value only; it is not added to landed cost."
    ),
    "sws_base": "SWS is charged on BCD.",
    "igst_base": "IGST is charged on assessable value + BCD + SWS + other duties.",
}
# Derived entries inherit staleness from the config entries they are built from.
DERIVED_FROM = {
    "freight_inr": ("default_freight_low_inr", "default_freight_high_inr"),
    "insurance_inr": ("insurance_pct_of_goods",),
}
SUPPORTED_CURRENCIES = ("USD", "INR")
PRECISION = 28
_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_ONE = Decimal(1)
_TWO = Decimal(2)


class UnsupportedCurrencyError(ValueError):
    """Raised for any price currency other than USD or INR."""


class CostOverrides(BaseModel):
    """User overrides of assumption values. Recorded as unverified, user-supplied assumptions."""

    model_config = ConfigDict(extra="forbid")

    fx_usd_inr: Optional[DecimalIn] = Field(default=None, gt=0)
    landing_charge_pct: Optional[DecimalIn] = Field(default=None, ge=0, le=100)
    bcd_pct: Optional[DecimalIn] = Field(default=None, ge=0, le=100)
    sws_pct_of_bcd: Optional[DecimalIn] = Field(default=None, ge=0, le=100)
    igst_pct: Optional[DecimalIn] = Field(default=None, ge=0, le=100)
    insurance_pct_of_goods: Optional[DecimalIn] = Field(default=None, ge=0, le=100)
    clearing_inr: Optional[DecimalIn] = Field(default=None, ge=0)
    port_cfs_inr: Optional[DecimalIn] = Field(default=None, ge=0)
    domestic_transport_inr: Optional[DecimalIn] = Field(default=None, ge=0)
    certification_inr: Optional[DecimalIn] = Field(default=None, ge=0)


class CostInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_price: DecimalIn = Field(ge=0)
    price_currency: str
    quantity: StrictInt = Field(ge=1)
    freight_inr: Optional[DecimalIn] = Field(default=None, ge=0)
    insurance_inr: Optional[DecimalIn] = Field(default=None, ge=0)
    overrides: Optional[CostOverrides] = None


class CostLine(BaseModel):
    label: str
    kind: str  # component | subtotal | notional | total
    base: Optional[Decimal] = None
    rate_pct: Optional[Decimal] = None
    amount: Decimal


class AssumptionEntry(BaseModel):
    name: str
    value: Optional[Decimal] = None
    source: str
    as_of: Optional[str] = None
    verified: bool
    user_supplied: bool = False
    owner: Optional[str] = None
    note: Optional[str] = None
    stale: Optional[bool] = None
    age_days: Optional[int] = None
    max_age_days: Optional[int] = None
    # None for entries that are not config rates (user overrides, methodology notes).
    provenance: Optional[Provenance] = Provenance.placeholder
    evidence_kind: Optional[EvidenceKind] = None


class CostEstimate(BaseModel):
    label: str
    currency: str
    quantity: int
    breakdown: List[CostLine]
    assumptions: List[AssumptionEntry]
    low: Decimal
    expected: Decimal
    high: Decimal
    per_unit_low: Decimal
    per_unit_expected: Decimal
    per_unit_high: Decimal
    breakdown_note: str
    rates_verified: bool
    methodology_unverified: bool
    unverified_assumptions: bool
    any_stale: bool
    staleness_checked: bool
    assumptions_version: str
    assumptions_effective_date: str
    any_human_approved: bool
    rates_verified_count: int
    rates_total: int


class _Calc(NamedTuple):
    goods: Decimal
    freight: Decimal
    insurance: Decimal
    cif: Decimal
    landing: Decimal
    assessable: Decimal
    bcd: Decimal
    sws: Decimal
    other: List[Tuple[str, Decimal, Decimal, Decimal]]  # label, rate_pct, base, amount
    other_total: Decimal
    igst_base: Decimal
    igst: Decimal
    duties_and_taxes: Decimal
    non_duty: List[Tuple[str, Decimal]]
    non_duty_total: Decimal
    landed: Decimal


def _pct(rate: Decimal, base: Decimal) -> Decimal:
    return base * rate / _HUNDRED


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _compute(
    unit_price: Decimal,
    quantity: int,
    fx: Decimal,
    freight: Decimal,
    insurance_inr: Optional[Decimal],
    insurance_pct: Decimal,
    landing_pct: Decimal,
    bcd_pct: Decimal,
    sws_pct: Decimal,
    igst_pct: Decimal,
    duties: List[Tuple[str, Decimal, str]],
    non_duty: List[Tuple[str, Decimal]],
) -> _Calc:
    goods = unit_price * quantity * fx
    insurance = insurance_inr if insurance_inr is not None else _pct(insurance_pct, goods)
    cif = goods + freight + insurance
    landing = _pct(landing_pct, cif)
    assessable = cif + landing
    bcd = _pct(bcd_pct, assessable)
    sws = _pct(sws_pct, bcd)
    bases = {"cif": cif, "assessable_value": assessable, "bcd": bcd}
    other = []
    for label, rate, base_name in duties:
        base = bases[base_name]
        other.append((label, rate, base, _pct(rate, base)))
    other_total = sum((o[3] for o in other), Decimal(0))
    igst_base = assessable + bcd + sws + other_total
    igst = _pct(igst_pct, igst_base)
    duties_and_taxes = bcd + sws + other_total + igst
    non_duty_total = sum((amount for _, amount in non_duty), Decimal(0))
    landed = goods + freight + insurance + duties_and_taxes + non_duty_total
    return _Calc(goods, freight, insurance, cif, landing, assessable, bcd, sws, other, other_total,
                 igst_base, igst, duties_and_taxes, non_duty, non_duty_total, landed)


def _join_note(note: Optional[str], sentence: Optional[str]) -> Optional[str]:
    if not sentence:
        return note
    if not note:
        return sentence
    return note.rstrip(".") + ". " + sentence


def _staleness(as_of: str, max_age_days: Optional[int], today: Date) -> Tuple[Optional[bool], Optional[int], Optional[str]]:
    """Return (stale, age_days, note sentence). At exactly max_age_days the entry is not stale."""
    if max_age_days is None:
        return None, None, "No expiry set, staleness not checked."
    age = (today - parse_as_of(as_of)).days
    if age < 0:
        return False, age, f"The as_of date {as_of} is in the future."
    if age > max_age_days:
        return True, age, f"Last checked {as_of}, older than {max_age_days} days."
    return False, age, None


def _apply_staleness(
    entries: List[AssumptionEntry], checked: Dict[str, Tuple[str, Optional[int]]], today: Date
) -> List[AssumptionEntry]:
    """Annotate config-derived entries. Overrides and methodology entries keep stale=None."""
    status: Dict[str, Optional[bool]] = {}
    out = []
    for e in entries:
        if not e.user_supplied and e.name in checked:
            as_of, max_age = checked[e.name]
            stale, age, sentence = _staleness(as_of, max_age, today)
            status[e.name] = stale
            e = e.model_copy(update={"stale": stale, "age_days": age, "max_age_days": max_age,
                                     "note": _join_note(e.note, sentence)})
        out.append(e)
    result = []
    for e in out:
        if e.name in DERIVED_FROM:
            sources = [s for s in DERIVED_FROM[e.name] if s in status and status[s] is not None]
            if sources:
                stale_sources = [s for s in sources if status[s]]
                sentence = ("Derived from a stale entry: " + ", ".join(stale_sources) + ".") if stale_sources else None
                e = e.model_copy(update={"stale": bool(stale_sources), "note": _join_note(e.note, sentence)})
        result.append(e)
    return result


def estimate_cost(inputs: CostInputs, assumptions: CostAssumptions, today: Optional[Date] = None) -> CostEstimate:
    """today is supplied by the caller; the engine never reads the clock. None skips staleness checks."""
    # type() rather than isinstance(): datetime is a subclass of date and must be rejected.
    if today is not None and type(today) is not Date:
        raise TypeError(f"today must be a datetime.date (not a datetime), got {type(today).__name__}")
    currency = inputs.price_currency.strip().upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(
            f"unsupported price currency {inputs.price_currency!r}; supported: {', '.join(SUPPORTED_CURRENCIES)}"
        )
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return _estimate(inputs, assumptions, currency, today)


def _estimate(inputs: CostInputs, a: CostAssumptions, currency: str, today: Optional[Date]) -> CostEstimate:
    ov = inputs.overrides or CostOverrides()
    entries: List[AssumptionEntry] = []
    checked: Dict[str, Tuple[str, Optional[int]]] = {}  # config-derived entry name -> (as_of, max_age_days)

    def use(name: str) -> Decimal:
        override = getattr(ov, name, None)
        if override is not None:
            entries.append(AssumptionEntry(
                name=name, value=override, source="user override", verified=False, user_supplied=True,
                note="Supplied by the user; not checked against an official source.", provenance=None,
            ))
            return override
        cfg = getattr(a, name)
        checked[name] = (cfg.as_of, cfg.max_age_days)
        entries.append(AssumptionEntry(
            name=name, value=cfg.value, source=cfg.source, as_of=cfg.as_of, verified=cfg.verified, owner=cfg.owner,
            note=cfg.evidence_note, provenance=cfg.provenance, evidence_kind=cfg.evidence_kind,
        ))
        return cfg.value

    def use_range(name: str) -> Tuple[Decimal, Decimal, Decimal]:
        """(expected, low, high). A config range applies only when both bounds are set and not overridden."""
        value = use(name)
        cfg = getattr(a, name)
        if getattr(ov, name, None) is None and cfg.range_low is not None and cfg.range_high is not None:
            sentence = f"Range used for low/high: {cfg.range_low} to {cfg.range_high}."
            entries[-1] = entries[-1].model_copy(update={"note": _join_note(entries[-1].note, sentence)})
            return value, cfg.range_low, cfg.range_high
        return value, value, value

    # FX
    if currency == "USD":
        fx = use("fx_usd_inr")
        fx_var = use("fx_variation_pct")
        fx_low = fx * (_ONE - fx_var / _HUNDRED)
        fx_high = fx * (_ONE + fx_var / _HUNDRED)
    else:
        fx = fx_low = fx_high = _ONE

    # Freight
    if inputs.freight_inr is not None:
        freight = inputs.freight_inr
        freight_var = use("freight_variation_pct")
        freight_low = freight * (_ONE - freight_var / _HUNDRED)
        freight_high = freight * (_ONE + freight_var / _HUNDRED)
    else:
        freight_low = use("default_freight_low_inr")
        freight_high = use("default_freight_high_inr")
        freight = (freight_low + freight_high) / _TWO
        lo_cfg, hi_cfg = a.default_freight_low_inr, a.default_freight_high_inr
        both_approved = lo_cfg.provenance == hi_cfg.provenance == Provenance.human_approved
        entries.append(AssumptionEntry(
            name="freight_inr", value=freight, source="default freight range (config)",
            verified=a.default_freight_low_inr.verified and a.default_freight_high_inr.verified,
            note="Freight not supplied; the labelled default range was used and expected is its midpoint.",
            provenance=Provenance.human_approved if both_approved else Provenance.placeholder,
            evidence_kind=lo_cfg.evidence_kind if lo_cfg.evidence_kind == hi_cfg.evidence_kind else None,
        ))

    # Insurance
    insurance_inr = inputs.insurance_inr
    insurance_pct = Decimal(0)
    insurance_fallback_verified = True
    insurance_provenance: Optional[Provenance] = Provenance.placeholder
    insurance_evidence: Optional[EvidenceKind] = None
    if insurance_inr is None:
        insurance_pct = use("insurance_pct_of_goods")
        insurance_fallback_verified = entries[-1].verified
        insurance_provenance, insurance_evidence = entries[-1].provenance, entries[-1].evidence_kind

    landing_pct = use("landing_charge_pct")
    bcd = use("bcd_pct")
    bcd_low = min(use("bcd_low_pct"), bcd)
    bcd_high = max(use("bcd_high_pct"), bcd)
    sws_pct = use("sws_pct_of_bcd")
    igst_pct = use("igst_pct")
    non_duty_ranges = [
        ("clearing", use_range("clearing_inr")),
        ("port_cfs", use_range("port_cfs_inr")),
        ("domestic_transport", use_range("domestic_transport_inr")),
        ("certification_testing", use_range("certification_inr")),
    ]
    non_duty = [(label, value) for label, (value, _, _) in non_duty_ranges]
    non_duty_low = [(label, low_v) for label, (_, low_v, _) in non_duty_ranges]
    non_duty_high = [(label, high_v) for label, (_, _, high_v) in non_duty_ranges]
    duties = []
    for d in a.other_duties:
        duties.append((d.label, d.rate_pct, d.base))
        checked["other_duty:" + d.label] = (d.as_of, d.max_age_days)
        entries.append(AssumptionEntry(
            name="other_duty:" + d.label, value=d.rate_pct, source=d.source, as_of=d.as_of,
            verified=d.verified, owner=d.owner, note="Charged on base: " + d.base,
        ))
    for name, note in METHODOLOGY_TO_VERIFY.items():
        entries.append(AssumptionEntry(
            name=name, source="docs/decisions.md section 5 (to verify)", verified=False, note=note, provenance=None,
        ))

    def run(fx_v: Decimal, freight_v: Decimal, bcd_v: Decimal, nd: List[Tuple[str, Decimal]]) -> _Calc:
        return _compute(inputs.unit_price, inputs.quantity, fx_v, freight_v, insurance_inr, insurance_pct,
                        landing_pct, bcd_v, sws_pct, igst_pct, duties, nd)

    exp = run(fx, freight, bcd, non_duty)
    low = run(fx_low, freight_low, bcd_low, non_duty_low)
    high = run(fx_high, freight_high, bcd_high, non_duty_high)

    if insurance_inr is None:
        entries.append(AssumptionEntry(
            name="insurance_inr", value=exp.insurance, source="insurance_pct_of_goods x goods value (config)",
            verified=insurance_fallback_verified,
            note="Insurance not supplied; calculated from the percentage assumption.",
            provenance=insurance_provenance, evidence_kind=insurance_evidence,
        ))

    # Overrides and derived defaults are unverified, so they also clear rates_verified.
    rates_verified = a.all_verified() and all(e.verified for e in entries if e.name not in METHODOLOGY_TO_VERIFY)
    methodology_unverified = any(not e.verified for e in entries if e.name in METHODOLOGY_TO_VERIFY)
    # Staleness only annotates entries; it never feeds amounts or the verified flags above.
    if today is not None:
        entries = _apply_staleness(entries, checked, today)

    rates_verified_count, rates_total = a.verified_counts()

    qty = Decimal(inputs.quantity)
    breakdown = [
        CostLine(label="goods_value", kind="component", base=_q(exp.goods), amount=_q(exp.goods)),
        CostLine(label="freight", kind="component", amount=_q(exp.freight)),
        CostLine(label="insurance", kind="component", amount=_q(exp.insurance)),
        CostLine(label="cif", kind="subtotal", amount=_q(exp.cif)),
        CostLine(label="landing_charge_notional", kind="notional", base=_q(exp.cif),
                 rate_pct=landing_pct, amount=_q(exp.landing)),
        CostLine(label="assessable_value", kind="subtotal", amount=_q(exp.assessable)),
        CostLine(label="bcd", kind="component", base=_q(exp.assessable), rate_pct=bcd, amount=_q(exp.bcd)),
        CostLine(label="sws", kind="component", base=_q(exp.bcd), rate_pct=sws_pct, amount=_q(exp.sws)),
    ]
    for label, rate, base, amount in exp.other:
        breakdown.append(CostLine(label="other_duty:" + label, kind="component", base=_q(base),
                                  rate_pct=rate, amount=_q(amount)))
    breakdown.append(CostLine(label="igst", kind="component", base=_q(exp.igst_base),
                              rate_pct=igst_pct, amount=_q(exp.igst)))
    breakdown.append(CostLine(label="duties_and_taxes", kind="subtotal", amount=_q(exp.duties_and_taxes)))
    for label, amount in exp.non_duty:
        breakdown.append(CostLine(label=label, kind="component", amount=_q(amount)))
    breakdown.append(CostLine(label="landed_cost", kind="total", amount=_q(exp.landed)))

    return CostEstimate(
        label=LABEL,
        currency="INR",
        quantity=inputs.quantity,
        breakdown=breakdown,
        assumptions=entries,
        low=_q(low.landed),
        expected=_q(exp.landed),
        high=_q(high.landed),
        per_unit_low=_q(low.landed / qty),
        per_unit_expected=_q(exp.landed / qty),
        per_unit_high=_q(high.landed / qty),
        breakdown_note=BREAKDOWN_NOTE,
        rates_verified=rates_verified,
        methodology_unverified=methodology_unverified,
        unverified_assumptions=any(not e.verified for e in entries),
        any_stale=any(e.stale is True for e in entries),
        staleness_checked=today is not None,
        assumptions_version=a.version,
        assumptions_effective_date=a.effective_date,
        any_human_approved=any(e.provenance == Provenance.human_approved for e in entries),
        rates_verified_count=rates_verified_count,
        rates_total=rates_total,
    )
