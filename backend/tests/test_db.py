"""Storage tests (docs/decisions.md section 10).

Pure tests (sessions, ULIDs, money, validation, schema text, log safety) always run. Tests that need
a real Postgres skip unless DATABASE_URL is set (in the environment, or in backend/.env, which is read
without changing os.environ). They run in a throwaway schema `test_<16 hex>` that is dropped afterwards.
"""
import ast
import asyncio
import json
import logging
import os
import re
import secrets
import warnings
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
from dotenv import dotenv_values
from pydantic import ValidationError
from ulid import ULID

from app.db import database, migrations, repositories as repo, session
from app.db.database import Database, DatabaseConfigError, DatabaseConnectionError, safe_host
from app.db.ids import InvalidIdError, is_valid_ulid, new_ulid, require_ulid
from app.db.migrations import SCHEMA_SQL, TABLES, create_tables
from app.decision.enums import FactKind, Outcome, RiskLevel
from app.decision.report_builder import assemble_report
from app.decision.report_schema import FullReport
from tests.fixtures.demo_report_inputs import demo_cost, demo_inputs

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL") or dotenv_values(BACKEND_DIR / ".env").get("DATABASE_URL")
SKIP_MESSAGE = ("DATABASE_URL is not set, so the database tests are skipped. Set it to a Supabase/Postgres "
                "connection string to run them (they use a temporary schema and drop it afterwards).")
if not DATABASE_URL:
    print(SKIP_MESSAGE)
    warnings.warn(SKIP_MESSAGE, UserWarning)
requires_db = pytest.mark.skipif(not DATABASE_URL, reason=SKIP_MESSAGE)

TEST_SCHEMA_RE = re.compile(r"^test_[0-9a-f]{16}$")
NOW = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)
SECRET = "k" * 40


# ---------------------------------------------------------------------------
# ULIDs
# ---------------------------------------------------------------------------

def test_new_ulid_is_valid_and_matches_the_library():
    value = new_ulid()
    assert len(value) == 26 and is_valid_ulid(value)
    assert str(ULID.from_str(value)) == value


def test_new_ulids_are_unique_and_sort_by_time():
    earlier = str(ULID.from_timestamp(1_700_000_000))
    later = str(ULID.from_timestamp(1_800_000_000))
    assert earlier < later
    assert len({new_ulid() for _ in range(200)}) == 200


@pytest.mark.parametrize("bad", [
    "", "abc", 123, None, b"01M5QH75WZQ17WBMV86QDYXVE8",
    "01m5qh75wzq17wbmv86qdyxve8",        # lowercase
    "01M5QH75WZQ17WBMV86QDYXVE",         # 25 chars
    "01M5QH75WZQ17WBMV86QDYXVE88",       # 27 chars
    "81M5QH75WZQ17WBMV86QDYXVE8",        # first char above 7
    "01M5QH75WZQ17WBMV86QDYXVEI",        # I is not in Crockford base32
    "01M5QH75WZQ17WBMV86QDYXVEU",        # U is not
])
def test_invalid_ulids_are_rejected(bad):
    assert not is_valid_ulid(bad)
    with pytest.raises(InvalidIdError):
        require_ulid(bad)


# ---------------------------------------------------------------------------
# Session cookie
# ---------------------------------------------------------------------------

def test_session_id_round_trips_through_the_cookie_signer():
    session_id = new_ulid()
    cookie = session.sign_session(session_id, SECRET)
    assert cookie.startswith(session_id + ".") and len(cookie) == 26 + 1 + 64
    assert session.verify_session(cookie, SECRET) == session_id
    assert session.resolve_session(cookie, SECRET) == (session_id, False)


def test_signing_is_deterministic_per_secret():
    session_id = new_ulid()
    assert session.sign_session(session_id, SECRET) == session.sign_session(session_id, SECRET)
    assert session.sign_session(session_id, SECRET) != session.sign_session(session_id, "j" * 40)


@pytest.mark.parametrize("cookie", [None, "", "no-dot", ".", "a.b", 123])
def test_missing_or_malformed_cookie_gets_a_new_valid_session(cookie):
    session_id, is_new = session.resolve_session(cookie, SECRET)
    assert is_new is True and is_valid_ulid(session_id)


