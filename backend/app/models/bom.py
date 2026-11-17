from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index,
    Integer, Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Bom(Base):
    __tablename__ = "boms"
    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_boms_product_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="status_valid"),
        CheckConstraint("expected_output_qty > 0", name="expected_output_positive"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="effective_range_valid"),
        Index("ix_boms_product_status_effective", "product_id", "status", "effective_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'DRAFT'"))
    expected_output_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    effective_from: Mapped[object] = mapped_column(Date, nullable=False)
    effective_to: Mapped[object | None] = mapped_column(Date)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lines: Mapped[list["BomLine"]] = relationship(
        back_populates="bom", cascade="all, delete-orphan", order_by="BomLine.inventory_item_id"
    )


class BomLine(Base):
    __tablename__ = "bom_lines"
    __table_args__ = (
        UniqueConstraint("bom_id", "inventory_item_id", name="uq_bom_lines_item"),
        CheckConstraint("line_type IN ('RAW_MATERIAL', 'PACKAGING')", name="line_type_valid"),
        CheckConstraint("quantity_per_batch > 0", name="quantity_positive"),
        Index("ix_bom_lines_inventory_item", "inventory_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="RESTRICT"), nullable=False)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_per_batch: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    bom: Mapped[Bom] = relationship(back_populates="lines")
