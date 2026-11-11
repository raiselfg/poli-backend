from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.db.session import create_database
from app.storage.configure import configure_public_read


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = create_database(app.state.settings)
    app.state.engine = database.engine
    app.state.session_factory = database.session_factory
    try:
        await run_in_threadpool(configure_public_read)
        yield
    finally:
        await database.engine.dispose()
