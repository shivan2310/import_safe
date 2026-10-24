"""Build CostAssumptions from cost_assumptions.yaml plus APPROVED rate records in the store.

The cost engine never reads the store: this loader builds the CostAssumptions object the engine already
accepts. Only the latest approved record per rate_key (with a matching evidence hash) is applied; pending,
rejected and superseded proposals never affect the result. The YAML file is only read, never written. With an
empty store the result is exactly the YAML load.

An approved record replaces value, as_of (its effective date), source, provenance (human_approved), verified
(true) and evidence_kind; max_age_days and owner stay as in the YAML. Benchmarks never become one exact number:
default_freight_inr sets both default-freight entries (low and high) in one step, and a non-duty benchmark sets
value = median with range_low/range_high = benchmark low/high. Each record is applied atomically: if the result
would not validate, that record is skipped with a warning and nothing from it is applied.

If the latest approval for a key is ignored (evidence hash mismatch), the previous valid approval is used; the
entry note then says "latest approval ignored (evidence hash mismatch); using the approval from <date>" and the
same text is returned as a warning. Records approved from fixture data are marked in the note and warned about.

StoreCorruptionError is NOT caught here. The investigation flow must catch it, fall back to the YAML
placeholders (load_cost_assumptions) and show a visible warning.
"""
import copy
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple, Union

from pydantic import ValidationError

from app.decision.cost_config import CostAssumptions, load_cost_assumptions
from app.decision.rates.models import RANGE_KEYS, EvidenceKind, Provenance, RateRecord, config_fields, target_fields
from app.decision.rates.store import RateStore

BENCHMARK_LABEL = "Market benchmark, not an official figure"


class RateLoaderWarning(UserWarning):
    """An approved record was ignored or could not be applied."""


@dataclass
class LoadReport:
    assumptions: CostAssumptions
    applied: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def benchmark_note(record: RateRecord) -> str:
    return (f"{BENCHMARK_LABEL}: {record.sample_count} samples from {record.domain_count} domains; "
            f"low {record.range_low}, median {record.value}, high {record.range_high} "
            f"(proposal {record.proposal_id}).")


FIXTURE_LABEL = "FIXTURE DATA, NOT REAL EVIDENCE"


def _annotate(note: str, record: RateRecord) -> str:
    """Add the fixture marker and the hash-mismatch fallback sentence, when they apply."""
    parts = [note]
    if record.fixture:
        parts.append(f"{FIXTURE_LABEL} (approved with --allow-fixture).")
    if record.fallback_note:
        parts.append(record.fallback_note + ".")
    return " ".join(parts)


def _dump(base: CostAssumptions) -> Dict[str, Any]:
    data: Dict[str, Any] = {name: getattr(base, name).model_dump() for name in config_fields()}
    data["other_duties"] = [d.model_dump() for d in base.other_duties]
    data["version"] = base.version
    data["effective_date"] = base.effective_date
    return data


def _apply(data: Dict[str, Any], key: str, fields: Tuple[str, ...], record: RateRecord) -> None:
    common = dict(as_of=record.effective_date, source=record.source, provenance=Provenance.human_approved,
                  verified=True, evidence_kind=record.evidence_kind)
    if key in RANGE_KEYS:
        if record.evidence_kind is not EvidenceKind.benchmark or record.range_low is None or record.range_high is None:
            raise ValueError(f"{key} needs a benchmark record with low and high")
        if not (record.range_low <= record.value <= record.range_high):
            raise ValueError("benchmark must satisfy low <= median <= high")
        note = _annotate(benchmark_note(record) + " Expected uses the midpoint of low and high, not the median.",
                         record)
        low_field, high_field = fields
        data[low_field].update(value=record.range_low, evidence_note=note, **common)
        data[high_field].update(value=record.range_high, evidence_note=note, **common)
        return
    (name,) = fields
    if record.evidence_kind is EvidenceKind.benchmark:
        if record.range_low is None or record.range_high is None:
            raise ValueError(f"benchmark record for {key} has no low/high range")
        if not (record.range_low <= record.value <= record.range_high):
            raise ValueError("range must satisfy range_low <= value <= range_high")
        data[name].update(value=record.value, range_low=record.range_low, range_high=record.range_high,
                          evidence_note=_annotate(benchmark_note(record), record), **common)
        return
    data[name].update(
        value=record.value,
        evidence_note=_annotate(f"Human-approved official rate (proposal {record.proposal_id}; approver "
                                f"{record.approved_by}, self-reported).", record),
        **common,
    )


def apply_approved_records(
    base: CostAssumptions, records: Mapping[str, RateRecord]
) -> Tuple[CostAssumptions, List[str], List[str]]:
    """Apply approved records to a copy of base. Returns (assumptions, applied keys, warnings). Pure."""
    if not records:
        return base, [], []
    data = _dump(base)
    applied: List[str] = []
    problems: List[str] = []
    for key in sorted(records):
        record = records[key]
        try:
            fields = target_fields(key)
        except KeyError:
            problems.append(f"approved record for {key} ignored: it matches no config entry")
            continue
        trial = copy.deepcopy(data)
        try:
            _apply(trial, key, fields, record)
            CostAssumptions.model_validate(trial)
        except (ValueError, ValidationError) as exc:
            reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            problems.append(f"approved record for {key} not applied: {reason}")
            continue
        data = trial
        applied.append(key)
        if record.fixture:
            problems.append(f"{key}: applied from fixture data, not real evidence (approved with --allow-fixture)")
    if not applied:
        return base, applied, problems
    return CostAssumptions.model_validate(data), applied, problems


def load_assumptions_report(store: RateStore, base_config_path: Union[str, Path, None] = None) -> LoadReport:
    """Like load_assumptions_with_store, but also returns what was applied and every warning."""
    base = load_cost_assumptions(base_config_path)
    records = store.approved_records()  # StoreCorruptionError propagates
    store_warnings = list(store.warnings)
    assumptions, applied, problems = apply_approved_records(base, records)
    return LoadReport(assumptions=assumptions, applied=applied, warnings=store_warnings + problems)


def load_assumptions_with_store(store: RateStore, base_config_path: Union[str, Path, None] = None) -> CostAssumptions:
    """CostAssumptions from the YAML plus approved records. Each warning is also emitted as RateLoaderWarning
    (for example an approval ignored because its evidence hash does not match)."""
    report = load_assumptions_report(store, base_config_path)
    for message in report.warnings:
        warnings.warn(message, RateLoaderWarning, stacklevel=2)
    return report.assumptions
