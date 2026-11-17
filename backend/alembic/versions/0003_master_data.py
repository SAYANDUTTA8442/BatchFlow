"""Create master-data entities for inventory, products, customers and suppliers.

Revision ID: 0003_master_data
Revises: 0002_identity_and_sessions
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_master_data"
down_revision: str | None = "0002_identity_and_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "unit_conversions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("from_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("to_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("factor", sa.Numeric(18, 9), nullable=False),
        sa.CheckConstraint("factor > 0", name="ck_unit_conversions_factor_positive"),
        sa.CheckConstraint("from_unit_id <> to_unit_id", name="ck_unit_conversions_different_units"),
        sa.ForeignKeyConstraint(["from_unit_id"], ["units.id"], name="fk_unit_conversions_from_unit_id_units"),
        sa.ForeignKeyConstraint(["to_unit_id"], ["units.id"], name="fk_unit_conversions_to_unit_id_units"),
        sa.PrimaryKeyConstraint("id", name="pk_unit_conversions"),
        sa.UniqueConstraint("from_unit_id", "to_unit_id", name="uq_unit_conversions_pair"),
    )
    op.create_index("ix_unit_conversions_to_unit", "unit_conversions", ["to_unit_id"])

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("base_unit_id", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("category IN ('RAW_MATERIAL', 'PACKAGING', 'FINISHED_GOOD')", name="ck_inventory_items_category_valid"),
        sa.ForeignKeyConstraint(["base_unit_id"], ["units.id"], name="fk_inventory_items_base_unit_id_units"),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_items"),
        sa.UniqueConstraint("code", name="uq_inventory_items_code"),
    )
    op.create_index("ix_inventory_items_base_unit", "inventory_items", ["base_unit_id"])
    op.create_index("ix_inventory_items_category", "inventory_items", ["category"])

    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), nullable=False),
        sa.Column("sku", sa.String(60), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("pack_size_value", sa.Numeric(18, 6)),
        sa.Column("pack_size_unit_id", sa.BigInteger()),
        sa.Column("hsn_code", sa.String(20)),
        sa.Column("default_selling_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("pack_size_value IS NULL OR pack_size_value > 0", name="ck_products_pack_size_positive"),
        sa.CheckConstraint("default_selling_price >= 0", name="ck_products_selling_price_nonnegative"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], name="fk_products_inventory_item_id_inventory_items"),
        sa.ForeignKeyConstraint(["pack_size_unit_id"], ["units.id"], name="fk_products_pack_size_unit_id_units"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("inventory_item_id", name="uq_products_inventory_item_id"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )
    op.create_index("ix_products_pack_size_unit", "products", ["pack_size_unit_id"])

    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("customer_code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("customer_type", sa.String(20), nullable=False),
        sa.Column("billing_address", sa.Text()),
        sa.Column("shipping_address", sa.Text()),
        sa.Column("state_code", sa.CHAR(2), nullable=False),
        sa.Column("gstin", sa.String(15)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("customer_type IN ('RETAILER', 'DISTRIBUTOR')", name="ck_customers_customer_type_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("customer_code", name="uq_customers_customer_code"),
    )
    op.create_index("ix_customers_state_code", "customers", ["state_code"])

    op.create_table(
        "customer_salesmen",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("salesman_user_id", sa.BigInteger(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_by_user_id", sa.BigInteger()),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_customer_salesmen_customer_id_customers", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["salesman_user_id"], ["users.id"], name="fk_customer_salesmen_salesman_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], name="fk_customer_salesmen_assigned_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("customer_id", "salesman_user_id", name="pk_customer_salesmen"),
    )
    op.create_index("ix_customer_salesmen_salesman", "customer_salesmen", ["salesman_user_id"])

    op.create_table(
        "suppliers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("supplier_code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("state_code", sa.CHAR(2)),
        sa.Column("gstin", sa.String(15)),
        sa.Column("phone", sa.String(30)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_suppliers"),
        sa.UniqueConstraint("supplier_code", name="uq_suppliers_supplier_code"),
    )

    op.create_table(
        "inventory_locations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_locations"),
        sa.UniqueConstraint("code", name="uq_inventory_locations_code"),
    )


def downgrade() -> None:
    op.drop_table("inventory_locations")
    op.drop_table("suppliers")
    op.drop_index("ix_customer_salesmen_salesman", table_name="customer_salesmen")
    op.drop_table("customer_salesmen")
    op.drop_index("ix_customers_state_code", table_name="customers")
    op.drop_table("customers")
    op.drop_index("ix_products_pack_size_unit", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_inventory_items_category", table_name="inventory_items")
    op.drop_index("ix_inventory_items_base_unit", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_index("ix_unit_conversions_to_unit", table_name="unit_conversions")
    op.drop_table("unit_conversions")
