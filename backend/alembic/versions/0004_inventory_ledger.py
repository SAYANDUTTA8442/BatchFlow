"""Add append-only stock ledger, balance and valuation projections.

Revision ID: 0004_inventory_ledger
Revises: 0003_master_data
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_inventory_ledger"
down_revision: str | None = "0003_master_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_adjustments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("adjustment_number", sa.String(60), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", sa.String(20), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("posted_by_user_id", sa.BigInteger()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('OPENING_BALANCE', 'COUNT_CORRECTION', 'PRODUCTION_REVERSAL', 'OTHER')",
            name="ck_stock_adjustments_reason_valid",
        ),
        sa.CheckConstraint("status IN ('DRAFT', 'POSTED')", name="ck_stock_adjustments_status_valid"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL AND posted_by_user_id IS NULL) OR "
            "(status = 'POSTED' AND posted_at IS NOT NULL AND posted_by_user_id IS NOT NULL)",
            name="ck_stock_adjustments_posting_state_consistent",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_stock_adjustments_created_by_user_id_users"),
        sa.ForeignKeyConstraint(["posted_by_user_id"], ["users.id"], name="fk_stock_adjustments_posted_by_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_stock_adjustments"),
        sa.UniqueConstraint("adjustment_number", name="uq_stock_adjustments_number"),
    )
    op.create_table(
        "stock_adjustment_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("stock_adjustment_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_location_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6)),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_stock_adjustment_lines_quantity_nonzero"),
        sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_stock_adjustment_lines_unit_cost_nonnegative"),
        sa.ForeignKeyConstraint(["stock_adjustment_id"], ["stock_adjustments.id"], name="fk_stock_adjustment_lines_stock_adjustment_id_stock_adjustments", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_stock_adjustment_lines_inventory_item_id_inventory_items", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_location_id"], ["inventory_locations.id"], name="fk_stock_adjustment_lines_inventory_location_id_inventory_locations", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_stock_adjustment_lines"),
        sa.UniqueConstraint("stock_adjustment_id", "inventory_item_id", "inventory_location_id", name="uq_stock_adjustment_lines_item_location"),
    )
    op.create_index("ix_stock_adjustment_lines_item_location", "stock_adjustment_lines", ["inventory_item_id", "inventory_location_id"])

    op.create_table(
        "inventory_balances",
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_location_id", sa.BigInteger(), nullable=False),
        sa.Column("on_hand_qty", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("on_hand_qty >= 0", name="ck_inventory_balances_on_hand_nonnegative"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_inventory_balances_inventory_item_id_inventory_items", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_location_id"], ["inventory_locations.id"], name="fk_inventory_balances_inventory_location_id_inventory_locations", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("inventory_item_id", "inventory_location_id", name="pk_inventory_balances"),
    )
    op.create_index("ix_inventory_balances_location_item", "inventory_balances", ["inventory_location_id", "inventory_item_id"])

    op.create_table(
        "inventory_valuations",
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_location_id", sa.BigInteger(), nullable=False),
        sa.Column("valued_qty", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("inventory_value", sa.Numeric(18, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("average_unit_cost", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("valued_qty >= 0", name="ck_inventory_valuations_valued_qty_nonnegative"),
        sa.CheckConstraint("inventory_value >= 0", name="ck_inventory_valuations_inventory_value_nonnegative"),
        sa.CheckConstraint("average_unit_cost >= 0", name="ck_inventory_valuations_average_unit_cost_nonnegative"),
        sa.CheckConstraint("valued_qty > 0 OR (inventory_value = 0 AND average_unit_cost = 0)", name="ck_inventory_valuations_zero_quantity_zero_value"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_inventory_valuations_inventory_item_id_inventory_items", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_location_id"], ["inventory_locations.id"], name="fk_inventory_valuations_inventory_location_id_inventory_locations", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("inventory_item_id", "inventory_location_id", name="pk_inventory_valuations"),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_location_id", sa.BigInteger(), nullable=False),
        sa.Column("movement_type", sa.String(30), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6)),
        sa.Column("extended_cost", sa.Numeric(18, 2)),
        sa.Column("stock_adjustment_line_id", sa.BigInteger(), nullable=False),
        sa.Column("reverses_movement_id", sa.BigInteger()),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("posted_by_user_id", sa.BigInteger()),
        sa.CheckConstraint("movement_type IN ('OPENING', 'ADJUSTMENT', 'REVERSAL')", name="ck_stock_movements_movement_type_valid"),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_stock_movements_quantity_nonzero"),
        sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_stock_movements_unit_cost_nonnegative"),
        sa.CheckConstraint("extended_cost IS NULL OR extended_cost >= 0", name="ck_stock_movements_extended_cost_nonnegative"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_stock_movements_inventory_item_id_inventory_items", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_location_id"], ["inventory_locations.id"], name="fk_stock_movements_inventory_location_id_inventory_locations", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_adjustment_line_id"], ["stock_adjustment_lines.id"], name="fk_stock_movements_stock_adjustment_line_id_stock_adjustment_lines", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reverses_movement_id"], ["stock_movements.id"], name="fk_stock_movements_reverses_movement_id_stock_movements", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by_user_id"], ["users.id"], name="fk_stock_movements_posted_by_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_stock_movements"),
        sa.UniqueConstraint("stock_adjustment_line_id", name="uq_stock_movements_adjustment_line"),
        sa.UniqueConstraint("reverses_movement_id", name="uq_stock_movements_reversal"),
    )
    op.create_index("ix_stock_movements_item_location_posted", "stock_movements", ["inventory_item_id", "inventory_location_id", "posted_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger()),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("before_data", postgresql.JSONB()),
        sa.Column("after_data", postgresql.JSONB()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_events_actor_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_entity_time", "audit_events", ["entity_type", "entity_id", "occurred_at"])
    op.create_index("ix_audit_events_actor_time", "audit_events", ["actor_user_id", "occurred_at"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(response_status IS NULL AND response_body IS NULL AND completed_at IS NULL) OR "
            "(response_status IS NOT NULL AND response_body IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_idempotency_records_completion_consistent",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_idempotency_records_actor_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint("actor_user_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"),
    )
    op.create_index("ix_idempotency_created_at", "idempotency_records", ["created_at"])

    op.execute("""
        CREATE FUNCTION reject_immutable_row_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Rows in % are append-only', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER stock_movements_append_only
        BEFORE UPDATE OR DELETE ON stock_movements
        FOR EACH ROW EXECUTE FUNCTION reject_immutable_row_mutation();
    """)
    op.execute("""
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_immutable_row_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS stock_movements_append_only ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS reject_immutable_row_mutation()")
    op.drop_index("ix_idempotency_created_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_events_actor_time", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_stock_movements_item_location_posted", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_table("inventory_valuations")
    op.drop_index("ix_inventory_balances_location_item", table_name="inventory_balances")
    op.drop_table("inventory_balances")
    op.drop_index("ix_stock_adjustment_lines_item_location", table_name="stock_adjustment_lines")
    op.drop_table("stock_adjustment_lines")
    op.drop_table("stock_adjustments")
