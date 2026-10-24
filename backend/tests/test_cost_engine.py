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


# ---- staleness and versioning (Step 2 follow-up) -----------------------------------------------

import datetime as _dt  # noqa: E402

from app.decision.cost_config import parse_as_of  # noqa: E402

AS_OF = _dt.date(2026, 10, 24)  # as_of of every placeholder entry


def _days(n):
    return AS_OF + _dt.timedelta(days=n)


def _entry(est, name):
    return next(e for e in est.assumptions if e.name == name)


def _with_as_of(**changes):
    raw = raw_config()
    for name, as_of in changes.items():
        raw[name]["as_of"] = as_of
    return parse_cost_assumptions(raw)


def _config_entries(est):
    skip = set(cost_engine.METHODOLOGY_TO_VERIFY) | set(cost_engine.DERIVED_FROM)
    return [e for e in est.assumptions if not e.user_supplied and e.name not in skip]


def test_fresh_entries_not_stale(assumptions):
    est = estimate_cost(golden_inputs(), assumptions, today=_days(3))
    assert est.staleness_checked is True
    assert est.any_stale is False
    for e in _config_entries(est):
        assert e.stale is False
        assert e.age_days == 3
        assert e.max_age_days is not None


def test_exactly_at_limit_not_stale_one_day_over_stale(assumptions):
    at_limit = estimate_cost(golden_inputs(), assumptions, today=_days(20))
    fx = _entry(at_limit, "fx_usd_inr")
    assert (fx.stale, fx.age_days, fx.max_age_days) == (False, 20, 20)
    assert at_limit.any_stale is False
    over = estimate_cost(golden_inputs(), assumptions, today=_days(21))
    fx = _entry(over, "fx_usd_inr")
    assert (fx.stale, fx.age_days) == (True, 21)
    assert "Last checked 2026-10-24, older than 20 days" in fx.note
    assert over.any_stale is True


def test_fx_stale_while_duty_rates_fresh():
    cfg = _with_as_of(fx_usd_inr="2026-09-01")
    est = estimate_cost(golden_inputs(), cfg, today=_days(1))
    stale = {e.name for e in est.assumptions if e.stale is True}
    assert stale == {"fx_usd_inr"}
    for name in ("bcd_pct", "sws_pct_of_bcd", "igst_pct"):
        assert _entry(est, name).stale is False
    assert est.any_stale is True


def test_today_none_skips_staleness(assumptions):
    est = estimate_cost(golden_inputs(freight_inr=None, insurance_inr=None), assumptions)
    assert est.staleness_checked is False
    assert est.any_stale is False
    for e in est.assumptions:
        assert e.stale is None
        assert e.age_days is None


def test_future_as_of_not_stale_with_note(assumptions):
    est = estimate_cost(golden_inputs(), assumptions, today=_days(-4))
    fx = _entry(est, "fx_usd_inr")
    assert fx.stale is False
    assert fx.age_days == -4
    assert "2026-10-24 is in the future" in fx.note
    assert est.any_stale is False


def test_override_entries_not_checked_and_not_counted():
    cfg = _with_as_of(bcd_pct="2020-01-01")  # would be stale, but it is overridden
    est = estimate_cost(golden_inputs(overrides=CostOverrides(bcd_pct=D("25"))), cfg, today=_days(1))
    bcd = _entry(est, "bcd_pct")
    assert bcd.user_supplied is True
    assert bcd.stale is None and bcd.age_days is None
    assert est.any_stale is False


def test_methodology_entries_not_checked(assumptions):
    est = estimate_cost(golden_inputs(), assumptions, today=_days(1000))
    for name in cost_engine.METHODOLOGY_TO_VERIFY:
        assert _entry(est, name).stale is None


def _amounts(est):
    return (est.low, est.expected, est.high, est.per_unit_low, est.per_unit_expected, est.per_unit_high,
            [(line.label, line.base, line.rate_pct, line.amount) for line in est.breakdown])


@pytest.mark.parametrize("kw", [{}, {"freight_inr": None, "insurance_inr": None}])
def test_staleness_never_changes_amounts(assumptions, kw):
    plain = estimate_cost(golden_inputs(**kw), assumptions)
    stale = estimate_cost(golden_inputs(**kw), assumptions, today=_days(1000))
    assert stale.any_stale is True
    assert _amounts(plain) == _amounts(stale)


