import ast
import socket
from decimal import Decimal, getcontext, localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.decision import cost_engine
from app.decision.cost_config import (
    Assumption,
    CostAssumptions,
    load_cost_assumptions,
    parse_cost_assumptions,
)
from app.decision.cost_engine import (
    LABEL,
    CostInputs,
    CostOverrides,
    UnsupportedCurrencyError,
    estimate_cost,
)

D = Decimal


@pytest.fixture()
def assumptions() -> CostAssumptions:
    return load_cost_assumptions()


def golden_inputs(**kw):
    base = dict(unit_price=D("10"), price_currency="USD", quantity=100, freight_inr=D("12000"), insurance_inr=D("0"))
    base.update(kw)
    return CostInputs(**base)


def raw_config():
    """Raw YAML-shaped dict with plain (non-Decimal) numbers."""
    import yaml
    with open(cost_engine.__file__.replace("cost_engine.py", "cost_assumptions.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def by_label(est, label):
    return next(line for line in est.breakdown if line.label == label)


# ---- golden case -------------------------------------------------------------------------------

def test_golden_case(assumptions):
    est = estimate_cost(golden_inputs(), assumptions)
    assert by_label(est, "goods_value").amount == D("90000.00")
    assert by_label(est, "cif").amount == D("102000.00")
    assert by_label(est, "landing_charge_notional").amount == D("1020.00")
    assert by_label(est, "assessable_value").amount == D("103020.00")
    assert by_label(est, "bcd").amount == D("20604.00")
    assert by_label(est, "sws").amount == D("2060.40")
    assert by_label(est, "igst").amount == D("22623.19")
    assert by_label(est, "duties_and_taxes").amount == D("45287.59")
    non_duty = sum(by_label(est, n).amount for n in
                   ("clearing", "port_cfs", "domestic_transport", "certification_testing"))
    assert non_duty == D("7000.00")
    assert est.expected == D("154287.59")
    assert est.per_unit_expected == D("1542.88")
    assert est.label == LABEL


def test_golden_unrounded_intermediates(assumptions):
    with localcontext() as ctx:
        ctx.prec = 28
        c = cost_engine._compute(
            D("10"), 100, D("90"), D("12000"), D("0"), D("0"), D("1"), D("20"), D("10"), D("18"), [],
            [("a", D("3000")), ("b", D("2000")), ("c", D("2000")), ("d", D("0"))],
        )
    assert c.igst == D("22623.192")
    assert c.duties_and_taxes == D("45287.592")
    assert c.landed == D("154287.592")


def test_landing_charge_is_notional_not_in_landed(assumptions):
    est = estimate_cost(golden_inputs(), assumptions)
    # landed = goods + freight + insurance + duties/taxes + non-duty, with no landing charge added
    expected = D("90000") + D("12000") + D("0") + D("45287.592") + D("7000")
    assert est.expected == expected.quantize(D("0.01"))
    assert by_label(est, "landing_charge_notional").kind == "notional"


# ---- missing freight / insurance ---------------------------------------------------------------

def test_missing_freight_gives_range_and_assumption(assumptions):
    est = estimate_cost(golden_inputs(freight_inr=None), assumptions)
    names = [e.name for e in est.assumptions]
    assert "freight_inr" in names
    assert "default_freight_low_inr" in names and "default_freight_high_inr" in names
    entry = next(e for e in est.assumptions if e.name == "freight_inr")
    assert entry.value == D("12500")  # midpoint of 5000..20000
    assert entry.verified is False
    assert est.low < est.expected < est.high
    assert by_label(est, "freight").amount == D("12500.00")


def test_missing_insurance_uses_pct_with_assumption(assumptions):
    est = estimate_cost(golden_inputs(insurance_inr=None), assumptions)
    assert any(e.name == "insurance_inr" for e in est.assumptions)
    assert any(e.name == "insurance_pct_of_goods" for e in est.assumptions)
    assert by_label(est, "insurance").amount == D("0.00")


def test_supplied_freight_does_not_add_default_entries(assumptions):
    est = estimate_cost(golden_inputs(), assumptions)
    names = [e.name for e in est.assumptions]
    assert "freight_inr" not in names and "default_freight_low_inr" not in names


# ---- INR price ---------------------------------------------------------------------------------

def test_inr_price_uses_fx_one_and_no_fx_assumption(assumptions):
    est = estimate_cost(golden_inputs(unit_price=D("900"), price_currency="INR"), assumptions)
    assert by_label(est, "goods_value").amount == D("90000.00")
    assert est.expected == D("154287.59")
    assert "fx_usd_inr" not in [e.name for e in est.assumptions]


# ---- input validation --------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("unit_price", D("-1")), ("quantity", 0), ("quantity", -3), ("freight_inr", D("-5")), ("insurance_inr", D("-5")),
])
def test_negative_or_invalid_inputs_rejected(field, value):
    with pytest.raises(ValidationError):
        golden_inputs(**{field: value})


