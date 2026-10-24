from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.decision.rates import checks
from app.decision.rates.models import Candidate, ReasonCode, normalise_host
from app.decision.rates.policy import load_policy, parse_policy
from tests.rate_helpers import NOW, POLICY, policy_with, sample, statutory

FX = POLICY.rates["fx_usd_inr"]
BCD = POLICY.rates["bcd_pct"]
CLEARING = POLICY.rates["clearing_inr"]


# ---- number in excerpt -------------------------------------------------------------------------

@pytest.mark.parametrize("value,excerpt", [
    ("100000", "Rs 1,00,000 per shipment"),
    ("100000", "Rs 100,000 per shipment"),
    ("3000", "Rs 3,000.00 per shipment"),
    ("3000.00", "Rs 3,000 per shipment"),
])
def test_number_found_after_normalising_separators_and_trailing_zeros(value, excerpt):
    assert checks.check_number_in_excerpt(D(value), excerpt, CLEARING).passed


@pytest.mark.parametrize("value,excerpt", [("20", "Notified in 2026"), ("20", "Rs 120 per shipment"), ("3000", "Rs 30,000")])
def test_number_inside_a_larger_number_is_not_a_match(value, excerpt):
    result = checks.check_number_in_excerpt(D(value), excerpt, CLEARING)
    assert not result.passed
    assert result.reason_code is ReasonCode.number_not_in_excerpt


@pytest.mark.parametrize("excerpt", ["duty 20% ad valorem", "duty 20 %", "at 20 per cent", "at 20 percent", "20 Per-Cent"])
def test_percent_number_followed_by_percent_marker(excerpt):
    assert checks.check_number_in_excerpt(D("20"), excerpt, BCD).passed


@pytest.mark.parametrize("excerpt", ["Notification 20/2024-Customs", "within 20 days", "20 percentage points", "20"])
def test_percent_number_without_marker_fails(excerpt):
    result = checks.check_number_in_excerpt(D("20"), excerpt, BCD)
    assert not result.passed
    assert result.reason_code is ReasonCode.number_not_in_excerpt


def test_notification_number_does_not_satisfy_percent_rule_even_if_rate_appears_elsewhere_without_marker():
    assert not checks.check_number_in_excerpt(D("20"), "Notification 20/2024 dated 2.2.2024", BCD).passed
    assert checks.check_number_in_excerpt(D("20"), "Notification 20/2024: duty 20%", BCD).passed


@pytest.mark.parametrize("excerpt,passed", [
    ("1 USD = 84.50 INR", True),
    ("One US Dollar: 84.50", True),
    ("United States Dollar 84.5", True),
    ("Rate 84.50 INR", False),
    ("1 USDT = 84.50", False),
])
def test_fx_excerpt_must_name_the_currency(excerpt, passed):
    assert checks.check_number_in_excerpt(D("84.50"), excerpt, FX).passed is passed


# ---- unit, bounds, kind, effective date --------------------------------------------------------

def test_unit_check():
    assert checks.check_unit(statutory(), FX).passed
    bad = checks.check_unit(statutory(unit="inr_per_eur"), FX)
    assert not bad.passed and bad.reason_code is ReasonCode.unit_mismatch


@pytest.mark.parametrize("value,passed", [("50", True), ("150", True), ("49.99", False), ("150.01", False)])
def test_bounds_check(value, passed):
    candidate = statutory(value=value)
    result = checks.check_bounds(candidate, FX)
    assert result.passed is passed
    if not passed:
        assert result.reason_code is ReasonCode.out_of_bounds


def test_kind_check():
    assert not checks.check_kind(statutory(kind="benchmark"), FX).passed


@pytest.mark.parametrize("effective_date,passed", [
    ("2026-10-23", True),
    ("2026-10-25", True),  # one day ahead of now is allowed
    ("2026-10-26", False),  # two days ahead is not
    ("23/10/2026", False),
    ("2026-02-30", False),
    (None, False),  # statutory rates need a date
])
def test_effective_date_check(effective_date, passed):
    result = checks.check_effective_date(effective_date, FX, NOW)
    assert result.passed is passed
    if not passed:
        assert result.reason_code is ReasonCode.bad_effective_date


def test_benchmark_effective_date_optional():
    assert checks.check_effective_date(None, CLEARING, NOW).passed


# ---- hosts and tiers ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,host", [
    ("https://WWW.CBIC.GOV.IN./a", "www.cbic.gov.in"),
    ("https://user:secret@cbic.gov.in:8443/a", "cbic.gov.in"),
    ("https://cbic.gov.in@other.example/a", "other.example"),
    ("https://cbic.gov.in/a", "cbic.gov.in"),
])
def test_host_normalisation(url, host):
    assert normalise_host(url) == host


