from fastapi import APIRouter, Depends, Form, Header, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db, require_admin_session
from app.models.admin_pin import AdminPin
from app.schemas.auth import LoginResponse
from app.services.auth_service import SESSION_COOKIE_NAME, attempt_login, issue_session_token

router = APIRouter(tags=["auth"])


@router.post("/login")
async def login(
    response: Response,
    pin: str = Form(...),
    db: AsyncSession = Depends(get_db),
    hx_request: str | None = Header(default=None, alias="HX-Request"),
):
    admin_pin = await attempt_login(db, pin)
    if admin_pin is None:
        if hx_request:
            return HTMLResponse('<span class="error-text">Invalid PIN</span>', status_code=200)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid PIN")

    token = issue_session_token(admin_pin.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    if hx_request:
        return HTMLResponse("", status_code=200)
    return LoginResponse(label=admin_pin.label)


@router.post("/logout")
async def logout(response: Response, _admin: AdminPin = Depends(require_admin_session)):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