@pytest.mark.parametrize("currency", ["EUR", "CNY", "", "usdt"])
def test_unsupported_currency_rejected(assumptions, currency):
    with pytest.raises(UnsupportedCurrencyError):
        estimate_cost(golden_inputs(price_currency=currency), assumptions)


def test_currency_case_insensitive(assumptions):
    assert estimate_cost(golden_inputs(price_currency="usd"), assumptions).expected == D("154287.59")


@pytest.mark.parametrize("field", ["unit_price", "freight_inr", "insurance_inr"])
def test_float_inputs_rejected(field):
    with pytest.raises(ValidationError):
        golden_inputs(**{field: 10.5})


def test_float_quantity_rejected():
    with pytest.raises(ValidationError):
        golden_inputs(quantity=100.0)


def test_int_and_str_inputs_accepted(assumptions):
    inp = CostInputs(unit_price="10", price_currency="USD", quantity=100, freight_inr=12000, insurance_inr="0")
    assert estimate_cost(inp, assumptions).expected == D("154287.59")


def test_float_override_rejected():
    with pytest.raises(ValidationError):
        CostOverrides(bcd_pct=20.5)


def test_override_pct_above_100_rejected():
    with pytest.raises(ValidationError):
        CostOverrides(bcd_pct=D("101"))


# ---- outputs -----------------------------------------------------------------------------------

def test_all_outputs_are_decimal(assumptions):
    est = estimate_cost(golden_inputs(), assumptions)
    for name in ("low", "expected", "high", "per_unit_low", "per_unit_expected", "per_unit_high"):
        assert type(getattr(est, name)) is D
    for line in est.breakdown:
        assert type(line.amount) is D
        assert line.base is None or type(line.base) is D
        assert line.rate_pct is None or type(line.rate_pct) is D
    for entry in est.assumptions:
        assert entry.value is None or type(entry.value) is D


@pytest.mark.parametrize("kw", [{}, {"freight_inr": None}, {"price_currency": "INR"}])
def test_label_always_present(assumptions, kw):
    assert estimate_cost(golden_inputs(**kw), assumptions).label == LABEL


def test_deterministic(assumptions):
    a = estimate_cost(golden_inputs(freight_inr=None), assumptions)
    b = estimate_cost(golden_inputs(freight_inr=None), assumptions)
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


@pytest.mark.parametrize("kw", [{}, {"freight_inr": None}, {"price_currency": "INR", "unit_price": D("900")}])
def test_low_le_expected_le_high(assumptions, kw):
    est = estimate_cost(golden_inputs(**kw), assumptions)
    assert est.low <= est.expected <= est.high
    assert est.per_unit_low <= est.per_unit_expected <= est.per_unit_high


def test_range_widens_with_variation(assumptions):
    est = estimate_cost(golden_inputs(), assumptions)
    assert est.low < est.expected < est.high


