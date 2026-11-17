"""Add users, role assignments and rotating authentication sessions.

Revision ID: 0002_identity_and_sessions
Revises: 0001_shared_reference_tables
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_identity_and_sessions"
down_revision: str | None = "0001_shared_reference_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_by_user_id", sa.BigInteger()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_roles_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_user_roles_role_id_roles", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], name="fk_user_roles_assigned_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(40)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_user_created", "auth_sessions", ["user_id", "created_at"])
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_token_id", sa.Uuid()),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], name="fk_auth_refresh_tokens_session_id_auth_sessions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_token_id"], ["auth_refresh_tokens.id"], name="fk_auth_refresh_tokens_replaced_by_token_id_auth_refresh_tokens", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_token_hash"),
    )
    op.create_index("ix_auth_refresh_tokens_session_id", "auth_refresh_tokens", ["session_id"])
    op.create_index(
        "uq_auth_refresh_tokens_active_session", "auth_refresh_tokens", ["session_id"],
        unique=True, postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_auth_refresh_tokens_active_session", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_session_id", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
    op.drop_index("ix_auth_sessions_user_created", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_table("users")
