"""Add versioned bills of materials.

Revision ID: 0006_boms
Revises: 0005_purchase_receipts
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_boms"
down_revision: str | None = "0005_purchase_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "boms",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("expected_output_qty", sa.Numeric(18, 6), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_boms_version_positive"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="ck_boms_status_valid"),
        sa.CheckConstraint("expected_output_qty > 0", name="ck_boms_expected_output_positive"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_boms_effective_range_valid"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_boms_product_id_products", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_boms_created_by_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_boms"),
        sa.UniqueConstraint("product_id", "version", name="uq_boms_product_version"),
    )
    op.create_index("ix_boms_product_status_effective", "boms", ["product_id", "status", "effective_from"])
    op.create_table(
        "bom_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("bom_id", sa.BigInteger(), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("line_type", sa.String(20), nullable=False),
        sa.Column("quantity_per_batch", sa.Numeric(18, 6), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.CheckConstraint("line_type IN ('RAW_MATERIAL', 'PACKAGING')", name="ck_bom_lines_line_type_valid"),
        sa.CheckConstraint("quantity_per_batch > 0", name="ck_bom_lines_quantity_positive"),
        sa.ForeignKeyConstraint(["bom_id"], ["boms.id"], name="fk_bom_lines_bom_id_boms", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_bom_lines_inventory_item_id_inventory_items", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_bom_lines"),
        sa.UniqueConstraint("bom_id", "inventory_item_id", name="uq_bom_lines_item"),
    )
    op.create_index("ix_bom_lines_inventory_item", "bom_lines", ["inventory_item_id"])

    op.execute("""
        CREATE FUNCTION reject_non_draft_bom_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'DRAFT' THEN
                IF TG_OP = 'UPDATE'
                   AND OLD.status = 'ACTIVE'
                   AND NEW.status = 'RETIRED'
                   AND (to_jsonb(NEW) - 'status' - 'effective_to') =
                       (to_jsonb(OLD) - 'status' - 'effective_to')
                   AND NEW.effective_to IS NOT NULL THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'Activated BOM versions are immutable'
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
        CREATE TRIGGER boms_immutable_after_activation
        BEFORE UPDATE OR DELETE ON boms
        FOR EACH ROW EXECUTE FUNCTION reject_non_draft_bom_mutation();
    """)
    op.execute("""
        CREATE FUNCTION reject_non_draft_bom_line_mutation() RETURNS trigger AS $$
        DECLARE
            parent_status text;
            parent_id bigint;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                parent_id := OLD.bom_id;
            ELSE
                parent_id := NEW.bom_id;
            END IF;
            SELECT status INTO parent_status FROM boms WHERE id = parent_id;
            IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'Lines of activated BOM versions are immutable'
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
        CREATE TRIGGER bom_lines_immutable_after_activation
        BEFORE INSERT OR UPDATE OR DELETE ON bom_lines
        FOR EACH ROW EXECUTE FUNCTION reject_non_draft_bom_line_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS bom_lines_immutable_after_activation ON bom_lines")
    op.execute("DROP TRIGGER IF EXISTS boms_immutable_after_activation ON boms")
    op.execute("DROP FUNCTION IF EXISTS reject_non_draft_bom_line_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reject_non_draft_bom_mutation()")
    op.drop_index("ix_bom_lines_inventory_item", table_name="bom_lines")
    op.drop_table("bom_lines")
    op.drop_index("ix_boms_product_status_effective", table_name="boms")
    op.drop_table("boms")
