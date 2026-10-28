from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, upload
from app.config import settings
from app.db import connect
from app.parsers import build_default_registry


def create_app(conn=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal conn
        owns_conn = conn is None
        if conn is None:
            conn = connect(settings.duckdb_path)
        app.state.conn = conn
        app.state.registry = build_default_registry()
        yield
        if owns_conn:
            conn.close()

    application = FastAPI(title="Data Ingestion API", lifespan=lifespan)
    application.include_router(health.router)
    application.include_router(upload.router)
    return application


app = create_app()
