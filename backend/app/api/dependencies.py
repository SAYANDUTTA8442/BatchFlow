import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Role, User, UserRole


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: uuid.UUID
    roles: frozenset[str]


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> Principal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
        if claims["typ"] != "access":
            raise ValueError("Wrong token type")
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    role_codes = db.scalars(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    ).all()
    return Principal(user=user, session_id=session_id, roles=frozenset(role_codes))


def require_roles(*required_roles: str):
    def dependency(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
        if not principal.roles.intersection(required_roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return principal
    return dependency