def test_tampered_cookies_are_rejected():
    session_id = new_ulid()
    cookie = session.sign_session(session_id, SECRET)
    other = new_ulid()
    flipped_sig = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
    assert session.verify_session(flipped_sig, SECRET) is None
    assert session.verify_session(other + cookie[26:], SECRET) is None          # signature for another id
    assert session.verify_session(cookie[:-5], SECRET) is None                    # truncated
    assert session.verify_session(cookie + "00", SECRET) is None                  # extended
    assert session.verify_session(session.sign_session(session_id, "j" * 40), SECRET) is None  # other key
    assert session.verify_session(cookie.lower(), SECRET) is None                 # id must be canonical
    assert session.verify_session(session_id + "." + "é" * 64, SECRET) is None    # non-ascii signature
    assert session.verify_session("x" * 500, SECRET) is None


def test_invalid_cookie_is_replaced_not_reused():
    session_id = new_ulid()
    cookie = session.sign_session(session_id, SECRET)
    new_id, is_new = session.resolve_session(cookie[:-1] + "x", SECRET)
    assert is_new and new_id != session_id


@pytest.mark.parametrize("secret", ["", "short", "k" * 31])
def test_short_or_missing_secret_is_a_configuration_error(secret, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secret)
    for call in (lambda: session.sign_session(new_ulid()), lambda: session.verify_session("x"),
                 lambda: session.resolve_session(None)):
        with pytest.raises(session.SessionConfigError) as info:
            call()
        assert secret not in str(info.value) or secret == ""


def test_secret_is_read_from_the_environment_when_not_passed(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", SECRET)
    session_id = new_ulid()
    assert session.verify_session(session.sign_session(session_id), None) == session_id
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(session.SessionConfigError):
        session.verify_session("x")


def test_sign_rejects_a_non_ulid_session_id():
    with pytest.raises(ValueError):
        session.sign_session("not-a-ulid", SECRET)


def test_cookie_attributes():
    attrs = session.cookie_attributes(3600)
    assert attrs == {"max_age": 3600, "httponly": True, "samesite": "lax", "secure": True, "path": "/"}
    assert session.cookie_attributes(60, secure=False)["secure"] is False
    with pytest.raises(ValueError):
        session.cookie_attributes(0)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, text", [
    ("1542.88", "1542.88"),
    (Decimal("1542.88"), "1542.88"),
    (Decimal("0.10"), "0.10"),            # trailing zero kept
    (Decimal("1E+3"), "1000"),            # no exponent form
    (5, "5"),
    ("0", "0"),
])
def test_money_text_is_an_exact_decimal_string(value, text):
    assert repo.money_text(value) == text


@pytest.mark.parametrize("bad", [1.5, 0.1, True, None, [], "abc", "", "NaN", "Infinity", Decimal("NaN")])
def test_money_text_rejects_floats_and_non_numbers(bad):
    with pytest.raises(ValueError):
        repo.money_text(bad)


def test_money_columns_are_text_and_nothing_uses_a_float_type():
    sql = SCHEMA_SQL.upper()
    for bad in ("FLOAT", "REAL", "DOUBLE", "NUMERIC", "DECIMAL", "MONEY"):
        assert bad not in sql
    for column in ("shipping_amount", "insurance", "other_charges", "fx_rate", "low", "expected", "high",
                   "per_unit_expected"):
        assert re.search(rf"^\s+{column} TEXT,?$", SCHEMA_SQL, re.MULTILINE), column


def test_jsonb_codec_never_produces_or_accepts_floats():
    with pytest.raises(ValueError):
        database.encode_jsonb({"cost": {"expected": 1542.88}})
    with pytest.raises(ValueError):
        database.encode_jsonb([1, [2, 0.5]])
    assert database.encode_jsonb({"expected": "1542.88", "n": 3}) == '{"expected":"1542.88","n":3}'
    decoded = database.decode_jsonb('{"a": 1.50, "b": 2, "c": "1.50"}')
    assert decoded["a"] == Decimal("1.50") and isinstance(decoded["a"], Decimal)
    assert isinstance(decoded["b"], int) and decoded["c"] == "1.50"


# ---------------------------------------------------------------------------
# Schema text
# ---------------------------------------------------------------------------

