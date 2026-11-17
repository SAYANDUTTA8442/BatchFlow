import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(40))


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (
        Index(
            "uq_auth_refresh_tokens_active_session",
            "session_id",
            unique=True,
            postgresql_where=text("consumed_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"))
