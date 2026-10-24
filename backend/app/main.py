import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.investigations import router as investigations_router, get_store, get_connector
from app.errors import ImportSafeError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the database pool when DATABASE_URL is configured; skip it otherwise."""
    pool = None
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        try:
            from app.db.database import init_pool
            from app.db.migrations import create_tables
            from app.coordinator.pg_store import PostgresInvestigationStore
            from app.services.tinyfish.fixture_adapter import FixtureTinyFishConnector
            from app.services.tinyfish.live_adapter import LiveTinyFishConnector
            import app.api.investigations as inv_module

            pool = await init_pool()
            await create_tables(pool)

            # Swap in the Postgres store and the appropriate connector.
            inv_module._store = PostgresInvestigationStore(pool)
            allow_demo = os.environ.get("ALLOW_DEMO_FALLBACK", "false").lower() == "true"
            if allow_demo:
                live = LiveTinyFishConnector() if os.environ.get("TINYFISH_API_KEY") else None
                inv_module._connector = FixtureTinyFishConnector(live=live)
            elif os.environ.get("TINYFISH_API_KEY"):
                inv_module._connector = LiveTinyFishConnector()
            log.info("ImportSafe: database pool ready")
        except Exception:
            log.exception("ImportSafe: could not start database pool — investigations will use in-memory store")
    yield
    if pool:
        try:
            from app.db.database import close_pool
            await close_pool()
        except Exception:
            log.exception("ImportSafe: error closing pool")


app = FastAPI(title="ImportSafe API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(investigations_router)


@app.exception_handler(ImportSafeError)
def importsafe_error_handler(_: Request, exc: ImportSafeError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": exc.message}},
    )