def test_schema_defines_exactly_the_expected_tables():
    created = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA_SQL)
    assert created == list(TABLES)
    assert set(TABLES) == {"investigations", "order_inputs", "facts", "evidence", "questions", "reports",
                           "cost_estimates", "raw_snapshots"}


def test_every_child_table_cascades_and_has_rls_and_no_schema_qualification():
    assert SCHEMA_SQL.count("REFERENCES investigations(id) ON DELETE CASCADE") == len(TABLES) - 1
    for table in TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in SCHEMA_SQL
    assert "public." not in SCHEMA_SQL and "CREATE POLICY" not in SCHEMA_SQL


def test_reports_has_the_report_json_column_and_order_inputs_a_primary_key():
    assert re.search(r"CREATE TABLE IF NOT EXISTS reports \(.*?report_json JSONB\s*\);", SCHEMA_SQL, re.DOTALL)
    assert re.search(r"CREATE TABLE IF NOT EXISTS order_inputs \(\s*investigation_id TEXT PRIMARY KEY",
                     SCHEMA_SQL)


def test_indexes_cover_session_and_child_investigation_ids():
    for name in ("idx_investigations_session_id", "idx_facts_investigation_id", "idx_evidence_investigation_id",
                 "idx_questions_investigation_id", "idx_raw_snapshots_investigation_id"):
        assert f"CREATE INDEX IF NOT EXISTS {name}" in SCHEMA_SQL


# ---------------------------------------------------------------------------
# Connection settings and log safety (no database needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dsn, host", [
    ("postgresql://user:pw@db.abc.supabase.co:5432/postgres", "db.abc.supabase.co"),
    ("postgres://postgres.abc:p%40ss%3Aword@aws-0-ap.pooler.supabase.com:6543/postgres?sslmode=require",
     "aws-0-ap.pooler.supabase.com"),
    ("postgresql://user:p@ss@host.example/db", "host.example"),
    ("postgresql://u:p@[::1]:5432/db", "::1"),
    ("postgresql:///db", database.UNKNOWN_HOST),
    ("", database.UNKNOWN_HOST),
    (None, database.UNKNOWN_HOST),
    ("not a url", database.UNKNOWN_HOST),
])
def test_safe_host_returns_only_the_host(dsn, host):
    assert safe_host(dsn) == host


def test_missing_database_url_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigError):
        Database()


@pytest.mark.parametrize("name", ["", "Test", "a;drop", 'a"b', "1abc", "x" * 64, "a b"])
def test_bad_search_path_names_are_rejected(name):
    with pytest.raises(DatabaseConfigError):
        Database("postgresql://u:p@h/db", search_path=name)


def test_pool_defaults_and_size_validation():
    assert (database.MIN_POOL_SIZE, database.MAX_POOL_SIZE) == (1, 5)
    for lo, hi in ((0, 5), (5, 2)):
        with pytest.raises(DatabaseConfigError):
            Database("postgresql://u:p@h/db", min_size=lo, max_size=hi)


def test_repr_and_failed_connection_never_expose_credentials(caplog):
    password = "s3cret-pw-9f2"
    dsn = f"postgresql://appuser:{password}@127.0.0.1:1/postgres"
    db = Database(dsn)
    assert password not in repr(db) and "127.0.0.1" in repr(db)
    with caplog.at_level(logging.DEBUG, logger="app.db.database"):
        with pytest.raises(DatabaseConnectionError) as info:
            asyncio.run(db.connect())
    assert password not in str(info.value) and "appuser" not in str(info.value)
    assert "127.0.0.1" in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert password not in caplog.text and "appuser" not in caplog.text and dsn not in caplog.text
    assert "127.0.0.1" in caplog.text


def test_closing_a_pool_that_was_never_opened_is_harmless():
    asyncio.run(Database("postgresql://u:p@h/db").close())


# ---------------------------------------------------------------------------
# Input validation (runs before any query, so no database is needed)
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def _create(**overrides):
    kwargs = dict(url="https://seller.example/x", session_id=new_ulid(), status="pending", created_at=NOW)
    kwargs.update(overrides)
    return repo.create_investigation(None, **kwargs)


