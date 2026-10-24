"""Investigation expiry: soft-delete investigations older than MAX_AGE_DAYS (docs/prd-backend.md B11).

``expire_old_investigations`` is a pure async function that the caller drives on whatever schedule it
wants (e.g. an APScheduler job, a cron hit, or a test). It never reads the clock directly —
``as_of`` must be supplied by the caller.

For ``InMemoryStore``, expiry marks the state as EXPIRED (force_state). For the Postgres store the
caller should pass the pool and call the repository directly; see the module-level helper
``expire_in_db`` for that case.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.coordinator.states import InvestigationState, TERMINAL, RESTING
from app.coordinator.store import InvestigationStore, InMemoryStore

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 30


async def expire_old_investigations(store: InMemoryStore, as_of: Optional[datetime] = None) -> int:
    """Soft-expire CREATED/FAILED/NEEDS_INPUT investigations older than MAX_AGE_DAYS.

    Only works with ``InMemoryStore`` (the Postgres case uses SQL directly via ``expire_in_db``).
    Returns the number of investigations expired.
    """
    now = as_of or datetime.now(timezone.utc)
    expired = 0
    for investigation_id, record in list(store._records.items()):
        if record.state in TERMINAL or record.state == InvestigationState.REPORT_READY:
            continue
        # Events tell us when the investigation started (first event).
        events = record.events
        if not events:
            continue
        first_event = events[0]
        age_days = (now - first_event.at).days
        if age_days > MAX_AGE_DAYS:
            prev = await store.force_state(investigation_id, InvestigationState.EXPIRED)
            if prev is not None:
                log.info("expired investigation %s (age %d days)", investigation_id, age_days)
                expired += 1
    return expired


async def expire_in_db(pool, as_of: Optional[datetime] = None) -> int:
    """Soft-expire old investigations directly in Postgres.

    Sets ``deleted_at`` (soft delete) for investigations whose ``created_at`` is older than
    MAX_AGE_DAYS and that are not already deleted or REPORT_READY. Returns the count updated.
    """
    now = as_of or datetime.now(timezone.utc)
    cutoff = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    from datetime import timedelta
    expire_before = cutoff - timedelta(days=MAX_AGE_DAYS)
    result = await pool.execute(
        "UPDATE investigations SET deleted_at = $1, status = 'EXPIRED' "
        "WHERE deleted_at IS NULL AND status != 'REPORT_READY' "
        "AND created_at < $2",
        now, expire_before,
    )
    # asyncpg execute returns 'UPDATE N'
    try:
        count = int(result.split()[-1])
    except (ValueError, AttributeError, IndexError):
        count = 0
    log.info("expired %d old investigations in db (cutoff %s)", count, expire_before.date())
    return count
