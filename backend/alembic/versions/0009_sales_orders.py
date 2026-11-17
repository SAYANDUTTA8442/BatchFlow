"""Add salesman-submitted sales orders and immutable submitted snapshots.

Revision ID: 0009_sales_orders
Revises: 0008_production_posting
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_sales_orders"
down_revision: str | None = "0008_production_posting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("order_number", sa.String(60), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("salesman_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(24), server_default=sa.text("'SUBMITTED'"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_user_id", sa.BigInteger()),
        sa.Column("review_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED', 'INVOICED', 'DISPATCHED')",
            name="ck_sales_orders_status_valid",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT",
                                name="fk_sales_orders_customer_id_customers"),
        sa.ForeignKeyConstraint(["salesman_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_sales_orders_salesman_user_id_users"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_sales_orders_reviewed_by_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_sales_orders"),
        sa.UniqueConstraint("order_number", name="uq_sales_orders_number"),
    )
    op.create_index("ix_sales_orders_status_submitted", "sales_orders", ["status", "submitted_at"])
    op.create_index("ix_sales_orders_salesman_submitted", "sales_orders", ["salesman_user_id", "submitted_at"])
    op.create_index("ix_sales_orders_customer_submitted", "sales_orders", ["customer_id", "submitted_at"])

    op.create_table(
        "sales_order_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sales_order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("sku_snapshot", sa.String(60), nullable=False),
        sa.Column("product_name_snapshot", sa.String(160), nullable=False),
        sa.Column("hsn_snapshot", sa.String(20)),
        sa.Column("submitted_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("submitted_unit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("line_taxable_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("submitted_quantity > 0", name="ck_sales_order_lines_submitted_quantity_positive"),
        sa.CheckConstraint("submitted_unit_price >= 0", name="ck_sales_order_lines_submitted_price_nonnegative"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_order_lines_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sales_order_lines_unit_price_nonnegative"),
        sa.CheckConstraint("line_taxable_value >= 0", name="ck_sales_order_lines_taxable_value_nonnegative"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT",
                                name="fk_sales_order_lines_sales_order_id_sales_orders"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT",
                                name="fk_sales_order_lines_product_id_products"),
        sa.PrimaryKeyConstraint("id", name="pk_sales_order_lines"),
        sa.UniqueConstraint("sales_order_id", "product_id", name="uq_sales_order_lines_product"),
    )
    op.create_index("ix_sales_order_lines_product", "sales_order_lines", ["product_id"])

    op.execute("""
        CREATE FUNCTION guard_sales_order_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Sales orders cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status <> 'SUBMITTED' THEN
                RAISE EXCEPTION 'Reviewed sales orders are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.order_number IS DISTINCT FROM OLD.order_number OR
               NEW.customer_id IS DISTINCT FROM OLD.customer_id OR
               NEW.salesman_user_id IS DISTINCT FROM OLD.salesman_user_id OR
               NEW.submitted_at IS DISTINCT FROM OLD.submitted_at OR
               NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Sales order identity and submission fields are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER sales_orders_guard_mutation
        BEFORE UPDATE OR DELETE ON sales_orders
        FOR EACH ROW EXECUTE FUNCTION guard_sales_order_mutation();
    """)
    op.execute("""
        CREATE FUNCTION guard_sales_order_line_mutation() RETURNS trigger AS $$
        DECLARE
            parent_id bigint;
            parent_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Sales order lines cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            parent_id := NEW.sales_order_id;
            SELECT status INTO parent_status FROM sales_orders WHERE id = parent_id;
            IF parent_status IS DISTINCT FROM 'SUBMITTED' THEN
                RAISE EXCEPTION 'Reviewed sales order lines are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                NEW.submitted_quantity IS DISTINCT FROM OLD.submitted_quantity OR
                NEW.submitted_unit_price IS DISTINCT FROM OLD.submitted_unit_price OR
                NEW.sku_snapshot IS DISTINCT FROM OLD.sku_snapshot OR
                NEW.product_name_snapshot IS DISTINCT FROM OLD.product_name_snapshot OR
                NEW.hsn_snapshot IS DISTINCT FROM OLD.hsn_snapshot OR
                NEW.product_id IS DISTINCT FROM OLD.product_id OR
                NEW.sales_order_id IS DISTINCT FROM OLD.sales_order_id OR
                NEW.created_at IS DISTINCT FROM OLD.created_at
            ) THEN
                RAISE EXCEPTION 'Submitted sales order snapshots are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER sales_order_lines_guard_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON sales_order_lines
        FOR EACH ROW EXECUTE FUNCTION guard_sales_order_line_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS sales_order_lines_guard_mutation ON sales_order_lines")
    op.execute("DROP TRIGGER IF EXISTS sales_orders_guard_mutation ON sales_orders")
    op.execute("DROP FUNCTION IF EXISTS guard_sales_order_line_mutation()")
    op.execute("DROP FUNCTION IF EXISTS guard_sales_order_mutation()")
    op.drop_index("ix_sales_order_lines_product", table_name="sales_order_lines")
    op.drop_table("sales_order_lines")
    op.drop_index("ix_sales_orders_customer_submitted", table_name="sales_orders")
    op.drop_index("ix_sales_orders_salesman_submitted", table_name="sales_orders")
    op.drop_index("ix_sales_orders_status_submitted", table_name="sales_orders")
    op.drop_table("sales_orders")