@pytest.mark.parametrize("verify_all", [False, True])
def test_staleness_does_not_change_verified_flags(assumptions, verify_all):
    cfg = _all_verified(assumptions) if verify_all else assumptions
    plain = estimate_cost(golden_inputs(), cfg)
    stale = estimate_cost(golden_inputs(), cfg, today=_days(1000))
    assert stale.any_stale is True
    for flag in ("rates_verified", "methodology_unverified", "unverified_assumptions"):
        assert getattr(plain, flag) == getattr(stale, flag)
    assert plain.rates_verified is verify_all


def test_version_and_effective_date_in_estimate(assumptions):
    raw = raw_config()
    assert assumptions.version == raw["version"] == "v0-placeholder"
    assert assumptions.effective_date == raw["effective_date"] == "2026-10-24"
    for today in (None, _days(1)):
        est = estimate_cost(golden_inputs(), assumptions, today=today)
        assert est.assumptions_version == raw["version"]
        assert est.assumptions_effective_date == raw["effective_date"]


def test_version_and_effective_date_are_read_only(assumptions):
    with pytest.raises((AttributeError, ValueError, TypeError)):
        assumptions.version = "other"
    with pytest.raises((AttributeError, ValueError, TypeError)):
        assumptions.effective_date = "2027-01-01"
    assert "version" not in type(assumptions).model_fields
    assert "effective_date" not in type(assumptions).model_fields


def test_metadata_survives_model_copy(assumptions):
    copied = _all_verified(assumptions)
    assert copied.version == assumptions.version
    assert copied.effective_date == assumptions.effective_date


@pytest.mark.parametrize("value", [None, "", "   ", 1, "missing"])
def test_bad_or_missing_version_rejected(value):
    raw = raw_config()
    if value == "missing":
        del raw["version"]
    else:
        raw["version"] = value
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


@pytest.mark.parametrize("value", [None, "", "24-10-2026", "2026-02-30", "2026/10/24", "soon", 20261024, "missing"])
def test_bad_or_missing_effective_date_rejected(value):
    raw = raw_config()
    if value == "missing":
        del raw["effective_date"]
    else:
        raw["effective_date"] = value
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


def test_effective_date_as_date_object_is_coerced():
    raw = raw_config()
    raw["effective_date"] = _dt.date(2026, 10, 24)
    assert parse_cost_assumptions(raw).effective_date == "2026-10-24"


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "30", None])
def test_invalid_max_age_days_rejected(value):
    raw = raw_config()
    raw["fx_usd_inr"]["max_age_days"] = value
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


def test_missing_max_age_days_rejected():
    raw = raw_config()
    del raw["bcd_pct"]["max_age_days"]
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


@pytest.mark.parametrize("value", ["2026-13-01", "24/10/2026", "yesterday", "", "2026-10-24T00:00:00"])
def test_unparseable_as_of_rejected(value):
    raw = raw_config()
    raw["igst_pct"]["as_of"] = value
    with pytest.raises(ValidationError):
        parse_cost_assumptions(raw)


def test_parse_as_of_error_is_clear():
    with pytest.raises(ValueError, match="not an ISO date"):
        parse_as_of("24/10/2026")
    with pytest.raises(ValueError, match="not a valid calendar date"):
        parse_as_of("2026-02-30")
    assert parse_as_of("2026-10-24") == AS_OF


def test_deterministic_with_today(assumptions):
    a = estimate_cost(golden_inputs(freight_inr=None), assumptions, today=_days(30))
    b = estimate_cost(golden_inputs(freight_inr=None), assumptions, today=_days(30))
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