@pytest.mark.parametrize("url,tier", [
    ("https://www.cbic.gov.in/a", 1),
    ("https://CBIC.gov.in./a", 1),
    ("https://cbic.gov.in:8443/a", 1),
    ("http://www.cbic.gov.in/a", 3),  # tier 1 requires https
    ("https://cbic.gov.in.other.example/a", 3),
    ("https://notcbic.gov.in/a", 3),
    ("https://cbic.gov.in@other.example/a", 3),
    ("https://news.example/a", 3),
])
def test_tier_from_policy(url, tier):
    assert checks.tier_for(normalise_host(url), url, FX) == tier


def test_tier_two_from_policy_list_and_https_not_required():
    rp = policy_with("fx_usd_inr", tier2_domains=["news-one.example"]).rates["fx_usd_inr"]
    assert checks.tier_for("news-one.example", "https://news-one.example/x", rp) == 2
    assert checks.tier_for("news-one.example", "http://news-one.example/x", rp) == 2
    assert checks.tier_for("news-two.example", "https://news-two.example/x", rp) == 3


@pytest.mark.parametrize("url", ["ftp://cbic.gov.in/x", "cbic.gov.in/x", "javascript:alert(1)", "https:///x"])
def test_candidate_rejects_non_http_urls(url):
    with pytest.raises(ValidationError):
        statutory(url=url)


def test_candidate_rejects_float_naive_datetime_and_bool_tier():
    base = statutory().model_dump()
    with pytest.raises(ValidationError):
        Candidate(**{**base, "value": 84.5})
    with pytest.raises(ValidationError):
        Candidate(**{**base, "retrieved_at": datetime(2026, 10, 24, 10, 0)})
    with pytest.raises(ValidationError):
        Candidate(**{**base, "source_tier": True})
    with pytest.raises(ValidationError):
        Candidate(**{**base, "value": "-1"})


# ---- change ------------------------------------------------------------------------------------

def test_change_check():
    assert checks.change_pct(D("84.5"), D("80")) == D("5.625")
    assert not checks.check_change(D("84.5"), D("80"), FX).passed  # 5.625% > 5%
    assert checks.check_change(D("84"), D("80"), FX).passed  # exactly 5% is within the limit
    assert checks.change_pct(D("0"), D("0")) == D("0")
    assert checks.change_pct(D("1"), D("0")) is None
    assert not checks.check_change(D("1"), D("0"), FX).passed


# ---- benchmark statistics ----------------------------------------------------------------------

def test_median_and_quantile():
    assert checks.median([D(3), D(1), D(2)]) == D(2)
    assert checks.median([D(1), D(2), D(3), D(4)]) == D("2.5")
    ordered = [D(1000), D(1100), D(1200), D(1300), D(5000)]
    assert checks.quantile(ordered, D("0.25")) == D(1100)
    assert checks.quantile(ordered, D("0.75")) == D(1300)
    assert checks.quantile([D(3000), D(3100), D(3200), D(3400)], D("0.25")) == D(3075)


def test_split_outliers_tukey_fences():
    points = [("a", D(3000)), ("b", D(3200)), ("c", D(3400)), ("d", D(3600)), ("e", D(12000))]
    kept, outliers = checks.split_outliers(points)
    assert outliers == [("e", D(12000))]
    assert [h for h, _ in kept] == ["a", "b", "c", "d"]


def test_spread_check():
    result, ratio = checks.check_spread(D(1000), D(3600), CLEARING)
    assert not result.passed and result.reason_code is ReasonCode.spread_too_wide
    assert ratio == D("3.6")
    assert checks.check_spread(D(1000), D(3000), CLEARING)[0].passed  # exactly 3 is allowed
    assert not checks.check_spread(D(0), D(10), CLEARING)[0].passed


# ---- policy validation -------------------------------------------------------------------------

