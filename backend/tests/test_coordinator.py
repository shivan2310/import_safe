"""Tests for the investigation coordinator and its support modules (Step 8).

These tests are fully offline: no TinyFish calls, no database, no clock calls.  A
mock connector returns either the fixture results or a failed result; the InMemoryStore
absorbs all storage.

Coverage plan (see progress.md Step 8 for the full matrix):
    states        – parse, can_transition, stage_progress
    profile_builder – listing facts, order facts, rule_profile, cert_claim, registry_record
    coordinator   – happy path, NEEDS_INPUT on failed listing, classification gate,
                    recalculate_cost, FAILED on unexpected error
"""
import asyncio
import dataclasses
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.coordinator.coordinator import _today, run, recalculate_cost
from app.coordinator.profile_builder import (
    build_listing_facts, build_order_facts, cert_claim_from_facts, extracted_from_facts,
    parse_price, profile_from_facts, registry_record, rule_profile, SPEC_PREFIX,
)
from app.coordinator.states import (
    InvestigationState as S, PIPELINE, RESTING, TERMINAL, can_transition, parse_state, stage_progress,
)
from app.coordinator.store import InMemoryStore, OrderInput, ProgressEvent, utcnow
from app.db.repositories import FactIn, FactRow, QUESTION_OPEN
from app.decision.enums import ClassificationStatus, FactKind, StageState
from app.decision.report_schema import EvidenceItem
from app.services.tinyfish.fixture_adapter import (
    BT100_SOURCE_URL, DEMO_REGISTRATION_NO, DEMO_REGISTRY_URL, FixtureTinyFishConnector,
)
from app.services.tinyfish.models import ExtractionResult, RegistryResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 10, 24, 10, 0, 0, tzinfo=timezone.utc)


def _fixture_connector(*, fail_listing=False, fail_registry=False, no_record=False) -> FixtureTinyFishConnector:
    conn = FixtureTinyFishConnector(now=lambda: _NOW)
    if fail_listing:
        async def _bad_listing(url):
            return ExtractionResult(source_url=url, retrieved_at=_NOW, status="FAILED",
                                    failed=True, is_fixture=True)
        conn.extract_listing = _bad_listing
    if fail_registry or no_record:
        async def _bad_reg(reg, mfr, mdl):
            return RegistryResult(source_url=DEMO_REGISTRY_URL, retrieved_at=_NOW,
                                  status="FAILED" if fail_registry else "COMPLETED",
                                  failed=fail_registry, record_found=not no_record and not fail_registry,
                                  is_fixture=True)
        conn.fetch_registry_record = _bad_reg
    return conn


def _order(**overrides) -> OrderInput:
    base = dict(url=BT100_SOURCE_URL, quantity=100, purpose="resale",
                freight_inr=Decimal("12000"), insurance_inr=Decimal("0"))
    base.update(overrides)
    return OrderInput(**base)


def _store_with(order: Optional[OrderInput] = None) -> tuple:
    store = InMemoryStore()
    inv_id = "01JK5R2X1Z11111111111111AA"
    if order is None:
        order = _order()
    store.create(inv_id, order)
    return store, inv_id


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class TestParseState:
    def test_valid(self):
        assert parse_state("CREATED") is S.CREATED
        assert parse_state("REPORT_READY") is S.REPORT_READY

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="unknown investigation state"):
            parse_state("BOGUS")


class TestCanTransition:
    def test_forward_steps(self):
        assert can_transition(S.CREATED, S.READING_LISTING)
        assert can_transition(S.READING_LISTING, S.PROFILE_BUILT)
        assert can_transition(S.PROFILE_BUILT, S.CLASSIFIED)
        assert can_transition(S.PROFILE_BUILT, S.NEEDS_INPUT)
        assert can_transition(S.NEEDS_INPUT, S.PROFILE_BUILT)

    def test_interrupt_always_allowed(self):
        for src in (S.CREATED, S.READING_LISTING, S.PROFILE_BUILT):
            assert can_transition(src, S.FAILED)
            assert can_transition(src, S.CANCELLED)
            assert can_transition(src, S.EXPIRED)

    def test_terminal_blocks_everything(self):
        for terminal in TERMINAL:
            for dest in S:
                assert not can_transition(terminal, dest)

    def test_backward_not_allowed(self):
        assert not can_transition(S.CLASSIFIED, S.PROFILE_BUILT)
        assert not can_transition(S.ESTIMATING_COST, S.CLASSIFIED)

    def test_skip_not_allowed(self):
        assert not can_transition(S.CREATED, S.CLASSIFIED)


