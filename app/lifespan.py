import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.db.session import create_database
from app.services.telegram import poll_telegram_links
from app.storage.configure import check_buckets


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = create_database(app.state.settings)
    app.state.engine = database.engine
    app.state.session_factory = database.session_factory
    telegram_task = None
    try:
        await run_in_threadpool(check_buckets)
        settings = app.state.settings
        if settings.telegram_bot_token:
            telegram_task = asyncio.create_task(
                poll_telegram_links(
                    database.session_factory,
                    settings.telegram_bot_token.get_secret_value(),
                    settings.telegram_proxy_url,
                    settings.allowed_origins,
                )
            )
        yield
    finally:
        if telegram_task is not None:
            telegram_task.cancel()
            with suppress(asyncio.CancelledError):
                await telegram_task
        await database.engine.dispose()
