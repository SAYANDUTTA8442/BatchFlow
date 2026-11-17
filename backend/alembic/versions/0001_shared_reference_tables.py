"""Create shared role and unit reference tables.

Revision ID: 0001_shared_reference_tables
Revises:
Create Date: 2026-11-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_shared_reference_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_table(
        "units",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("dimension", sa.String(length=20), nullable=False),
        sa.Column("input_decimal_places", sa.SmallInteger(), nullable=False),
        sa.Column(
            "is_base_unit",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_decimal_places BETWEEN 0 AND 6",
            name="ck_units_input_decimal_places_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_units"),
        sa.UniqueConstraint("code", name="uq_units_code"),
    )


def downgrade() -> None:
    op.drop_table("units")
    op.drop_table("roles")