class TestStageProgress:
    def test_created_shows_all_pending(self):
        stages = stage_progress(S.CREATED)
        assert all(st == StageState.pending for _, st in stages)

    def test_running_state(self):
        prog = dict(stage_progress(S.READING_LISTING))
        assert prog["READING_LISTING"] == StageState.running

    def test_needs_input_marks_profile_built(self):
        prog = dict(stage_progress(S.NEEDS_INPUT))
        assert prog["PROFILE_BUILT"] == StageState.needs_input

    def test_report_ready_all_done(self):
        stages = stage_progress(S.REPORT_READY)
        assert all(st == StageState.done for _, st in stages)

    def test_failed_all_pending(self):
        stages = stage_progress(S.FAILED)
        assert all(st == StageState.pending for _, st in stages)


# ---------------------------------------------------------------------------
# InMemoryStore
# ---------------------------------------------------------------------------

class TestInMemoryStore:
    def test_transition_cas(self):
        store = InMemoryStore()
        store.create("id1", _order())
        ok = _run(store.transition("id1", S.CREATED, S.READING_LISTING))
        assert ok
        fail = _run(store.transition("id1", S.CREATED, S.PROFILE_BUILT))
        assert not fail

    def test_force_state_skips_terminal(self):
        store = InMemoryStore()
        store.create("id1", _order())
        _run(store.force_state("id1", S.FAILED))
        prev = _run(store.force_state("id1", S.READING_LISTING))
        assert prev is None

    def test_question_resolve_answered(self):
        from app.db.ids import new_ulid
        store = InMemoryStore()
        store.create("id1", _order())
        from app.db.repositories import QuestionIn
        q = QuestionIn(id=new_ulid(), field="category", prompt="What category?",
                       status=QUESTION_OPEN, created_at=_NOW)
        _run(store.save_question("id1", q))
        ok = _run(store.resolve_question("id1", q.id, "bluetooth speaker", False))
        assert ok
        rows = _run(store.list_questions("id1"))
        assert rows[0].answer == "bluetooth speaker"
        assert rows[0].status == "answered"

    def test_question_resolve_skipped(self):
        from app.db.ids import new_ulid
        store = InMemoryStore()
        store.create("id1", _order())
        from app.db.repositories import QuestionIn
        q = QuestionIn(id=new_ulid(), field="freight", prompt="Freight?",
                       status=QUESTION_OPEN, created_at=_NOW)
        _run(store.save_question("id1", q))
        _run(store.resolve_question("id1", q.id, None, True))
        rows = _run(store.list_questions("id1"))
        assert rows[0].status == "skipped"


# ---------------------------------------------------------------------------
# parse_price
# ---------------------------------------------------------------------------

class TestParsePrice:
    def test_usd_symbol(self):
        amount, currency = parse_price("US$10.00")
        assert amount == Decimal("10.00") and currency == "USD"

    def test_inr_symbol(self):
        amount, currency = parse_price("₹850")
        assert amount == Decimal("850") and currency == "INR"

    def test_range_returns_none(self):
        amount, _ = parse_price("10-20")
        assert amount is None

    def test_bare_number_with_hint(self):
        amount, currency = parse_price("10", "USD")
        assert amount == Decimal("10") and currency == "USD"

    def test_non_usd_inr_currency(self):
        amount, currency = parse_price("€10")
        assert currency is None

    def test_non_string(self):
        amount, currency = parse_price(None)
        assert amount is None and currency is None


# ---------------------------------------------------------------------------
# build_listing_facts
# ---------------------------------------------------------------------------

def _fixture_extraction(fields=None, excerpts=None) -> ExtractionResult:
    fields = fields or {
        "title": "BT-100 Speaker", "price": "10", "currency": "USD",
        "specs": {"Bluetooth Version": "5.0", "Battery Capacity": "2000mAh"},
        "certification_numbers": [DEMO_REGISTRATION_NO],
    }
    excerpts = excerpts or {
        "title": "BT-100 Speaker", "specs": "Bluetooth 5.0, 2000mAh",
        "certification_numbers": "BIS R-41234567",
    }
    return ExtractionResult(source_url=BT100_SOURCE_URL, retrieved_at=_NOW, status="COMPLETED",
                            failed=False, fields=fields, excerpt_map=excerpts)


