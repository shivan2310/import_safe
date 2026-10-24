"""Investigation state machine (docs/prd-backend.md B2).

A state names the stage that is running, or that runs next if the process restarts. The coordinator moves between
states only through ``can_transition``. Values are upper case because the API returns them as ``status``
(docs/prd-backend.md B3).
"""
from enum import Enum
from typing import List, Tuple

from app.decision.enums import StageState


class InvestigationState(str, Enum):
    CREATED = "CREATED"
    READING_LISTING = "READING_LISTING"
    PROFILE_BUILT = "PROFILE_BUILT"
    NEEDS_INPUT = "NEEDS_INPUT"
    CLASSIFIED = "CLASSIFIED"
    CHECKING_REQUIREMENTS = "CHECKING_REQUIREMENTS"
    VERIFYING_CLAIMS = "VERIFYING_CLAIMS"
    ESTIMATING_COST = "ESTIMATING_COST"
    REPORT_READY = "REPORT_READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


S = InvestigationState

# The happy path, in order. NEEDS_INPUT sits beside PROFILE_BUILT and is not part of the line.
PIPELINE: Tuple[InvestigationState, ...] = (
    S.CREATED, S.READING_LISTING, S.PROFILE_BUILT, S.CLASSIFIED, S.CHECKING_REQUIREMENTS,
    S.VERIFYING_CLAIMS, S.ESTIMATING_COST, S.REPORT_READY,
)

# No way out of these.
TERMINAL = frozenset({S.FAILED, S.CANCELLED, S.EXPIRED, S.DELETED})

# Where a run stops: finished, paused for the user, or terminal.
RESTING = TERMINAL | {S.REPORT_READY, S.NEEDS_INPUT}

_INTERRUPTS = frozenset({S.FAILED, S.CANCELLED, S.EXPIRED, S.DELETED})

_FORWARD = {
    S.CREATED: {S.READING_LISTING},
    S.READING_LISTING: {S.PROFILE_BUILT},
    S.PROFILE_BUILT: {S.CLASSIFIED, S.NEEDS_INPUT},
    S.NEEDS_INPUT: {S.PROFILE_BUILT},
    S.CLASSIFIED: {S.CHECKING_REQUIREMENTS},
    S.CHECKING_REQUIREMENTS: {S.VERIFYING_CLAIMS},
    S.VERIFYING_CLAIMS: {S.ESTIMATING_COST},
    S.ESTIMATING_COST: {S.REPORT_READY},
    # A finished report can be recomputed from classification after an answer or an assumption change.
    S.REPORT_READY: {S.CLASSIFIED},
}


def parse_state(value: str) -> InvestigationState:
    try:
        return InvestigationState(value)
    except ValueError:
        raise ValueError(f"unknown investigation state: {value!r}") from None


def can_transition(current: InvestigationState, new: InvestigationState) -> bool:
    if current in TERMINAL:
        return False
    if new in _INTERRUPTS:
        return True
    return new in _FORWARD.get(current, set())


def stage_progress(current: InvestigationState) -> List[Tuple[str, StageState]]:
    """The stage list for the status endpoint: every pipeline stage with its state.

    Stages before ``current`` are done, ``current`` is running (or needs input), later stages are pending. A
    failed or cancelled investigation shows every unfinished stage as pending, which is all that is known.
    """
    stages = PIPELINE[1:]  # CREATED is not a stage
    if current is S.REPORT_READY:
        return [(s.value, StageState.done) for s in stages]
    if current in TERMINAL:
        return [(s.value, StageState.pending) for s in stages]
    position = PIPELINE.index(S.PROFILE_BUILT if current is S.NEEDS_INPUT else current)
    out: List[Tuple[str, StageState]] = []
    for s in stages:
        index = PIPELINE.index(s)
        if index < position:
            out.append((s.value, StageState.done))
        elif index == position:
            out.append((s.value, StageState.needs_input if current is S.NEEDS_INPUT else StageState.running))
        else:
            out.append((s.value, StageState.pending))
    return out
