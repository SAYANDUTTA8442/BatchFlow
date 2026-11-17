import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    SESSION_LIFETIME_DAYS,
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_expiry,
    verify_password,
)
from app.models import AuthRefreshToken, AuthSession, Role, User, UserRole
from app.schemas.auth import TokenResponse, UserRead


def _user_read(db: Session, user: User) -> UserRead:
    roles = db.scalars(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id).order_by(Role.code)
    ).all()
    return UserRead(id=user.id, full_name=user.full_name, email=user.email, roles=list(roles))


def _token_response(db: Session, user: User, session_id: uuid.UUID) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, session_id),
        expires_in=ACCESS_TOKEN_MINUTES * 60,
        user=_user_read(db, user),
    )


def authenticate(db: Session, email: str, password: str) -> tuple[TokenResponse, str, uuid.UUID]:
    now = datetime.now(UTC)
    session_id = uuid.uuid4()
    raw_refresh = create_refresh_token()
    with db.begin():
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
        session_expiry = now + timedelta(days=SESSION_LIFETIME_DAYS)
        user.last_login_at = now
        db.add(
            AuthSession(
                id=session_id,
                user_id=user.id,
                expires_at=session_expiry,
                last_used_at=now,
            )
        )
        # Persist the parent session before inserting its refresh-token child.
        db.flush()
        db.add(
            AuthRefreshToken(
                id=uuid.uuid4(),
                session_id=session_id,
                token_hash=hash_refresh_token(raw_refresh),
                expires_at=refresh_expiry(session_expiry),
            )
        )
        user_id = user.id
    user = db.get(User, user_id)
    return _token_response(db, user, session_id), raw_refresh, session_id


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[TokenResponse, str]:
    token_hash = hash_refresh_token(raw_token)
    token_snapshot = db.scalar(select(AuthRefreshToken).where(AuthRefreshToken.token_hash == token_hash))
    if token_snapshot is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    token_id, session_id = token_snapshot.id, token_snapshot.session_id
    db.rollback()

    now = datetime.now(UTC)
    reuse_detected = False
    failure: str | None = None
    response: TokenResponse | None = None
    successor_raw: str | None = None
    with db.begin():
        session = db.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
        token = db.scalar(select(AuthRefreshToken).where(AuthRefreshToken.id == token_id).with_for_update())
        if session is None or token is None:
            failure = "Invalid refresh token"
        elif token.consumed_at is not None:
            if session.revoked_at is None:
                session.revoked_at = now
                session.revoke_reason = "refresh_token_reuse"
            reuse_detected = True
        elif session.revoked_at is not None or session.expires_at <= now:
            failure = "Session expired or revoked"
        else:
            user = db.get(User, session.user_id)
            if user is None or not user.is_active:
                session.revoked_at = now
                session.revoke_reason = "inactive_user"
                failure = "Account is inactive"
            elif token.expires_at <= now:
                session.revoked_at = now
                session.revoke_reason = "refresh_token_expired"
                failure = "Refresh token expired"
            else:
                successor_raw = create_refresh_token()
                successor_id = uuid.uuid4()
                token.consumed_at = now
                session.last_used_at = now
                # Remove the old row from the partial unique index before inserting its successor.
                db.flush()
                db.add(
                    AuthRefreshToken(
                        id=successor_id,
                        session_id=session.id,
                        token_hash=hash_refresh_token(successor_raw),
                        expires_at=refresh_expiry(session.expires_at),
                    )
                )
                db.flush()
                token.replaced_by_token_id = successor_id
                db.flush()
                response = _token_response(db, user, session.id)
    if reuse_detected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh-token reuse detected; log in again")
    if failure is not None or response is None or successor_raw is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=failure or "Invalid refresh token")
    return response, successor_raw


def revoke_session(db: Session, session_id: uuid.UUID, user_id: int) -> None:
    # Authentication dependencies may have opened a read transaction.
    db.rollback()
    now = datetime.now(UTC)
    with db.begin():
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.id == session_id, AuthSession.user_id == user_id
            ).with_for_update()
        )
        if session is not None and session.revoked_at is None:
            session.revoked_at = now
            session.revoke_reason = "logout"


def create_user(db: Session, *, full_name: str, email: str, password: str, role_codes: list[str]) -> User:
    normalized_email = email.strip().lower()
    if not role_codes:
        raise ValueError("At least one role is required")
    with db.begin():
        if db.scalar(select(User.id).where(User.email == normalized_email)) is not None:
            raise ValueError("A user with this email already exists")
        roles = db.scalars(select(Role).where(Role.code.in_(role_codes))).all()
        if {role.code for role in roles} != set(role_codes):
            raise ValueError("One or more role codes are unknown")
        user = User(full_name=full_name.strip(), email=normalized_email, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        for role in roles:
            db.add(UserRole(user_id=user.id, role_id=role.id))
    return user
