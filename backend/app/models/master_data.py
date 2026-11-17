from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnitConversion(Base):
    __tablename__ = "unit_conversions"
    __table_args__ = (
        UniqueConstraint("from_unit_id", "to_unit_id", name="uq_unit_conversions_pair"),
        CheckConstraint("factor > 0", name="factor_positive"),
        CheckConstraint("from_unit_id <> to_unit_id", name="different_units"),
        Index("ix_unit_conversions_to_unit", "to_unit_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    from_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    to_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    factor: Mapped[object] = mapped_column(Numeric(18, 9), nullable=False)


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("code", name="uq_inventory_items_code"),
        CheckConstraint(
            "category IN ('RAW_MATERIAL', 'PACKAGING', 'FINISHED_GOOD')",
            name="category_valid",
        ),
        Index("ix_inventory_items_base_unit", "base_unit_id"),
        Index("ix_inventory_items_category", "category"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    base_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("inventory_item_id", name="uq_products_inventory_item_id"),
        UniqueConstraint("sku", name="uq_products_sku"),
        CheckConstraint("pack_size_value IS NULL OR pack_size_value > 0", name="pack_size_positive"),
        CheckConstraint("default_selling_price >= 0", name="selling_price_nonnegative"),
        Index("ix_products_pack_size_unit", "pack_size_unit_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    pack_size_value: Mapped[object | None] = mapped_column(Numeric(18, 6))
    pack_size_unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"))
    hsn_code: Mapped[str | None] = mapped_column(String(20))
    default_selling_price: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("customer_code", name="uq_customers_customer_code"),
        CheckConstraint("customer_type IN ('RETAILER', 'DISTRIBUTOR')", name="customer_type_valid"),
        Index("ix_customers_state_code", "state_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    customer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CustomerSalesman(Base):
    __tablename__ = "customer_salesmen"
    __table_args__ = (Index("ix_customer_salesmen_salesman", "salesman_user_id"),)

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True)
    salesman_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    assigned_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    assigned_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("supplier_code", name="uq_suppliers_supplier_code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    supplier_code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(CHAR(2))
    gstin: Mapped[str | None] = mapped_column(String(15))
    phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class InventoryLocation(Base):
    __tablename__ = "inventory_locations"
    __table_args__ = (UniqueConstraint("code", name="uq_inventory_locations_code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
