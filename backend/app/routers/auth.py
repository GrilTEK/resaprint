from fastapi import APIRouter, Depends, Form, Header, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db, require_admin_session
from app.models.admin_pin import AdminPin
from app.schemas.auth import LoginResponse
from app.services.auth_service import SESSION_COOKIE_NAME, attempt_login, issue_session_token

router = APIRouter(tags=["auth"])


@router.post("/login")
async def login(
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

    # Build the actual Response we return and set the cookie on THAT
    # object — setting it on an injected `response: Response` param is
    # silently discarded by FastAPI when the handler explicitly returns
    # its own Response subclass (HTMLResponse here). This previously
    # meant the HTMX login path always "succeeded" with 200 but never
    # actually issued a session cookie.
    if hx_request:
        resp = HTMLResponse("", status_code=200)
    else:
        resp = JSONResponse(LoginResponse(label=admin_pin.label).model_dump())

    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return resp


@router.post("/logout")
async def logout(_admin: AdminPin = Depends(require_admin_session)):
    resp = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp
