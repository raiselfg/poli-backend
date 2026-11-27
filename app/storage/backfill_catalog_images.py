import asyncio
import logging

from app.core.config import get_settings
from app.db.session import create_database
from app.repository.media import MediaRepository
from app.services.media import MediaService
from app.storage.s3 import S3Storage, get_storage_settings

logger = logging.getLogger(__name__)


async def main() -> int:
    storage = S3Storage(get_storage_settings())
    database = create_database(get_settings())
    updated = failed = 0
    try:
        async with database.session_factory() as db:
            ids = await MediaRepository(db).catalog_ids_without_variants()
        for media_id in ids:
            try:
                async with database.session_factory() as db:
                    updated += await MediaService(db, storage).backfill_variants(media_id)
            except Exception:
                logger.exception("Could not process catalog image %s", media_id)
                failed += 1
    finally:
        await database.engine.dispose()
    logger.info("Prepared images: %s. Failed images: %s.", updated, failed)
    return int(failed > 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