def test_no_forbidden_words_in_output(assumptions):
    est = estimate_cost(golden_inputs(freight_inr=None), assumptions)
    text = est.model_dump_json().lower()
    assert "fraud" not in text and "fake" not in text


# ---- verified / override semantics -------------------------------------------------------------

def test_placeholders_are_unverified(assumptions):
    assert assumptions.all_verified() is False
    assert estimate_cost(golden_inputs(), assumptions).unverified_assumptions is True


def _all_verified(a: CostAssumptions) -> CostAssumptions:
    update = {}
    for name in type(a).model_fields:
        if name == "other_duties":
            continue
        update[name] = getattr(a, name).model_copy(update={"verified": True})
    return a.model_copy(update=update)


def test_override_never_clears_unverified_flag(assumptions):
    verified = _all_verified(assumptions)
    assert verified.all_verified() is True
    # baseline: every config assumption verified. The landing-charge treatment stays unverified.
    baseline = estimate_cost(golden_inputs(), verified)
    assert baseline.rates_verified is True
    assert baseline.methodology_unverified is True  # landing charge, SWS and IGST bases are "to verify"
    assert baseline.unverified_assumptions is True  # never clears
    ov = CostOverrides(bcd_pct=D("25"))
    est = estimate_cost(golden_inputs(overrides=ov), assumptions)
    assert est.unverified_assumptions is True
    # an override on fully verified rates also clears rates_verified
    overridden = estimate_cost(golden_inputs(overrides=ov), verified)
    assert overridden.rates_verified is False
    assert overridden.unverified_assumptions is True
    entry = next(e for e in est.assumptions if e.name == "bcd_pct")
    assert entry.source == "user override"
    assert entry.verified is False
    assert entry.user_supplied is True
    assert entry.value == D("25")


def test_split_flags_for_placeholders(assumptions):
    est = estimate_cost(golden_inputs(), assumptions)
    assert est.rates_verified is False
    assert est.methodology_unverified is True
    assert est.unverified_assumptions is True
    names = {e.name for e in est.assumptions}
    assert set(cost_engine.METHODOLOGY_TO_VERIFY) <= names
    assert {"landing_charge_treatment", "sws_base", "igst_base"} <= names


def test_missing_freight_rates_verified_follows_config(assumptions):
    est = estimate_cost(golden_inputs(freight_inr=None), _all_verified(assumptions))
    assert est.rates_verified is True  # default freight range entries are verified in this config
    placeholder = estimate_cost(golden_inputs(freight_inr=None), assumptions)
    assert placeholder.rates_verified is False


def test_breakdown_note_always_present(assumptions):
    for kw in ({}, {"freight_inr": None}, {"price_currency": "INR", "unit_price": D("900")}):
        est = estimate_cost(golden_inputs(**kw), assumptions)
        assert "use the engine total" in est.breakdown_note
        assert "cent" in est.breakdown_note


def test_override_applies_to_calculation(assumptions):
    est = estimate_cost(golden_inputs(overrides=CostOverrides(bcd_pct=D("10"))), assumptions)
    assert by_label(est, "bcd").amount == D("10302.00")


def test_override_does_not_mark_config_entries_user_supplied(assumptions):
    est = estimate_cost(golden_inputs(overrides=CostOverrides(bcd_pct=D("25"))), assumptions)
    others = [e for e in est.assumptions if e.name != "bcd_pct"]
    assert all(not e.user_supplied for e in others)


# ---- config boundary ---------------------------------------------------------------------------

def test_yaml_loads_with_expected_placeholders(assumptions):
    assert assumptions.fx_usd_inr.value == D("90")
    assert assumptions.bcd_pct.value == D("20")
    assert assumptions.other_duties == []
    for name in type(assumptions).model_fields:
        if name == "other_duties":
            continue
        entry = getattr(assumptions, name)
        assert entry.verified is False
        assert entry.owner == "TBD"
        assert entry.source == "placeholder - not verified"
        assert isinstance(entry.as_of, str)