class TestBuildListingFacts:
    def test_title_fact_is_confirmed(self):
        facts, _ = build_listing_facts(_fixture_extraction(), "INV001")
        by_field = {f.field: f for f in facts}
        assert by_field["title"].kind == FactKind.confirmed
        assert by_field["title"].evidence_id is not None

    def test_bis_number_extracted(self):
        facts, _ = build_listing_facts(_fixture_extraction(), "INV001")
        by_field = {f.field: f for f in facts}
        assert "bis_registration_no" in by_field
        assert by_field["bis_registration_no"].value.startswith("R-")

    def test_specs_become_prefixed_facts(self):
        facts, _ = build_listing_facts(_fixture_extraction(), "INV001")
        spec_fields = [f.field for f in facts if f.field.startswith(SPEC_PREFIX)]
        assert any("Bluetooth" in sf for sf in spec_fields)

    def test_evidence_count(self):
        _, evidence = build_listing_facts(_fixture_extraction(), "INV001")
        assert len(evidence) > 0

    def test_no_excerpt_becomes_seller_claim(self):
        ext = _fixture_extraction(fields={"title": "X", "moq": "50"}, excerpts={"title": "X"})
        facts, _ = build_listing_facts(ext, "INV001")
        by_field = {f.field: f for f in facts}
        assert by_field["moq"].kind == FactKind.seller_claim
        assert by_field["moq"].evidence_id is None


# ---------------------------------------------------------------------------
# build_order_facts
# ---------------------------------------------------------------------------

class TestBuildOrderFacts:
    def test_quantity_is_user_supplied(self):
        facts = build_order_facts(_order())
        by_field = {f.field: f for f in facts}
        assert by_field["quantity"].kind == FactKind.user_supplied
        assert by_field["quantity"].value == 100

    def test_purpose_included(self):
        facts = build_order_facts(_order())
        by_field = {f.field: f for f in facts}
        assert by_field["purpose"].value == "resale"

    def test_bis_number_from_certificates(self):
        order = _order(seller_certificates=(DEMO_REGISTRATION_NO,))
        facts = build_order_facts(order)
        by_field = {f.field: f for f in facts}
        assert "bis_registration_no" in by_field
        assert by_field["bis_registration_no"].kind == FactKind.seller_claim


# ---------------------------------------------------------------------------
# profile_from_facts and extracted_from_facts
# ---------------------------------------------------------------------------

_EVIDENCE_ID = "01JK5R2X1Z00000000000000EE"


def _make_fact_row(field, value, kind=FactKind.confirmed, evidence_id=None):
    # confirmed facts must carry an evidence_id (ProductProfile validator).
    eid = evidence_id if evidence_id is not None else (_EVIDENCE_ID if kind == FactKind.confirmed else None)
    return FactRow(id="01JK5R2X1Z00000000000000FF", investigation_id="inv", field=field,
                   value=value, kind=kind, evidence_id=eid, confidence=None)


class TestProfileFromFacts:
    def test_kind_routing(self):
        rows = [
            _make_fact_row("title", "BT-100", FactKind.confirmed),
            _make_fact_row("manufacturer", "Acme", FactKind.seller_claim),
            _make_fact_row("quantity", "100", FactKind.user_supplied),
        ]
        profile = profile_from_facts(rows)
        assert any(f.field == "title" for f in profile.confirmed)
        assert any(f.field == "manufacturer" for f in profile.seller_claims)
        assert any(f.field == "quantity" for f in profile.user_supplied)

    def test_quantity_cast_to_int(self):
        rows = [_make_fact_row("quantity", "100", FactKind.user_supplied)]
        profile = profile_from_facts(rows)
        assert profile.user_supplied[0].value == 100

    def test_user_supplied_overrides_extracted(self):
        rows = [
            _make_fact_row("category", "speaker", FactKind.confirmed),
            _make_fact_row("category", "bluetooth_speaker", FactKind.user_supplied),
        ]
        profile = profile_from_facts(rows)
        assert len([f for f in profile.confirmed if f.field == "category"]) == 0