def test_create_investigation_validates_before_touching_the_database():
    with pytest.raises(InvalidIdError):
        run(_create(id="not-a-ulid"))
    with pytest.raises(InvalidIdError):
        run(_create(session_id="abc"))
    with pytest.raises(ValueError):
        run(_create(created_at=datetime(2026, 10, 24)))
    with pytest.raises(ValueError):
        run(_create(expires_at=datetime(2026, 11, 24)))
    for quantity in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            run(_create(quantity=quantity))
    with pytest.raises(ValueError):
        run(_create(url="  "))


@pytest.mark.parametrize("call", [
    lambda: repo.get_investigation(None, "x"),
    lambda: repo.soft_delete(None, "x", NOW),
    lambda: repo.hard_delete(None, "x"),
    lambda: repo.list_by_session(None, "x"),
    lambda: repo.list_facts(None, "x"),
    lambda: repo.list_evidence(None, "x"),
    lambda: repo.list_questions(None, "x"),
    lambda: repo.get_report(None, "x"),
    lambda: repo.get_cost_estimate(None, "x"),
])
def test_every_function_rejects_a_non_ulid_id(call):
    with pytest.raises(InvalidIdError):
        run(call())


def test_soft_delete_needs_an_aware_timestamp():
    with pytest.raises(ValueError):
        run(repo.soft_delete(None, new_ulid(), datetime(2026, 10, 24)))


def test_row_inputs_are_validated():
    ok = dict(field="battery", value="2000mAh", kind=FactKind.seller_claim)
    repo.FactIn(**ok)
    with pytest.raises(ValidationError):
        repo.FactIn(**dict(ok, id="abc"))
    with pytest.raises(ValidationError):
        repo.FactIn(**dict(ok, evidence_id="ev_1"))
    with pytest.raises(ValidationError):
        repo.FactIn(**dict(ok, value=1.5))
    with pytest.raises(ValidationError):
        repo.FactIn(**dict(ok, kind="guess"))
    with pytest.raises(ValidationError):
        repo.FactIn(**dict(ok, field=" "))
    evidence = dict(source_url="https://x.example", retrieved_at=NOW, source_type="listing")
    repo.EvidenceIn(**evidence)
    with pytest.raises(ValidationError):
        repo.EvidenceIn(**dict(evidence, retrieved_at=datetime(2026, 10, 24)))
    with pytest.raises(ValidationError):
        repo.EvidenceIn(**dict(evidence, source_type="forum"))
    question = dict(field="quantity", prompt="How many units?", created_at=NOW)
    assert repo.QuestionIn(**question).status == repo.QUESTION_OPEN
    with pytest.raises(ValidationError):
        repo.QuestionIn(**dict(question, status="done"))


def test_save_report_and_cost_estimate_validate_first():
    base = dict(outcome=Outcome.conditional_import, risk_level=RiskLevel.high, score=10, next_actions=[],
                generated_at=NOW, rule_set_versions=[])
    with pytest.raises(ValueError):
        run(repo.save_report(None, new_ulid(), **dict(base, outcome="great")))
    with pytest.raises(ValueError):
        run(repo.save_report(None, new_ulid(), **dict(base, score=True)))
    with pytest.raises(ValueError):
        run(repo.save_report(None, new_ulid(), **dict(base, generated_at=datetime(2026, 1, 1))))
    money = dict(assumptions=[], breakdown=[], low="1", expected="2", high="3", per_unit_expected="0.5")
    with pytest.raises(ValueError):
        run(repo.save_cost_estimate(None, new_ulid(), **dict(money, expected=1542.88)))


def test_db_modules_use_no_eval_or_exec_and_no_forbidden_words():
    for path in (BACKEND_DIR / "app" / "db").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
        assert not names & {"eval", "exec", "compile", "__import__"}, path.name
        assert "fraud" not in source.lower() and "fake" not in source.lower(), path.name


# ---------------------------------------------------------------------------
# Database tests (skipped without DATABASE_URL)
# ---------------------------------------------------------------------------

class DbRunner:
    """Runs one coroutine against a pool whose search_path is a throwaway schema."""

    def __init__(self, schema: str) -> None:
        self.schema = schema

    def run(self, body):
        async def main():
            db = Database(DATABASE_URL, search_path=self.schema)
            pool = await db.connect()
            try:
                await create_tables(pool)
                return await body(pool)
            finally:
                await db.close()

        return asyncio.run(main())


