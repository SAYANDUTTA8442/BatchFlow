"""Add immutable-source snapshots for draft production plans.

Revision ID: 0007_production_plans
Revises: 0006_boms
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_production_plans"
down_revision: str | None = "0006_boms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_number", sa.String(60), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("product_sku_snapshot", sa.String(60), nullable=False),
        sa.Column("product_name_snapshot", sa.String(160), nullable=False),
        sa.Column("finished_item_code_snapshot", sa.String(60), nullable=False),
        sa.Column("finished_item_name_snapshot", sa.String(160), nullable=False),
        sa.Column("output_unit_code_snapshot", sa.String(20), nullable=False),
        sa.Column("bom_id", sa.BigInteger(), nullable=False),
        sa.Column("bom_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("batch_multiplier", sa.Numeric(18, 6), nullable=False),
        sa.Column("expected_output_qty", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("production_date", sa.Date(), nullable=False),
        sa.Column("supervisor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("posted_by_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("bom_version_snapshot > 0", name="ck_production_runs_bom_version_positive"),
        sa.CheckConstraint("batch_multiplier > 0", name="ck_production_runs_batch_multiplier_positive"),
        sa.CheckConstraint("expected_output_qty > 0", name="ck_production_runs_expected_output_positive"),
        sa.CheckConstraint("status IN ('DRAFT', 'POSTED', 'REVERSED')", name="ck_production_runs_status_valid"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL AND posted_by_user_id IS NULL) OR "
            "(status IN ('POSTED', 'REVERSED') AND posted_at IS NOT NULL AND posted_by_user_id IS NOT NULL)",
            name="ck_production_runs_posting_state_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT",
            name="fk_production_runs_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["bom_id"], ["boms.id"], ondelete="RESTRICT",
            name="fk_production_runs_bom_id_boms"
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_production_runs_supervisor_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["posted_by_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_production_runs_posted_by_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_runs"),
        sa.UniqueConstraint("run_number", name="uq_production_runs_number"),
    )
    op.create_index("ix_production_runs_date_status", "production_runs", ["production_date", "status"])
    op.create_index("ix_production_runs_product_date", "production_runs", ["product_id", "production_date"])

    op.create_table(
        "production_run_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("production_run_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("line_type", sa.String(20), nullable=False),
        sa.Column("item_code_snapshot", sa.String(60), nullable=False),
        sa.Column("item_name_snapshot", sa.String(160), nullable=False),
        sa.Column("base_unit_code_snapshot", sa.String(20), nullable=False),
        sa.Column("quantity_per_batch_snapshot", sa.Numeric(18, 6), nullable=False),
        sa.Column("planned_qty", sa.Numeric(18, 6), nullable=False),
        sa.CheckConstraint("line_type IN ('RAW_MATERIAL', 'PACKAGING')", name="ck_production_run_lines_line_type_valid"),
        sa.CheckConstraint("quantity_per_batch_snapshot > 0", name="ck_production_run_lines_quantity_per_batch_positive"),
        sa.CheckConstraint("planned_qty > 0", name="ck_production_run_lines_planned_qty_positive"),
        sa.ForeignKeyConstraint(
            ["production_run_id"], ["production_runs.id"], ondelete="RESTRICT",
            name="fk_production_run_lines_production_run_id_production_runs"
        ),
        sa.ForeignKeyConstraint(
            ["inventory_item_id"], ["inventory_items.id"], ondelete="RESTRICT",
            name="fk_production_run_lines_inventory_item_id_inventory_items"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_run_lines"),
        sa.UniqueConstraint("production_run_id", "inventory_item_id", name="uq_production_run_lines_item"),
    )
    op.create_index(
        "ix_production_run_lines_inventory_item", "production_run_lines", ["inventory_item_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_production_run_lines_inventory_item", table_name="production_run_lines")
    op.drop_table("production_run_lines")
    op.drop_index("ix_production_runs_product_date", table_name="production_runs")
    op.drop_index("ix_production_runs_date_status", table_name="production_runs")
    op.drop_table("production_runs")