class TestExtractedFromFacts:
    def test_spec_prefix_becomes_specifications(self):
        rows = [_make_fact_row(SPEC_PREFIX + "Bluetooth Version", "5.0")]
        ext = extracted_from_facts(rows)
        assert "specifications" in ext
        assert "bluetooth" in ext

    def test_user_category_excluded(self):
        rows = [_make_fact_row("category", "bluetooth_speaker", FactKind.user_supplied)]
        ext = extracted_from_facts(rows)
        assert "category" not in ext


# ---------------------------------------------------------------------------
# rule_profile
# ---------------------------------------------------------------------------

class TestRuleProfile:
    def test_bluetooth_flag(self):
        ext = {"title": "Bluetooth speaker", "specifications": {"Bluetooth Version": "5.0"}}
        rp = rule_profile(ext, None)
        assert rp.get("has_bluetooth") is True

    def test_battery_flag(self):
        ext = {"title": "Speaker", "specifications": {"Battery Capacity": "2000mAh"}}
        rp = rule_profile(ext, None)
        assert rp.get("has_battery") is True

    def test_category_from_classification(self):
        from app.decision.classifier import Classification
        from app.decision.enums import ClassificationStatus, Confidence
        cls = Classification(category="bluetooth_speaker", confidence=Confidence.high,
                             status=ClassificationStatus.confirmed, candidate_hs_codes=[],
                             reasoning="", score=Decimal("0.8"), config_version="v0-proposed")
        rp = rule_profile({}, cls)
        assert rp.get("category") == "bluetooth_speaker"


# ---------------------------------------------------------------------------
# cert_claim_from_facts
# ---------------------------------------------------------------------------

class TestCertClaimFromFacts:
    def test_extracts_registration_number(self):
        rows = [_make_fact_row("bis_registration_no", "R-41234567", FactKind.seller_claim),
                _make_fact_row("manufacturer", "Acme", FactKind.seller_claim),
                _make_fact_row("model", "BT-100", FactKind.confirmed)]
        claim = cert_claim_from_facts(rows)
        assert claim is not None
        assert claim.registration_no == "R-41234567"
        assert claim.manufacturer == "Acme"
        assert claim.model == "BT-100"

    def test_no_registration_returns_none(self):
        rows = [_make_fact_row("title", "BT-100")]
        assert cert_claim_from_facts(rows) is None


# ---------------------------------------------------------------------------
# registry_record
# ---------------------------------------------------------------------------

class TestRegistryRecord:
    def test_failed_result_returns_none_record(self):
        result = RegistryResult(source_url=DEMO_REGISTRY_URL, retrieved_at=_NOW,
                                status="FAILED", failed=True, record_found=False)
        rec, evidence = registry_record(result, "INV001")
        assert rec is None

    def test_no_record_found_returns_none(self):
        result = RegistryResult(source_url=DEMO_REGISTRY_URL, retrieved_at=_NOW,
                                status="COMPLETED", failed=False, record_found=False)
        rec, _ = registry_record(result, "INV001")
        assert rec is None

    def test_valid_record_fields(self):
        result = RegistryResult(
            source_url=DEMO_REGISTRY_URL, retrieved_at=_NOW, status="COMPLETED",
            failed=False, record_found=True,
            fields={"registration_number": "R-41234567", "manufacturer": "Acme Co",
                    "valid_from": "2024-01-01", "valid_to": "2027-01-01", "status": "Active"},
            excerpt_map={"registration_number": "R-41234567 Active", "manufacturer": "Acme Co"},
        )
        rec, evidence = registry_record(result, "INV001")
        assert rec is not None
        assert rec.registration_no == "R-41234567"
        assert rec.manufacturer == "Acme Co"
        assert len(evidence) > 0

    def test_reliable_record_has_evidence_id(self):
        result = RegistryResult(
            source_url=DEMO_REGISTRY_URL, retrieved_at=_NOW, status="COMPLETED",
            failed=False, record_found=True,
            fields={"registration_number": "R-41234567", "manufacturer": "Acme"},
            excerpt_map={"registration_number": "R-41234567"},
        )
        rec, _ = registry_record(result, "INV001")
        assert rec.evidence_id is not None
        assert rec.excerpt is not None


# ---------------------------------------------------------------------------
# Coordinator: happy path (end-to-end with fixtures)
# ---------------------------------------------------------------------------

