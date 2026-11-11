from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import create_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = create_database(app.state.settings)
    app.state.engine = database.engine
    app.state.session_factory = database.session_factory
    try:
        yield
    finally:
        await database.engine.dispose()
