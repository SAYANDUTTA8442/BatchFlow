"""Add atomic production execution, costs and source-linked movements.

Revision ID: 0008_production_posting
Revises: 0007_production_plans
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_production_posting"
down_revision: str | None = "0007_production_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("production_runs", sa.Column("finished_inventory_item_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE production_runs pr
        SET finished_inventory_item_id = p.inventory_item_id
        FROM products p
        WHERE p.id = pr.product_id
    """)
    op.alter_column("production_runs", "finished_inventory_item_id", nullable=False)
    op.create_foreign_key(
        "fk_production_runs_finished_inventory_item_id_inventory_items",
        "production_runs", "inventory_items",
        ["finished_inventory_item_id"], ["id"], ondelete="RESTRICT",
    )
    op.add_column(
        "production_runs",
        sa.Column("variance_tolerance_percent", sa.Numeric(12, 4), server_default=sa.text("3.0000"), nullable=False),
    )
    op.add_column("production_runs", sa.Column("actual_good_output_qty", sa.Numeric(18, 6), nullable=True))
    op.add_column("production_runs", sa.Column("yield_variance_qty", sa.Numeric(18, 6), nullable=True))
    op.add_column("production_runs", sa.Column("yield_variance_percent", sa.Numeric(12, 4), nullable=True))
    op.add_column(
        "production_runs",
        sa.Column("yield_variance_alert", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("production_runs", sa.Column("total_run_cost", sa.Numeric(18, 2), nullable=True))
    op.add_column("production_runs", sa.Column("cost_per_good_unit", sa.Numeric(18, 6), nullable=True))
    op.add_column("production_runs", sa.Column("wastage_note", sa.String(2000), nullable=True))
    op.create_check_constraint(
        "ck_production_runs_variance_tolerance_nonnegative",
        "production_runs", "variance_tolerance_percent >= 0",
    )
    op.create_check_constraint(
        "ck_production_runs_actual_output_positive",
        "production_runs", "actual_good_output_qty IS NULL OR actual_good_output_qty > 0",
    )
    op.create_check_constraint(
        "ck_production_runs_total_cost_nonnegative",
        "production_runs", "total_run_cost IS NULL OR total_run_cost >= 0",
    )
    op.create_check_constraint(
        "ck_production_runs_unit_cost_nonnegative",
        "production_runs", "cost_per_good_unit IS NULL OR cost_per_good_unit >= 0",
    )
    op.create_check_constraint(
        "ck_production_runs_posting_cost_state_consistent",
        "production_runs",
        "(status = 'DRAFT' AND actual_good_output_qty IS NULL AND total_run_cost IS NULL AND cost_per_good_unit IS NULL) OR "
        "(status IN ('POSTED', 'REVERSED') AND actual_good_output_qty IS NOT NULL AND total_run_cost IS NOT NULL AND cost_per_good_unit IS NOT NULL)",
    )

    op.add_column("production_run_lines", sa.Column("actual_qty", sa.Numeric(18, 6), nullable=True))
    op.add_column(
        "production_run_lines",
        sa.Column("damaged_qty", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("production_run_lines", sa.Column("variance_qty", sa.Numeric(18, 6), nullable=True))
    op.add_column("production_run_lines", sa.Column("variance_percent", sa.Numeric(12, 4), nullable=True))
    op.add_column(
        "production_run_lines",
        sa.Column("variance_alert", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("production_run_lines", sa.Column("unit_cost_snapshot", sa.Numeric(18, 6), nullable=True))
    op.add_column("production_run_lines", sa.Column("line_cost", sa.Numeric(18, 2), nullable=True))
    op.create_check_constraint(
        "ck_production_run_lines_actual_qty_nonnegative",
        "production_run_lines", "actual_qty IS NULL OR actual_qty >= 0",
    )
    op.create_check_constraint(
        "ck_production_run_lines_damaged_qty_nonnegative",
        "production_run_lines", "damaged_qty >= 0",
    )
    op.create_check_constraint(
        "ck_production_run_lines_damaged_not_over_actual",
        "production_run_lines", "actual_qty IS NULL OR damaged_qty <= actual_qty",
    )
    op.create_check_constraint(
        "ck_production_run_lines_unit_cost_nonnegative",
        "production_run_lines", "unit_cost_snapshot IS NULL OR unit_cost_snapshot >= 0",
    )
    op.create_check_constraint(
        "ck_production_run_lines_line_cost_nonnegative",
        "production_run_lines", "line_cost IS NULL OR line_cost >= 0",
    )

    op.create_table(
        "production_run_outputs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("production_run_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("good_qty", sa.Numeric(18, 6), nullable=False),
        sa.Column("base_unit_code_snapshot", sa.String(20), nullable=False),
        sa.CheckConstraint("good_qty > 0", name="ck_production_run_outputs_good_qty_positive"),
        sa.ForeignKeyConstraint(
            ["production_run_id"], ["production_runs.id"], ondelete="RESTRICT",
            name="fk_production_run_outputs_production_run_id_production_runs"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT",
            name="fk_production_run_outputs_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["inventory_item_id"], ["inventory_items.id"], ondelete="RESTRICT",
            name="fk_production_run_outputs_inventory_item_id_inventory_items"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_run_outputs"),
        sa.UniqueConstraint("production_run_id", name="uq_production_run_outputs_run"),
    )
    op.create_table(
        "production_cost_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("production_run_id", sa.BigInteger(), nullable=False),
        sa.Column("cost_type", sa.String(30), nullable=False),
        sa.Column("description", sa.String(180), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("cost_type IN ('LABOUR', 'ENERGY', 'OTHER')", name="ck_production_cost_lines_cost_type_valid"),
        sa.CheckConstraint("amount >= 0", name="ck_production_cost_lines_amount_nonnegative"),
        sa.ForeignKeyConstraint(
            ["production_run_id"], ["production_runs.id"], ondelete="RESTRICT",
            name="fk_production_cost_lines_production_run_id_production_runs"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_cost_lines"),
    )
    op.create_index("ix_production_cost_lines_run", "production_cost_lines", ["production_run_id"])

    op.add_column("stock_movements", sa.Column("production_run_line_id", sa.BigInteger(), nullable=True))
    op.add_column("stock_movements", sa.Column("production_run_output_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_stock_movements_production_run_line_id_production_run_lines",
        "stock_movements", "production_run_lines", ["production_run_line_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_stock_movements_production_run_output_id_production_run_outputs",
        "stock_movements", "production_run_outputs", ["production_run_output_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_stock_movements_production_run_line", "stock_movements", ["production_run_line_id"]
    )
    op.create_unique_constraint(
        "uq_stock_movements_production_run_output", "stock_movements", ["production_run_output_id"]
    )
    op.drop_constraint("ck_stock_movements_exactly_one_source_line", "stock_movements", type_="check")
    op.create_check_constraint(
        "ck_stock_movements_exactly_one_source_line",
        "stock_movements",
        "(stock_adjustment_line_id IS NOT NULL)::int + "
        "(purchase_receipt_line_id IS NOT NULL)::int + "
        "(production_run_line_id IS NOT NULL)::int + "
        "(production_run_output_id IS NOT NULL)::int = 1",
    )
    op.drop_constraint("ck_stock_movements_movement_type_valid", "stock_movements", type_="check")
    op.create_check_constraint(
        "ck_stock_movements_movement_type_valid",
        "stock_movements",
        "movement_type IN ('OPENING', 'ADJUSTMENT', 'RECEIPT', 'PRODUCTION_ISSUE', 'PRODUCTION_OUTPUT', 'REVERSAL')",
    )

    op.execute("""
        CREATE FUNCTION reject_posted_production_run_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'Posted production runs are immutable'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status <> 'DRAFT' THEN
                RAISE EXCEPTION 'Posted production runs are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER production_runs_immutable_after_posting
        BEFORE UPDATE OR DELETE ON production_runs
        FOR EACH ROW EXECUTE FUNCTION reject_posted_production_run_mutation();
    """)
    op.execute("""
        CREATE FUNCTION reject_posted_production_child_mutation() RETURNS trigger AS $$
        DECLARE
            parent_id bigint;
            parent_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                parent_id := OLD.production_run_id;
            ELSE
                parent_id := NEW.production_run_id;
            END IF;
            SELECT status INTO parent_status FROM production_runs WHERE id = parent_id;
            IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'Lines of posted production runs are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table, trigger in (
        ("production_run_lines", "production_run_lines_immutable_after_posting"),
        ("production_run_outputs", "production_run_outputs_immutable_after_posting"),
        ("production_cost_lines", "production_cost_lines_immutable_after_posting"),
    ):
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_posted_production_child_mutation()"
        )


def downgrade() -> None:
    for table, trigger in (
        ("production_cost_lines", "production_cost_lines_immutable_after_posting"),
        ("production_run_outputs", "production_run_outputs_immutable_after_posting"),
        ("production_run_lines", "production_run_lines_immutable_after_posting"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.execute("DROP TRIGGER IF EXISTS production_runs_immutable_after_posting ON production_runs")
    op.execute("DROP FUNCTION IF EXISTS reject_posted_production_child_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reject_posted_production_run_mutation()")
    op.drop_constraint("ck_stock_movements_movement_type_valid", "stock_movements", type_="check")
    op.create_check_constraint(
        "ck_stock_movements_movement_type_valid",
        "stock_movements",
        "movement_type IN ('OPENING', 'ADJUSTMENT', 'RECEIPT', 'REVERSAL')",
    )
    op.drop_constraint("ck_stock_movements_exactly_one_source_line", "stock_movements", type_="check")
    op.create_check_constraint(
        "ck_stock_movements_exactly_one_source_line",
        "stock_movements",
        "(stock_adjustment_line_id IS NOT NULL)::int + (purchase_receipt_line_id IS NOT NULL)::int = 1",
    )
    op.drop_constraint("uq_stock_movements_production_run_output", "stock_movements", type_="unique")
    op.drop_constraint("uq_stock_movements_production_run_line", "stock_movements", type_="unique")
    op.drop_constraint(
        "fk_stock_movements_production_run_output_id_production_run_outputs",
        "stock_movements", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_stock_movements_production_run_line_id_production_run_lines",
        "stock_movements", type_="foreignkey",
    )
    op.drop_column("stock_movements", "production_run_output_id")
    op.drop_column("stock_movements", "production_run_line_id")
    op.drop_index("ix_production_cost_lines_run", table_name="production_cost_lines")
    op.drop_table("production_cost_lines")
    op.drop_table("production_run_outputs")
    for name in (
        "ck_production_run_lines_line_cost_nonnegative",
        "ck_production_run_lines_unit_cost_nonnegative",
        "ck_production_run_lines_damaged_not_over_actual",
        "ck_production_run_lines_damaged_qty_nonnegative",
        "ck_production_run_lines_actual_qty_nonnegative",
    ):
        op.drop_constraint(name, "production_run_lines", type_="check")
    for column in (
        "line_cost", "unit_cost_snapshot", "variance_alert", "variance_percent",
        "variance_qty", "damaged_qty", "actual_qty",
    ):
        op.drop_column("production_run_lines", column)
    for name in (
        "ck_production_runs_posting_cost_state_consistent",
        "ck_production_runs_unit_cost_nonnegative",
        "ck_production_runs_total_cost_nonnegative",
        "ck_production_runs_actual_output_positive",
        "ck_production_runs_variance_tolerance_nonnegative",
    ):
        op.drop_constraint(name, "production_runs", type_="check")
    for column in (
        "wastage_note", "cost_per_good_unit", "total_run_cost", "yield_variance_alert",
        "yield_variance_percent", "yield_variance_qty", "actual_good_output_qty",
        "variance_tolerance_percent",
    ):
        op.drop_column("production_runs", column)
    op.drop_constraint(
        "fk_production_runs_finished_inventory_item_id_inventory_items",
        "production_runs", type_="foreignkey",
    )
    op.drop_column("production_runs", "finished_inventory_item_id")