def _raw_policy():
    import yaml
    from app.decision.rates.policy import DEFAULT_POLICY_PATH
    with open(DEFAULT_POLICY_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _freight_as_statutory(raw):
    rp = raw["rates"]["default_freight_inr"]
    for name in ("min_samples", "min_distinct_domains", "max_spread_ratio"):
        rp.pop(name)
    rp.update({"kind": "statutory", "tier1_domains": ["cbic.gov.in"]})


def test_shipped_policy_loads_with_decimals():
    policy = load_policy()
    assert set(policy.rates) == {"fx_usd_inr", "bcd_pct", "sws_pct_of_bcd", "igst_pct", "default_freight_inr",
                                 "clearing_inr", "port_cfs_inr", "domestic_transport_inr"}
    for rp in policy.rates.values():
        for value in (rp.min_value, rp.max_value, rp.max_change_pct):
            assert type(value) is D
    assert policy.rates["fx_usd_inr"].max_change_pct == D(5)
    assert policy.rates["bcd_pct"].max_change_pct == D(25)
    assert policy.rates["clearing_inr"].min_samples == 5
    assert policy.rates["clearing_inr"].min_distinct_domains == 3
    assert policy.rates["clearing_inr"].max_spread_ratio == D(3)
    assert policy.rates["fx_usd_inr"].max_effective_date_future_days == 1
    assert policy.rates["fx_usd_inr"].proposal_expiry_days == 14
    assert all(rp.tier2_domains == [] for rp in policy.rates.values())


def test_yaml_float_converted_exactly():
    raw = _raw_policy()
    raw["rates"]["fx_usd_inr"]["max_change_pct"] = 0.1
    assert parse_policy(raw).rates["fx_usd_inr"].max_change_pct == D("0.1")


@pytest.mark.parametrize("mutate", [
    lambda r: r["rates"].update({"mystery_rate": r["rates"]["bcd_pct"]}),  # matches no config entry
    lambda r: r["rates"].update({"default_freight_low_inr": r["rates"]["clearing_inr"]}),  # only via default_freight_inr
    lambda r: r["rates"]["bcd_pct"].update({"min_value": 50, "max_value": 10}),  # min > max
    lambda r: r["rates"]["bcd_pct"].update({"min_value": -1}),
    lambda r: r["rates"]["bcd_pct"].update({"max_change_pct": -5}),
    lambda r: r["rates"]["bcd_pct"].update({"tier1_domains": []}),  # statutory needs an official domain
    lambda r: r["rates"]["bcd_pct"].update({"min_samples": 5}),  # benchmark-only field on statutory
    lambda r: r["rates"]["clearing_inr"].pop("min_samples"),
    lambda r: r["rates"]["clearing_inr"].update({"max_spread_ratio": 0.5}),
    lambda r: r["rates"]["bcd_pct"].update({"tier2_domains": ["cbic.gov.in"]}),  # in both lists
    lambda r: r["rates"]["bcd_pct"].update({"tier1_domains": ["https://cbic.gov.in/"]}),
    lambda r: r["rates"]["bcd_pct"].update({"kind": "benchmark", "min_samples": 5, "min_distinct_domains": 3,
                                            "max_spread_ratio": 3}),  # benchmark on a non-range entry
    lambda r: _freight_as_statutory(r),  # default_freight_inr feeds a range, so it must be a benchmark
    lambda r: r["rates"]["fx_usd_inr"].update({"currency_terms": []}),
    lambda r: r["rates"]["bcd_pct"].update({"max_value": 150}),  # percent above 100
    lambda r: r.update({"max_runs_per_refresh": 0}),
    lambda r: r.update({"max_domains_per_refresh": True}),
    lambda r: r["rates"]["bcd_pct"].update({"proposal_expiry_days": 1.5}),
])
def test_invalid_policies_rejected(mutate):
    raw = _raw_policy()
    mutate(raw)
    with pytest.raises((ValidationError, ValueError)):
        parse_policy(raw)


def test_domains_normalised_and_unlisted_domain_is_tier_three():
    rp = policy_with("bcd_pct", tier1_domains=["CBIC.GOV.IN."]).rates["bcd_pct"]
    assert rp.tier1_domains == ["cbic.gov.in"]
    assert checks.tier_for("unlisted.example", "https://unlisted.example/x", rp) == 3


def test_now_date_used_for_future_limit_not_wall_clock():
    later = NOW + timedelta(days=30)
    assert checks.check_effective_date("2026-11-23", FX, later).passed
    assert not checks.check_effective_date("2026-11-23", FX, NOW).passed


def test_benchmark_sample_helper_excerpt_contains_value():
    candidate = sample(value="3000")
    assert checks.check_number_in_excerpt(candidate.value, candidate.excerpt, CLEARING).passed


def test_timezone_of_now_is_respected():
    ist = timezone(timedelta(hours=5, minutes=30))
    late_evening_utc = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    # 20:00 UTC is already 25 October in IST, so 2026-10-26 is only one day ahead there.
    assert checks.check_effective_date("2026-10-26", FX, late_evening_utc.astimezone(ist)).passed
    assert not checks.check_effective_date("2026-10-26", FX, late_evening_utc).passed
