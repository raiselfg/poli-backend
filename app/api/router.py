from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routers.auth import router as auth_router
from app.api.routers.categories import router as categories_router
from app.api.routers.contacts import router as contacts_router
from app.api.routers.media import router as media_router
from app.api.routers.requests import router as requests_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(categories_router)
api_router.include_router(contacts_router)
api_router.include_router(media_router)
api_router.include_router(requests_router)


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default response includes input values, including invalid passwords.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ]
        },
    )