async def _admin(sql: str) -> None:
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture()
def db():
    schema = "test_" + secrets.token_hex(8)
    assert TEST_SCHEMA_RE.match(schema)
    asyncio.run(_admin(f'CREATE SCHEMA "{schema}"'))
    try:
        yield DbRunner(schema)
    finally:
        assert TEST_SCHEMA_RE.match(schema)  # never drop anything that is not a throwaway test schema
        asyncio.run(_admin(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


async def _new(pool, **overrides):
    kwargs = dict(url="https://seller.example/listing/bt-100", session_id=new_ulid(), status="pending",
                  created_at=NOW)
    kwargs.update(overrides)
    return await repo.create_investigation(pool, **kwargs)


async def _count(pool, table: str, investigation_id: str) -> int:
    column = "id" if table == "investigations" else "investigation_id"
    return await pool.fetchval(f"SELECT count(*) FROM {table} WHERE {column} = $1", investigation_id)


@requires_db
def test_create_and_retrieve_an_investigation(db):
    async def body(pool):
        session_id = new_ulid()
        created = await _new(
            pool, session_id=session_id, normalized_url="https://seller.example/listing/bt-100", quantity=100,
            destination={"country": "IN", "pincode": "110001"}, purpose="resale", variant="black",
            expires_at=NOW + timedelta(days=30),
        )
        assert is_valid_ulid(created.id)
        fetched = await repo.get_investigation(pool, created.id)
        assert fetched == created
        assert fetched.quantity == 100 and fetched.destination == {"country": "IN", "pincode": "110001"}
        assert fetched.created_at == NOW and fetched.expires_at == NOW + timedelta(days=30)
        assert await repo.get_investigation(pool, created.id, session_id=session_id) == created
        assert await repo.get_investigation(pool, created.id, session_id=new_ulid()) is None
        assert await repo.get_investigation(pool, new_ulid()) is None
        assert await repo.update_investigation_status(pool, created.id, "running") is True
        assert (await repo.get_investigation(pool, created.id)).status == "running"
        assert await repo.update_investigation_status(pool, new_ulid(), "running") is False

    db.run(body)


@requires_db
def test_a_second_create_with_the_same_id_is_rejected(db):
    async def body(pool):
        first = await _new(pool, purpose="resale")
        with pytest.raises(repo.DuplicateIdError):
            await _new(pool, id=first.id, purpose="personal")
        assert (await repo.get_investigation(pool, first.id)).purpose == "resale"
        # the pool is still usable after the rejected insert
        assert await repo.get_investigation(pool, first.id) is not None

    db.run(body)


@requires_db
def test_soft_delete_hides_the_investigation_and_everything_under_it(db):
    async def body(pool):
        session_id = new_ulid()
        keep = await _new(pool, session_id=session_id, created_at=NOW)
        gone = await _new(pool, session_id=session_id, created_at=NOW + timedelta(minutes=1))
        await repo.save_facts(pool, gone.id, [repo.FactIn(field="title", value="Speaker", kind=FactKind.confirmed)])
        await repo.save_evidence(pool, gone.id, [repo.EvidenceIn(source_url="https://x.example",
                                                                 retrieved_at=NOW, source_type="listing")])
        await repo.save_question(pool, gone.id, repo.QuestionIn(field="quantity", prompt="How many?", created_at=NOW))
        await repo.save_report(pool, gone.id, outcome=Outcome.conditional_import, risk_level=RiskLevel.high,
                               score=7, next_actions=[], generated_at=NOW, rule_set_versions=[])
        await repo.save_cost_estimate(pool, gone.id, assumptions=[], breakdown=[], low="1", expected="2",
                                      high="3", per_unit_expected="0.02")
        assert [i.id for i in await repo.list_by_session(pool, session_id)] == [gone.id, keep.id]

        assert await repo.soft_delete(pool, gone.id, NOW + timedelta(hours=1)) is True

        assert await repo.get_investigation(pool, gone.id) is None
        assert [i.id for i in await repo.list_by_session(pool, session_id)] == [keep.id]
        assert await repo.list_facts(pool, gone.id) == []
        assert await repo.list_evidence(pool, gone.id) == []
        assert await repo.list_questions(pool, gone.id) == []
        assert await repo.get_report(pool, gone.id) is None
        assert await repo.get_cost_estimate(pool, gone.id) is None
        assert await repo.soft_delete(pool, gone.id, NOW) is False            # already hidden
        assert await repo.update_investigation_status(pool, gone.id, "x") is False
        # the rows are still there until a hard delete
        assert await _count(pool, "facts", gone.id) == 1

    db.run(body)


@requires_db
def test_hard_delete_removes_every_related_row_by_cascade(db):
    async def body(pool):
        target = await _new(pool)
        other = await _new(pool)
        for inv in (target, other):
            await repo.save_facts(pool, inv.id, [repo.FactIn(field="title", value="Speaker", kind=FactKind.confirmed)])
            await repo.save_evidence(pool, inv.id, [repo.EvidenceIn(source_url="https://x.example",
                                                                    retrieved_at=NOW, source_type="listing")])
            await repo.save_question(pool, inv.id, repo.QuestionIn(field="quantity", prompt="How many?",
                                                                   created_at=NOW))
            await repo.save_snapshot(pool, inv.id, task_id="task-1", url="https://x.example",
                                     content="page text", retrieved_at=NOW)
            await repo.save_report(pool, inv.id, outcome=Outcome.conditional_import, risk_level=RiskLevel.high,
                                   score=7, next_actions=[], generated_at=NOW, rule_set_versions=[])
            await repo.save_cost_estimate(pool, inv.id, assumptions=[], breakdown=[], low="1", expected="2",
                                          high="3", per_unit_expected="0.02")
            await pool.execute("INSERT INTO order_inputs (investigation_id, shipping_amount, fx_rate) "
                               "VALUES ($1, '12000', '90')", inv.id)
        for table in migrations.TABLES:
            assert await _count(pool, table, target.id) == 1, table

        assert await repo.hard_delete(pool, target.id) is True

        for table in migrations.TABLES:
            assert await _count(pool, table, target.id) == 0, table
            assert await _count(pool, table, other.id) == 1, table   # other investigations untouched
        assert await repo.hard_delete(pool, target.id) is False

    db.run(body)


@requires_db
def test_hard_delete_also_removes_a_soft_deleted_investigation(db):
    async def body(pool):
        inv = await _new(pool)
        await repo.save_facts(pool, inv.id, [repo.FactIn(field="title", value="Speaker", kind=FactKind.confirmed)])
        await repo.soft_delete(pool, inv.id, NOW)
        assert await repo.hard_delete(pool, inv.id) is True
        assert await _count(pool, "investigations", inv.id) == 0
        assert await _count(pool, "facts", inv.id) == 0

    db.run(body)


@requires_db
def test_money_round_trips_as_a_decimal_string_without_float_conversion(db):
    estimate = demo_cost()
    dump = estimate.model_dump(mode="json")

    async def body(pool):
        inv = await _new(pool)
        await repo.save_cost_estimate(
            pool, inv.id, assumptions=dump["assumptions"], breakdown=dump["breakdown"],
            low=estimate.low, expected=estimate.expected, high=estimate.high,
            per_unit_expected=estimate.per_unit_expected,
        )
        row = await repo.get_cost_estimate(pool, inv.id)
        assert row.expected == "154287.59" and row.per_unit_expected == "1542.88"
        assert (row.low, row.high) == (str(estimate.low), str(estimate.high))
        assert Decimal(row.expected) == estimate.expected
        assert row.breakdown == dump["breakdown"] and row.assumptions == dump["assumptions"]
        assert all(isinstance(line["amount"], str) for line in row.breakdown)
        types = await pool.fetchrow("SELECT pg_typeof(low)::text AS a, pg_typeof(expected)::text AS b, "
                                    "pg_typeof(high)::text AS c, pg_typeof(per_unit_expected)::text AS d "
                                    "FROM cost_estimates WHERE investigation_id = $1", inv.id)
        assert set(types.values()) == {"text"}
        # exactness: trailing zeros and many digits survive
        await repo.save_cost_estimate(pool, inv.id, assumptions=[], breakdown=[], low=Decimal("0.10"),
                                      expected="1234567890123456789.123456789", high=5, per_unit_expected="0.00")
        again = await repo.get_cost_estimate(pool, inv.id)
        assert (again.low, again.expected, again.high, again.per_unit_expected) == (
            "0.10", "1234567890123456789.123456789", "5", "0.00")
        with pytest.raises(ValueError):
            await repo.save_cost_estimate(pool, inv.id, assumptions=[], breakdown=[], low="1", expected=1542.88,
                                          high="3", per_unit_expected="1")
        with pytest.raises(ValueError):
            await repo.save_cost_estimate(pool, inv.id, assumptions=[{"value": 0.5}], breakdown=[], low="1",
                                          expected="2", high="3", per_unit_expected="1")
        assert (await repo.get_cost_estimate(pool, inv.id)).expected == "1234567890123456789.123456789"

    db.run(body)


@requires_db
def test_the_full_report_snapshot_round_trips(db):
    report = assemble_report(**demo_inputs())

    async def body(pool):
        inv = await _new(pool)
        await repo.save_report(
            pool, inv.id, outcome=report.outcome, risk_level=report.risk_level, score=report.score,
            next_actions=[a.model_dump(mode="json", by_alias=True) for a in report.next_actions],
            generated_at=NOW, rule_set_versions=report.rule_versions, report_json=report.to_frontend(),
        )
        row = await repo.get_report(pool, inv.id)
        assert (row.outcome, row.risk_level, row.score) == (Outcome.conditional_import, RiskLevel.high, 10)
        assert row.generated_at == NOW and row.rule_set_versions == report.rule_versions
        assert FullReport.model_validate(row.report_json) == report
        assert row.report_json["cost"]["perUnitExpected"] == "1542.88"
        # saving again replaces the row
        await repo.save_report(pool, inv.id, outcome=Outcome.likely_importable, risk_level=RiskLevel.low, score=0,
                               next_actions=[], generated_at=NOW, rule_set_versions=[])
        replaced = await repo.get_report(pool, inv.id)
        assert replaced.outcome is Outcome.likely_importable and replaced.report_json is None
        assert await pool.fetchval("SELECT count(*) FROM reports") == 1

    db.run(body)


@requires_db
def test_list_by_session_is_scoped_and_newest_first(db):
    async def body(pool):
        mine, theirs = new_ulid(), new_ulid()
        first = await _new(pool, session_id=mine, created_at=NOW)
        second = await _new(pool, session_id=mine, created_at=NOW + timedelta(minutes=5))
        await _new(pool, session_id=theirs)
        assert [i.id for i in await repo.list_by_session(pool, mine)] == [second.id, first.id]
        assert await repo.list_by_session(pool, new_ulid()) == []

    db.run(body)


@requires_db
def test_facts_evidence_questions_and_snapshots(db):
    async def body(pool):
        inv = await _new(pool)
        evidence = repo.EvidenceIn(source_url="https://seller.example/x", retrieved_at=NOW, excerpt="BIS R-41234567",
                                   source_type="listing")
        await repo.save_evidence(pool, inv.id, [evidence])
        facts = [
            repo.FactIn(field="title", value="Speaker", kind=FactKind.confirmed, evidence_id=evidence.id),
            repo.FactIn(field="has_bluetooth", value=True, kind=FactKind.confirmed, evidence_id=evidence.id),
            repo.FactIn(field="quantity", value=100, kind=FactKind.user_supplied),
        ]
        await repo.save_facts(pool, inv.id, facts)
        rows = {f.field: f for f in await repo.list_facts(pool, inv.id)}
        assert rows["title"].value == "Speaker" and rows["title"].evidence_id == evidence.id
        assert rows["has_bluetooth"].value == "true" and rows["quantity"].value == "100"
        assert rows["quantity"].kind is FactKind.user_supplied
        listed = await repo.list_evidence(pool, inv.id)
        assert [(e.id, e.excerpt, e.source_type) for e in listed] == [(evidence.id, "BIS R-41234567", "listing")]

        question = repo.QuestionIn(field="quantity", prompt="How many units?", why_it_matters="Affects risk",
                                   created_at=NOW)
        await repo.save_question(pool, inv.id, question)
        assert (await repo.list_questions(pool, inv.id))[0].status == repo.QUESTION_OPEN
        assert await repo.update_question_answer(pool, inv.id, question.id, "100") is True
        answered = (await repo.list_questions(pool, inv.id))[0]
        assert (answered.answer, answered.status) == ("100", repo.QUESTION_ANSWERED)
        assert await repo.update_question_answer(pool, new_ulid(), question.id, "5") is False  # wrong investigation
        assert await repo.update_question_answer(pool, inv.id, new_ulid(), "5") is False

        snapshot_id = await repo.save_snapshot(pool, inv.id, task_id="task-1", url="https://seller.example/x",
                                               content="<html>page text</html>", retrieved_at=NOW)
        assert is_valid_ulid(snapshot_id)
        assert await pool.fetchval("SELECT content FROM raw_snapshots WHERE id = $1", snapshot_id) \
            == "<html>page text</html>"

    db.run(body)


@requires_db
def test_a_batch_with_a_duplicate_id_saves_nothing(db):
    async def body(pool):
        inv = await _new(pool)
        fact = repo.FactIn(field="title", value="Speaker", kind=FactKind.confirmed)
        other = repo.FactIn(id=new_ulid(), field="color", value="black", kind=FactKind.seller_claim)
        with pytest.raises(repo.DuplicateIdError):
            await repo.save_facts(pool, inv.id, [fact, other, fact])
        assert await repo.list_facts(pool, inv.id) == []
        await repo.save_facts(pool, inv.id, [fact])
        with pytest.raises(repo.DuplicateIdError):
            await repo.save_facts(pool, inv.id, [other, fact])
        assert [f.id for f in await repo.list_facts(pool, inv.id)] == [fact.id]

    db.run(body)


@requires_db
def test_writing_under_an_unknown_investigation_is_rejected(db):
    async def body(pool):
        missing = new_ulid()
        with pytest.raises(repo.InvestigationNotFoundError):
            await repo.save_facts(pool, missing, [repo.FactIn(field="a", value="b", kind=FactKind.confirmed)])
        with pytest.raises(repo.InvestigationNotFoundError):
            await repo.save_report(pool, missing, outcome=Outcome.likely_importable, risk_level=RiskLevel.low,
                                   score=0, next_actions=[], generated_at=NOW, rule_set_versions=[])
        with pytest.raises(repo.InvestigationNotFoundError):
            await repo.save_snapshot(pool, missing, task_id="t", url="https://x.example", content="c",
                                     retrieved_at=NOW)

    db.run(body)


@requires_db
def test_schema_is_isolated_idempotent_and_hardened(db):
    async def body(pool):
        assert pool.get_min_size() == 1 and pool.get_max_size() == 5
        assert await pool.fetchval("SELECT current_schema()") == db.schema
        await create_tables(pool)  # running it again is harmless
        tables = await pool.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = $1",
                                  db.schema)
        assert {r["table_name"] for r in tables} == set(migrations.TABLES)
        rls = await pool.fetch("SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n "
                               "ON n.oid = c.relnamespace WHERE n.nspname = $1 AND c.relkind = 'r'", db.schema)
        assert {r["relname"]: r["relrowsecurity"] for r in rls} == {t: True for t in migrations.TABLES}
        policies = await pool.fetchval("SELECT count(*) FROM pg_policies WHERE schemaname = $1", db.schema)
        assert policies == 0
        indexes = {r["indexname"] for r in await pool.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname = $1", db.schema)}
        assert {"idx_investigations_session_id", "idx_facts_investigation_id", "idx_evidence_investigation_id",
                "idx_questions_investigation_id", "idx_raw_snapshots_investigation_id"} <= indexes

    db.run(body)


@requires_db
def test_the_pool_closes_gracefully(db):
    async def main():
        database_ = Database(DATABASE_URL, search_path=db.schema)
        pool = await database_.connect()
        assert await pool.fetchval("SELECT 1") == 1
        await database_.close()
        assert pool.is_closing()
        await database_.close()  # closing twice is harmless
        with pytest.raises(DatabaseConfigError):
            database_.pool

    asyncio.run(main())
