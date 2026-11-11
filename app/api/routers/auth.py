from fastapi import APIRouter, HTTPException, Response

from app.api.cookies import clear_session_cookie, set_session_cookie
from app.api.dependencies import (
    AuthServiceDep,
    CurrentSessionDep,
    SessionTokenDep,
    SettingsDep,
)
from app.schemas.auth import Credentials
from app.schemas.user import UserRead
from app.services.auth import (
    AuthenticationRequiredError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserRead)
async def login(body: Credentials, response: Response, auth: AuthServiceDep, settings: SettingsDep):
    try:
        user, token = await auth.login(body.login, body.password.get_secret_value())
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid login or password") from None
    set_session_cookie(response, settings, token)
    return user


@router.post("/logout", status_code=204)
async def logout(
    response: Response, auth: AuthServiceDep, token: SessionTokenDep, settings: SettingsDep
):
    try:
        await auth.logout(token)
    except AuthenticationRequiredError:
        raise HTTPException(status_code=401, detail="Authentication required") from None
    clear_session_cookie(response, settings)


@router.get("/me", response_model=UserRead)
async def me(current_session: CurrentSessionDep):
    return current_session.user
