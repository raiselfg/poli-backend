from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import CurrentSessionDep, MediaServiceDep
from app.api.files import FileTooLargeError, InvalidFileError, check_file, optimize_catalog_image
from app.schemas.media import MediaRead, MediaUpdate
from app.services.media import MediaInUseError, MediaNotFoundError

router = APIRouter(prefix="/admin/media", tags=["media"])


@router.get("", response_model=list[MediaRead])
async def list_media(current_session: CurrentSessionDep, service: MediaServiceDep):
    return await service.list()


@router.post("", response_model=MediaRead, status_code=201)
async def upload_media(
    current_session: CurrentSessionDep,
    service: MediaServiceDep,
    file: Annotated[UploadFile, File()],
):
    try:
        checked = await check_file(file, images_only=True)
    except FileTooLargeError:
        raise HTTPException(status_code=413, detail="File too large") from None
    except InvalidFileError:
        raise HTTPException(status_code=415, detail="Unsupported file") from None
    try:
        try:
            await run_in_threadpool(optimize_catalog_image, checked)
        except InvalidFileError:
            raise HTTPException(status_code=415, detail="Unsupported file") from None
        return await service.upload(
            checked.stream,
            checked.original_name,
            checked.mime_type,
            checked.size,
            checked.width,
            checked.height,
        )
    finally:
        checked.stream.close()
        await file.close()


@router.patch("/{media_id}", response_model=MediaRead)
async def update_media(
    media_id: UUID, body: MediaUpdate, current_session: CurrentSessionDep, service: MediaServiceDep
):
    try:
        return await service.update(media_id, body.alt)
    except MediaNotFoundError:
        raise HTTPException(status_code=404, detail="Media not found") from None


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: UUID, current_session: CurrentSessionDep, service: MediaServiceDep
):
    try:
        await service.delete(media_id)
    except MediaNotFoundError:
        raise HTTPException(status_code=404, detail="Media not found") from None
    except MediaInUseError:
        raise HTTPException(status_code=409, detail="Media is in use") from None
    return Response(status_code=204)