@pytest.mark.parametrize("today", [None, _dt.date(2026, 10, 25), _dt.date(2030, 1, 1)])
def test_golden_case_unchanged_with_staleness(assumptions, today):
    est = estimate_cost(golden_inputs(), assumptions, today=today)
    assert by_label(est, "goods_value").amount == D("90000.00")
    assert by_label(est, "cif").amount == D("102000.00")
    assert by_label(est, "landing_charge_notional").amount == D("1020.00")
    assert by_label(est, "assessable_value").amount == D("103020.00")
    assert by_label(est, "bcd").amount == D("20604.00")
    assert by_label(est, "sws").amount == D("2060.40")
    assert by_label(est, "igst").amount == D("22623.19")
    assert by_label(est, "duties_and_taxes").amount == D("45287.59")
    assert est.expected == D("154287.59")
    assert est.per_unit_expected == D("1542.88")


def test_stale_default_freight_flags_derived_freight_entry():
    cfg = _with_as_of(default_freight_low_inr="2026-01-01")
    est = estimate_cost(golden_inputs(freight_inr=None), cfg, today=_days(1))
    derived = _entry(est, "freight_inr")
    assert derived.stale is True
    assert "default_freight_low_inr" in derived.note
    assert _entry(est, "default_freight_low_inr").stale is True
    assert _entry(est, "default_freight_high_inr").stale is False
    assert est.any_stale is True


def test_fresh_default_freight_derived_entry_not_stale(assumptions):
    est = estimate_cost(golden_inputs(freight_inr=None), assumptions, today=_days(1))
    assert _entry(est, "freight_inr").stale is False


def test_user_provided_freight_not_flagged_by_stale_default():
    cfg = _with_as_of(default_freight_low_inr="2026-01-01", default_freight_high_inr="2026-01-01")
    est = estimate_cost(golden_inputs(), cfg, today=_days(1))
    names = {e.name for e in est.assumptions}
    assert "freight_inr" not in names and "default_freight_low_inr" not in names
    assert est.any_stale is False


def test_stale_insurance_pct_flags_derived_insurance_entry():
    cfg = _with_as_of(insurance_pct_of_goods="2026-01-01")
    est = estimate_cost(golden_inputs(insurance_inr=None), cfg, today=_days(1))
    assert _entry(est, "insurance_pct_of_goods").stale is True
    assert _entry(est, "insurance_inr").stale is True
    supplied = estimate_cost(golden_inputs(), cfg, today=_days(1))
    assert supplied.any_stale is False


def test_other_duty_without_max_age_days_not_checked():
    raw = raw_config()
    raw["other_duties"] = [{"label": "extra", "rate_pct": 5, "base": "assessable_value", "source": "s",
                            "as_of": "2020-01-01", "verified": False}]
    est = estimate_cost(golden_inputs(), parse_cost_assumptions(raw), today=_days(1))
    duty = _entry(est, "other_duty:extra")
    assert duty.stale is None
    assert "no expiry set, staleness not checked" in duty.note.lower()
    assert duty.note.startswith("Charged on base: assessable_value")
    assert est.any_stale is False


def test_other_duty_with_max_age_days_is_checked():
    raw = raw_config()
    raw["other_duties"] = [{"label": "extra", "rate_pct": 5, "base": "assessable_value", "source": "s",
                            "as_of": "2020-01-01", "verified": False, "max_age_days": 90}]
    est = estimate_cost(golden_inputs(), parse_cost_assumptions(raw), today=_days(1))
    assert _entry(est, "other_duty:extra").stale is True
    assert est.any_stale is True


@pytest.mark.parametrize("bad", [_dt.datetime(2026, 10, 25, 12, 0), "2026-10-25", 20261025])
def test_today_must_be_a_plain_date(assumptions, bad):
    with pytest.raises(TypeError):
        estimate_cost(golden_inputs(), assumptions, today=bad)


def test_no_forbidden_words_in_stale_output():
    cfg = _with_as_of(fx_usd_inr="2026-01-01")
    text = estimate_cost(golden_inputs(freight_inr=None), cfg, today=_days(1)).model_dump_json().lower()
    assert "fraud" not in text and "fake" not in text


CLOCK_ATTRS = {"today", "now", "utcnow"}


@pytest.mark.parametrize("module_file", ["cost_engine.py", "cost_config.py"])
def test_no_clock_or_time_usage(module_file):
    path = Path(cost_engine.__file__).with_name(module_file)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in CLOCK_ATTRS, f"{module_file} calls .{node.func.attr}()"
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] != "time" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "time"
