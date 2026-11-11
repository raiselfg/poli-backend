from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import set_session_cookie
from app.core.config import Settings
from app.core.security import utc_now
from app.db.session import get_db
from app.services.auth import AuthenticationRequiredError, AuthService, CurrentSession
from app.services.category import CategoryService
from app.services.contact import ContactService
from app.services.media import MediaService
from app.services.request import RequestService
from app.storage.s3 import S3Storage, get_storage_settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: SettingsDep,
) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_session_token(request: Request, settings: SettingsDep) -> str | None:
    return request.cookies.get(settings.cookie_name)


SessionTokenDep = Annotated[str | None, Depends(get_session_token)]


async def get_current_session(
    response: Response, auth: AuthServiceDep, settings: SettingsDep, token: SessionTokenDep
) -> CurrentSession:
    try:
        current_session = await auth.verify_session(token)
    except AuthenticationRequiredError:
        raise HTTPException(status_code=401, detail="Authentication required") from None
    # Sliding expiration: endpoints that touch the session prolong its cookie.
    remaining = max(0, int((current_session.session_expires_at - utc_now()).total_seconds()))
    set_session_cookie(response, settings, token, max_age=remaining)
    return current_session


CurrentSessionDep = Annotated[CurrentSession, Depends(get_current_session)]


def get_contact_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ContactService:
    return ContactService(session)


ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]


def get_category_service(session: Annotated[AsyncSession, Depends(get_db)]) -> CategoryService:
    return CategoryService(session)


CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]


def get_media_service(session: Annotated[AsyncSession, Depends(get_db)]) -> MediaService:
    return MediaService(session, S3Storage(get_storage_settings()))


MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]


def get_request_service(session: Annotated[AsyncSession, Depends(get_db)]) -> RequestService:
    return RequestService(session, S3Storage(get_storage_settings()))


RequestServiceDep = Annotated[RequestService, Depends(get_request_service)]