def test_loaded_config_contains_no_float(assumptions):
    for name in type(assumptions).model_fields:
        if name == "other_duties":
            continue
        assert type(getattr(assumptions, name).value) is D


def test_loader_converts_float_via_str():
    raw = raw_config()
    raw["igst_pct"]["value"] = 0.1
    cfg = parse_cost_assumptions(raw)
    assert cfg.igst_pct.value == D("0.1")
    assert cfg.igst_pct.value != D(0.1)


def test_float_passed_to_config_model_rejected():
    with pytest.raises(ValidationError):
        Assumption(value=0.1, source="s", as_of="2026-10-24", verified=False)


def test_as_of_coerced_to_string():
    import datetime
    raw = raw_config()
    raw["bcd_pct"]["as_of"] = datetime.date(2026, 10, 24)
    assert parse_cost_assumptions(raw).bcd_pct.as_of == "2026-10-24"


def test_empty_other_duties_is_empty_list():
    raw = raw_config()
    raw["other_duties"] = []
    assert parse_cost_assumptions(raw).other_duties == []
    raw["other_duties"] = None
    assert parse_cost_assumptions(raw).other_duties == []


def test_other_duties_converted_and_applied(assumptions):
    raw = raw_config()
    raw["other_duties"] = [{"label": "extra", "rate_pct": 5, "base": "assessable_value", "source": "s",
                            "as_of": "2026-10-24", "verified": False}]
    cfg = parse_cost_assumptions(raw)
    assert cfg.other_duties[0].rate_pct == D("5")
    est = estimate_cost(golden_inputs(), cfg)
    assert by_label(est, "other_duty:extra").amount == D("5151.00")
    # IGST base now includes the other duty: 18% x (103020 + 20604 + 2060.40 + 5151)
    assert by_label(est, "igst").base == D("130835.40")
    assert by_label(est, "igst").amount == D("23550.37")  # 23550.372 before rounding


def test_negative_config_value_rejected():
    raw = raw_config()
    raw["clearing_inr"]["value"] = -1
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


@pytest.mark.parametrize("name", ["bcd_pct", "igst_pct", "landing_charge_pct", "fx_variation_pct"])
def test_percentage_above_100_rejected(name):
    raw = raw_config()
    raw[name]["value"] = 101
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


def test_zero_fx_rejected():
    raw = raw_config()
    raw["fx_usd_inr"]["value"] = 0
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


def test_inverted_ranges_rejected():
    raw = raw_config()
    raw["bcd_low_pct"]["value"] = 40
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)
    raw = raw_config()
    raw["default_freight_low_inr"]["value"] = 99999
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


def test_unknown_config_key_rejected():
    raw = raw_config()
    raw["mystery"] = {"value": 1, "source": "s", "as_of": "x", "verified": False}
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


# ---- purity ------------------------------------------------------------------------------------

BANNED_IMPORTS = {"time", "datetime", "random", "socket", "requests", "httpx"}


def test_engine_imports_no_clock_random_or_network_modules():
    tree = ast.parse(Path(cost_engine.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(BANNED_IMPORTS), imported & BANNED_IMPORTS


def test_estimate_cost_opens_no_sockets(assumptions, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", boom)
    assert estimate_cost(golden_inputs(freight_inr=None), assumptions).expected > 0


# ---- decimal context ---------------------------------------------------------------------------

def test_global_decimal_precision_does_not_change_result(assumptions):
    reference = estimate_cost(golden_inputs(freight_inr=None), assumptions)
    for prec in (4, 9, 60):
        with localcontext() as ctx:
            ctx.prec = prec
            result = estimate_cost(golden_inputs(freight_inr=None), assumptions)
        assert result == reference
    assert getcontext().prec == 28  # the caller's context is untouched
