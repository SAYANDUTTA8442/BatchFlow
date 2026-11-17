"""Add movement reversal reason to stock adjustments.

Revision ID: 0006_movement_reversals
Revises: 0005_purchase_receipts
Create Date: 2026-11-17
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0006_movement_reversals"
down_revision: str | None = "0005_purchase_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_stock_adjustments_reason_valid",
        "stock_adjustments",
        type_="check",
    )
    op.create_check_constraint(
        "ck_stock_adjustments_reason_valid",
        "stock_adjustments",
        "reason IN ('OPENING_BALANCE', 'COUNT_CORRECTION', 'PRODUCTION_REVERSAL', 'MOVEMENT_REVERSAL', 'OTHER')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE stock_adjustments SET reason = 'OTHER' WHERE reason = 'MOVEMENT_REVERSAL'"
    )
    op.drop_constraint(
        "ck_stock_adjustments_reason_valid",
        "stock_adjustments",
        type_="check",
    )
    op.create_check_constraint(
        "ck_stock_adjustments_reason_valid",
        "stock_adjustments",
        "reason IN ('OPENING_BALANCE', 'COUNT_CORRECTION', 'PRODUCTION_REVERSAL', 'OTHER')",
    )
