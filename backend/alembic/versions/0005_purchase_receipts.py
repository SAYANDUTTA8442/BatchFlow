"""Add supplier purchase receipts and receipt-sourced stock movements.

Revision ID: 0005_purchase_receipts
Revises: 0004_inventory_ledger
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_purchase_receipts"
down_revision: str | None = "0004_inventory_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_receipts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("receipt_number", sa.String(60), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_invoice_number", sa.String(80)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", sa.String(20), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("posted_by_user_id", sa.BigInteger()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'POSTED')", name="ck_purchase_receipts_status_valid"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL AND posted_by_user_id IS NULL) OR "
            "(status = 'POSTED' AND posted_at IS NOT NULL AND posted_by_user_id IS NOT NULL)",
            name="ck_purchase_receipts_posting_state_consistent",
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_purchase_receipts_supplier", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_purchase_receipts_created_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by_user_id"], ["users.id"], name="fk_purchase_receipts_posted_by", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_receipts"),
        sa.UniqueConstraint("receipt_number", name="uq_purchase_receipts_number"),
        sa.UniqueConstraint("supplier_id", "supplier_invoice_number", name="uq_purchase_receipts_supplier_invoice"),
    )
    op.create_table(
        "purchase_receipt_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("purchase_receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_location_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_received", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint("quantity_received > 0", name="ck_purchase_receipt_lines_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_purchase_receipt_lines_unit_cost_nonnegative"),
        sa.ForeignKeyConstraint(["purchase_receipt_id"], ["purchase_receipts.id"], name="fk_purchase_receipt_lines_receipt", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_purchase_receipt_lines_item", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_location_id"], ["inventory_locations.id"], name="fk_purchase_receipt_lines_location", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_receipt_lines"),
        sa.UniqueConstraint("purchase_receipt_id", "inventory_item_id", "inventory_location_id", name="uq_purchase_receipt_lines_item_location"),
    )
    op.create_index(
        "ix_purchase_receipt_lines_item_location",
        "purchase_receipt_lines",
        ["inventory_item_id", "inventory_location_id"],
    )

    op.alter_column("stock_movements", "stock_adjustment_line_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("stock_movements", sa.Column("purchase_receipt_line_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_stock_movements_receipt_line",
        "stock_movements",
        "purchase_receipt_lines",
        ["purchase_receipt_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_stock_movements_purchase_receipt_line",
        "stock_movements",
        ["purchase_receipt_line_id"],
    )
    op.drop_constraint(
        "ck_stock_movements_movement_type_valid",
        "stock_movements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_stock_movements_movement_type_valid",
        "stock_movements",
        "movement_type IN ('OPENING', 'ADJUSTMENT', 'RECEIPT', 'REVERSAL')",
    )
    op.create_check_constraint(
        "ck_stock_movements_exactly_one_source_line",
        "stock_movements",
        "(stock_adjustment_line_id IS NOT NULL)::int + (purchase_receipt_line_id IS NOT NULL)::int = 1",
    )

    op.execute("""
        CREATE FUNCTION reject_posted_purchase_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'POSTED' THEN
                RAISE EXCEPTION 'Posted purchase receipts are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER purchase_receipts_immutable
        BEFORE UPDATE OR DELETE ON purchase_receipts
        FOR EACH ROW EXECUTE FUNCTION reject_posted_purchase_receipt_mutation();
    """)
    op.execute("""
        CREATE FUNCTION reject_posted_purchase_receipt_line_mutation() RETURNS trigger AS $$
        DECLARE
            receipt_status text;
            parent_receipt_id bigint;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                parent_receipt_id := NEW.purchase_receipt_id;
            ELSE
                parent_receipt_id := OLD.purchase_receipt_id;
            END IF;
            SELECT status INTO receipt_status
            FROM purchase_receipts
            WHERE id = parent_receipt_id;
            IF receipt_status = 'POSTED' THEN
                RAISE EXCEPTION 'Lines of posted purchase receipts are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER purchase_receipt_lines_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON purchase_receipt_lines
        FOR EACH ROW EXECUTE FUNCTION reject_posted_purchase_receipt_line_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS purchase_receipt_lines_immutable ON purchase_receipt_lines")
    op.execute("DROP TRIGGER IF EXISTS purchase_receipts_immutable ON purchase_receipts")
    op.execute("DROP FUNCTION IF EXISTS reject_posted_purchase_receipt_line_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reject_posted_purchase_receipt_mutation()")
    op.drop_constraint("ck_stock_movements_exactly_one_source_line", "stock_movements", type_="check")
    op.drop_constraint("ck_stock_movements_movement_type_valid", "stock_movements", type_="check")
    op.create_check_constraint(
        "ck_stock_movements_movement_type_valid",
        "stock_movements",
        "movement_type IN ('OPENING', 'ADJUSTMENT', 'REVERSAL')",
    )
    op.drop_constraint("uq_stock_movements_purchase_receipt_line", "stock_movements", type_="unique")
    op.drop_constraint("fk_stock_movements_receipt_line", "stock_movements", type_="foreignkey")
    op.drop_column("stock_movements", "purchase_receipt_line_id")
    op.alter_column("stock_movements", "stock_adjustment_line_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_index("ix_purchase_receipt_lines_item_location", table_name="purchase_receipt_lines")
    op.drop_table("purchase_receipt_lines")
    op.drop_table("purchase_receipts")
