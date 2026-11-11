from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import CurrentSessionDep, RequestServiceDep
from app.api.files import FileTooLargeError, InvalidFileError, check_file
from app.schemas.request import (
    RequestCreated,
    RequestDetail,
    RequestListItem,
    RequestStatus,
    RequestUpdate,
)
from app.services.request import RequestCategoryNotFoundError, RequestNotFoundError

router = APIRouter(tags=["requests"])


@router.post("/requests", status_code=201, response_model=RequestCreated)
async def create_request(
    service: RequestServiceDep,
    name: Annotated[str, Form(min_length=1, max_length=100)],
    phone: Annotated[str, Form(min_length=1, max_length=40)],
    comment: Annotated[str | None, Form()] = None,
    category_id: Annotated[UUID | None, Form(alias="categoryId")] = None,
    file: Annotated[list[UploadFile] | None, File()] = None,
):
    if not name.strip() or not phone.strip():
        raise HTTPException(status_code=422, detail="Name and phone must not be blank")
    if file is not None and len(file) > 1:
        raise HTTPException(status_code=400, detail="Only one file is allowed")
    checked = None
    try:
        if file:
            try:
                checked = await check_file(file[0], images_only=False)
            except FileTooLargeError:
                raise HTTPException(status_code=413, detail="File too large") from None
            except InvalidFileError:
                raise HTTPException(status_code=415, detail="Unsupported file") from None
        file_data = None
        if checked is not None:
            file_data = (
                checked.stream,
                checked.original_name,
                checked.mime_type,
                checked.size,
                checked.width,
                checked.height,
            )
        try:
            return await service.create(name, phone, comment, category_id, file_data)
        except RequestCategoryNotFoundError:
            raise HTTPException(status_code=404, detail="Category not found") from None
    finally:
        if checked is not None:
            checked.stream.close()
        if file:
            for upload in file:
                await upload.close()


@router.get("/admin/requests", response_model=list[RequestListItem])
async def list_requests(
    current_session: CurrentSessionDep,
    service: RequestServiceDep,
    status: RequestStatus | None = None,
):
    return await service.list(status)


@router.get("/admin/requests/{request_id}", response_model=RequestDetail)
async def get_request(
    request_id: UUID, current_session: CurrentSessionDep, service: RequestServiceDep
):
    try:
        return await service.detail(request_id)
    except RequestNotFoundError:
        raise HTTPException(status_code=404, detail="Request not found") from None


@router.get("/admin/requests/{request_id}/file")
async def download_request_file(
    request_id: UUID, service: RequestServiceDep, current_session: CurrentSessionDep
):
    try:
        media, body = await service.file(request_id)
    except RequestNotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None

    async def chunks():
        try:
            while chunk := await run_in_threadpool(body.read, 64 * 1024):
                yield chunk
        finally:
            await run_in_threadpool(body.close)

    filename = quote(media.original_name, safe="")
    return StreamingResponse(
        chunks(),
        media_type=media.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
        },
    )


@router.patch("/admin/requests/{request_id}", response_model=RequestDetail)
async def update_request(
    request_id: UUID,
    body: RequestUpdate,
    current_session: CurrentSessionDep,
    service: RequestServiceDep,
):
    try:
        return await service.update(request_id, body.status)
    except RequestNotFoundError:
        raise HTTPException(status_code=404, detail="Request not found") from None
