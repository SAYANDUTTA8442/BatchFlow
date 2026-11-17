from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_current_principal
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import LoginRequest, TokenResponse, UserRead
from app.services.auth import authenticate, revoke_session, rotate_refresh_token


router = APIRouter(prefix="/api/auth", tags=["authentication"])
REFRESH_COOKIE_NAME = "batchflow_refresh"
REFRESH_COOKIE_PATH = "/api/auth/refresh"


def validate_origin(origin: str | None) -> None:
    settings = get_settings()
    normalized = origin.rstrip("/") if origin else None
    if normalized not in settings.origin_allowlist:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME, value=raw_token, max_age=30 * 24 * 60 * 60,
        httponly=True, secure=settings.refresh_cookie_secure, samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH, httponly=True,
        secure=settings.refresh_cookie_secure, samesite="lax",
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    response: Response,
    origin: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> TokenResponse:
    validate_origin(origin)
    tokens, refresh_token, _ = authenticate(db, str(payload.email), payload.password)
    set_refresh_cookie(response, refresh_token)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    origin: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> TokenResponse:
    validate_origin(origin)
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh cookie missing")
    tokens, successor = rotate_refresh_token(db, raw_token)
    set_refresh_cookie(response, successor)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    principal: Principal = Depends(get_current_principal),
    origin: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> Response:
    validate_origin(origin)
    revoke_session(db, principal.session_id, principal.user.id)
    clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def me(principal: Principal = Depends(get_current_principal)) -> UserRead:
    return UserRead(
        id=principal.user.id, full_name=principal.user.full_name,
        email=principal.user.email, roles=sorted(principal.roles),
    )