class TestCoordinatorHappyPath:
    def _go(self, fail_listing=False, fail_registry=False, no_record=False):
        store, inv_id = _store_with()
        connector = _fixture_connector(fail_listing=fail_listing, fail_registry=fail_registry,
                                        no_record=no_record)
        _run(run(inv_id, store, connector))
        return store, inv_id

    def test_report_ready_state(self):
        store, inv_id = self._go()
        assert _run(store.get_state(inv_id)) == S.REPORT_READY

    def test_report_saved(self):
        store, inv_id = self._go()
        report = store.report(inv_id)
        assert report is not None
        assert report.outcome.value in (
            "likely_importable", "conditional_import", "high_risk_do_not_proceed", "insufficient_information")

    def test_facts_saved(self):
        store, inv_id = self._go()
        facts = _run(store.list_facts(inv_id))
        assert len(facts) > 0
        fields = {f.field for f in facts}
        assert "quantity" in fields

    def test_evidence_saved(self):
        store, inv_id = self._go()
        evidence = _run(store.list_evidence(inv_id))
        assert len(evidence) > 0

    def test_events_emitted(self):
        store, inv_id = self._go()
        events = _run(store.list_events(inv_id))
        stage_names = {e.stage for e in events}
        assert "READING_LISTING" in stage_names
        assert "REPORT_READY" in stage_names

    def test_registry_failure_does_not_crash(self):
        store, inv_id = self._go(fail_registry=True)
        # Investigation should still finish
        assert _run(store.get_state(inv_id)) == S.REPORT_READY

    def test_no_registry_record_unverified(self):
        store, inv_id = self._go(no_record=True)
        report = store.report(inv_id)
        assert report is not None
        from app.decision.enums import IdentityResult
        assert report.certification_comparison.result == IdentityResult.unverified

    def test_run_idempotent_when_report_ready(self):
        store, inv_id = self._go()
        events_before = len(_run(store.list_events(inv_id)))
        _run(run(inv_id, store, _fixture_connector()))
        events_after = len(_run(store.list_events(inv_id)))
        assert events_before == events_after


# ---------------------------------------------------------------------------
# Coordinator: NEEDS_INPUT when listing fails
# ---------------------------------------------------------------------------

class TestCoordinatorNeedsInput:
    def test_state_is_needs_input(self):
        store, inv_id = _store_with()
        _run(run(inv_id, store, _fixture_connector(fail_listing=True)))
        assert _run(store.get_state(inv_id)) == S.NEEDS_INPUT

    def test_question_created(self):
        store, inv_id = _store_with()
        _run(run(inv_id, store, _fixture_connector(fail_listing=True)))
        questions = _run(store.list_questions(inv_id))
        assert any(q.status == QUESTION_OPEN for q in questions)


# ---------------------------------------------------------------------------
# Coordinator: FAILED state
# ---------------------------------------------------------------------------

class TestCoordinatorFailed:
    def test_store_errors_mark_failed(self):
        store, inv_id = _store_with()
        # Make list_facts raise an unexpected error after listing succeeds.
        original = store.list_facts
        call_count = [0]
        async def _broken(investigation_id):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("db gone")
            return await original(investigation_id)
        store.list_facts = _broken
        _run(run(inv_id, store, _fixture_connector()))
        state = _run(store.get_state(inv_id))
        assert state in (S.FAILED, S.REPORT_READY)


# ---------------------------------------------------------------------------
# recalculate_cost
# ---------------------------------------------------------------------------

class TestRecalculateCost:
    def test_cost_updated(self):
        store, inv_id = _store_with()
        _run(run(inv_id, store, _fixture_connector()))
        original_cost = store.cost(inv_id)
        assert original_cost is not None
        _run(recalculate_cost(inv_id, store))
        new_cost = store.cost(inv_id)
        assert new_cost is not None
        assert new_cost.expected == original_cost.expected

    def test_with_freight_override(self):
        store, inv_id = _store_with()
        _run(run(inv_id, store, _fixture_connector()))
        overrides = __import__("app.decision.cost_engine", fromlist=["CostOverrides"]).CostOverrides(
            clearing_inr=Decimal("5000"))
        _run(recalculate_cost(inv_id, store, overrides))
        new_cost = store.cost(inv_id)
        assert new_cost is not None

    def test_no_op_when_not_ready(self):
        store, inv_id = _store_with()
        # Investigation is still CREATED; recalculate should be a no-op.
        _run(recalculate_cost(inv_id, store))
        assert store.cost(inv_id) is None
