"""Database schema. Runs as one transaction. See docs/decisions.md section 10 and PRD B4.

Table names are unqualified, so they are created in the first schema on the connection's
search_path (the tests point that at a throwaway schema). Money columns are TEXT holding
a Decimal string. Every child table cascades on delete. Row Level Security is enabled with
no policies, so Supabase's REST API (anon key) cannot read these tables; the direct
Postgres role used by this app bypasses RLS.
"""
from typing import Union

import asyncpg

TABLES = (
    "investigations",
    "order_inputs",
    "facts",
    "evidence",
    "questions",
    "reports",
    "cost_estimates",
    "raw_snapshots",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    url TEXT,
    normalized_url TEXT,
    quantity INTEGER,
    destination JSONB,
    purpose TEXT,
    variant TEXT,
    status TEXT,
    session_id TEXT,
    created_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS order_inputs (
    investigation_id TEXT PRIMARY KEY REFERENCES investigations(id) ON DELETE CASCADE,
    shipping_amount TEXT,
    shipping_currency TEXT,
    shipping_mode TEXT,
    insurance TEXT,
    other_charges TEXT,
    fx_rate TEXT,
    fx_source TEXT,
    fx_time TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    field TEXT,
    value TEXT,
    kind TEXT,
    evidence_id TEXT,
    confidence TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    source_url TEXT,
    retrieved_at TIMESTAMPTZ,
    excerpt TEXT,
    snapshot_ref TEXT,
    source_type TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    field TEXT,
    prompt TEXT,
    why_it_matters TEXT,
    answer TEXT,
    status TEXT,
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reports (
    investigation_id TEXT PRIMARY KEY REFERENCES investigations(id) ON DELETE CASCADE,
    outcome TEXT,
    risk_level TEXT,
    score INTEGER,
    next_actions JSONB,
    generated_at TIMESTAMPTZ,
    rule_set_versions JSONB,
    report_json JSONB
);

CREATE TABLE IF NOT EXISTS cost_estimates (
    investigation_id TEXT PRIMARY KEY REFERENCES investigations(id) ON DELETE CASCADE,
    assumptions JSONB,
    breakdown JSONB,
    low TEXT,
    expected TEXT,
    high TEXT,
    per_unit_expected TEXT
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    id TEXT PRIMARY KEY,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    task_id TEXT,
    url TEXT,
    content TEXT,
    retrieved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_investigations_session_id ON investigations (session_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_facts_investigation_id ON facts (investigation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_investigation_id ON evidence (investigation_id);
CREATE INDEX IF NOT EXISTS idx_questions_investigation_id ON questions (investigation_id);
CREATE INDEX IF NOT EXISTS idx_raw_snapshots_investigation_id ON raw_snapshots (investigation_id);

ALTER TABLE investigations ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_inputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_estimates ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_snapshots ENABLE ROW LEVEL SECURITY;
"""


async def create_tables(executor: Union[asyncpg.Pool, asyncpg.Connection]) -> None:
    """Create every table, index and RLS setting in a single transaction. Safe to run again."""
    if isinstance(executor, asyncpg.Pool):
        async with executor.acquire() as conn:
            await _run(conn)
    else:
        await _run(executor)


async def _run(conn: asyncpg.Connection) -> None:
    async with conn.transaction():
        await conn.execute(SCHEMA_SQL)
