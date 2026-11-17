from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Numeric,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("order_number", name="uq_sales_orders_number"),
        CheckConstraint(
            "status IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED', 'INVOICED', 'DISPATCHED')",
            name="status_valid",
        ),
        Index("ix_sales_orders_status_submitted", "status", "submitted_at"),
        Index("ix_sales_orders_salesman_submitted", "salesman_user_id", "submitted_at"),
        Index("ix_sales_orders_customer_submitted", "customer_id", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_number: Mapped[str] = mapped_column(String(60), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    salesman_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'SUBMITTED'"))
    submitted_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="SalesOrderLine.id"
    )


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint("sales_order_id", "product_id", name="uq_sales_order_lines_product"),
        CheckConstraint("submitted_quantity > 0", name="submitted_quantity_positive"),
        CheckConstraint("submitted_unit_price >= 0", name="submitted_price_nonnegative"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint("line_taxable_value >= 0", name="taxable_value_nonnegative"),
        Index("ix_sales_order_lines_product", "product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    hsn_snapshot: Mapped[str | None] = mapped_column(String(20))
    submitted_quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    submitted_unit_price: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    quantity: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    line_taxable_value: Mapped[object] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    order: Mapped[SalesOrder] = relationship(back_populates="lines")
