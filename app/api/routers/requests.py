from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import CurrentSessionDep, RequestServiceDep, SettingsDep
from app.api.files import (
    MAX_REQUEST_FILE_SIZE,
    MAX_REQUEST_FILES,
    CheckedFile,
    FileTooLargeError,
    InvalidFileError,
    check_file,
)
from app.schemas.request import (
    RequestCreated,
    RequestDetail,
    RequestListItem,
    RequestStatus,
    RequestUpdate,
)
from app.services.request import RequestCategoryNotFoundError, RequestNotFoundError
from app.services.telegram import notify_new_request

router = APIRouter(tags=["requests"])


@router.post("/requests", status_code=201, response_model=RequestCreated)
async def create_request(
    service: RequestServiceDep,
    settings: SettingsDep,
    request: Request,
    background_tasks: BackgroundTasks,
    name: Annotated[str, Form(min_length=1, max_length=100)],
    phone: Annotated[str, Form(min_length=1, max_length=40)],
    comment: Annotated[str | None, Form()] = None,
    category_id: Annotated[UUID | None, Form(alias="categoryId")] = None,
    file: Annotated[list[UploadFile] | None, File()] = None,
):
    if not name.strip() or not phone.strip():
        raise HTTPException(status_code=422, detail="Name and phone must not be blank")
    uploads = file or []
    checked: list[CheckedFile] = []
    try:
        if len(uploads) > MAX_REQUEST_FILES:
            raise HTTPException(status_code=400, detail="Too many files")
        for upload in uploads:
            checked.append(
                await check_file(upload, images_only=False, max_size=MAX_REQUEST_FILE_SIZE)
            )
        files = [
            (item.stream, item.original_name, item.mime_type, item.size, item.width, item.height)
            for item in checked
        ]
        created = await service.create(name, phone, comment, category_id, files)
        token = settings.telegram_bot_token
        if token:
            background_tasks.add_task(
                notify_new_request,
                request.app.state.session_factory,
                token.get_secret_value(),
                settings.allowed_origins,
                created,
                proxy_url=settings.telegram_proxy_url,
            )
        return created
    except FileTooLargeError:
        raise HTTPException(status_code=413, detail="File too large") from None
    except InvalidFileError:
        raise HTTPException(status_code=415, detail="Unsupported file") from None
    except RequestCategoryNotFoundError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    finally:
        for item in checked:
            item.stream.close()
        for upload in uploads:
            await upload.close()


@router.get("/admin/requests", response_model=list[RequestListItem])
async def list_requests(
    _current_session: CurrentSessionDep,
    service: RequestServiceDep,
    status: RequestStatus | None = None,
):
    return await service.list(status)


@router.get("/admin/requests/{request_id}", response_model=RequestDetail)
async def get_request(
    request_id: UUID, _current_session: CurrentSessionDep, service: RequestServiceDep
):
    try:
        return await service.detail(request_id)
    except RequestNotFoundError:
        raise HTTPException(status_code=404, detail="Request not found") from None


@router.get("/admin/requests/{request_id}/file")
async def download_request_file(
    request_id: UUID,
    service: RequestServiceDep,
    current_session: CurrentSessionDep,
    file_id: UUID | None = None,
):
    try:
        media, body = await service.file(request_id, file_id)
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
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
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
