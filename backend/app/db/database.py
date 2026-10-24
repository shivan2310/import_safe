"""Async connection pool for Supabase Postgres, using asyncpg directly.

DATABASE_URL comes from the environment. The URL holds credentials, so it is never
logged or put in an error message: only the host is. See docs/decisions.md section 10.
"""
import asyncio
import json
import logging
import os
import re
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlsplit

import asyncpg

logger = logging.getLogger(__name__)

# Supabase Nano allows 15 connections in total. Keep this app to 5 so migrations, local development
# and Supabase's own internal connections still have room.
MIN_POOL_SIZE = 1
MAX_POOL_SIZE = 5
CLOSE_TIMEOUT_S = 10.0

_SCHEMA_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
UNKNOWN_HOST = "<unknown host>"


class DatabaseConfigError(RuntimeError):
    """DATABASE_URL is missing or the pool settings are invalid."""


class DatabaseConnectionError(RuntimeError):
    """The pool could not be created. The message names the host only."""


def safe_host(dsn: Optional[str]) -> str:
    """The host part of a connection string, for logs. Never returns credentials."""
    if not dsn:
        return UNKNOWN_HOST
    try:
        host = urlsplit(dsn).hostname
    except ValueError:
        return UNKNOWN_HOST
    return host or UNKNOWN_HOST


def database_url_from_env() -> str:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise DatabaseConfigError("DATABASE_URL is not set")
    return dsn


def _reject_floats(node: Any) -> None:
    if isinstance(node, float):
        raise ValueError("floats are not stored in JSON columns; use a Decimal string for money")
    if isinstance(node, dict):
        for value in node.values():
            _reject_floats(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _reject_floats(value)


def encode_jsonb(value: Any) -> str:
    _reject_floats(value)
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def decode_jsonb(text: str) -> Any:
    # A JSON number that has a fraction comes back as Decimal, never float.
    return json.loads(text, parse_float=Decimal)


class Database:
    """Owns one asyncpg pool. `search_path` is for tests (a separate schema)."""

    def __init__(self, dsn: Optional[str] = None, *, search_path: Optional[str] = None,
                 min_size: int = MIN_POOL_SIZE, max_size: int = MAX_POOL_SIZE) -> None:
        if search_path is not None and not _SCHEMA_NAME_RE.match(search_path):
            raise DatabaseConfigError("invalid search_path schema name")
        if not (0 < min_size <= max_size):
            raise DatabaseConfigError("pool sizes must satisfy 0 < min_size <= max_size")
        self._dsn = dsn if dsn is not None else database_url_from_env()
        self._search_path = search_path
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    def __repr__(self) -> str:
        return f"Database(host={safe_host(self._dsn)!r})"

    @property
    def host(self) -> str:
        return safe_host(self._dsn)

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        await conn.set_type_codec("jsonb", encoder=encode_jsonb, decoder=decode_jsonb, schema="pg_catalog")

    async def connect(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        logger.info("connecting to database host %s", self.host)
        # Pass search_path as a startup parameter so it survives pgBouncer session reuse.
        server_settings = {}
        if self._search_path is not None:
            server_settings["search_path"] = self._search_path
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                init=self._init_connection,
                # Works with Supabase's session pooler (pgbouncer) as well as direct connections.
                statement_cache_size=0,
                **({"server_settings": server_settings} if server_settings else {}),
            )
        except Exception as exc:
            # Only the host and the error class: the original message and chain are dropped on purpose.
            logger.error("could not connect to database host %s (%s)", self.host, type(exc).__name__)
            raise DatabaseConnectionError(f"could not connect to database host {self.host}") from None
        return self._pool

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise DatabaseConfigError("database is not connected; call connect() first")
        return self._pool

    async def close(self) -> None:
        """Graceful shutdown: wait for connections to be released, then force-close if it takes too long."""
        pool, self._pool = self._pool, None
        if pool is None:
            return
        try:
            await asyncio.wait_for(pool.close(), timeout=CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("database pool did not close in %.0fs; terminating it", CLOSE_TIMEOUT_S)
            pool.terminate()
        logger.info("database pool closed (host %s)", self.host)


_database: Optional[Database] = None


async def init_pool() -> asyncpg.Pool:
    """Create the application-wide pool from DATABASE_URL (call from the app's startup)."""
    global _database
    if _database is None:
        _database = Database()
    return await _database.connect()


def get_pool() -> asyncpg.Pool:
    if _database is None:
        raise DatabaseConfigError("database is not connected; call init_pool() first")
    return _database.pool


async def close_pool() -> None:
    """Call from the app's shutdown."""
    global _database
    database, _database = _database, None
    if database is not None:
        await database.close()
