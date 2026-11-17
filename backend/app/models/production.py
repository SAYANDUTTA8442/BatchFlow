from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProductionRun(Base):
    __tablename__ = "production_runs"
    __table_args__ = (
        UniqueConstraint("run_number", name="uq_production_runs_number"),
        CheckConstraint("bom_version_snapshot > 0", name="bom_version_positive"),
        CheckConstraint("batch_multiplier > 0", name="batch_multiplier_positive"),
        CheckConstraint("expected_output_qty > 0", name="expected_output_positive"),
        CheckConstraint("status IN ('DRAFT', 'POSTED', 'REVERSED')", name="status_valid"),
        CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL AND posted_by_user_id IS NULL) OR "
            "(status IN ('POSTED', 'REVERSED') AND posted_at IS NOT NULL AND posted_by_user_id IS NOT NULL)",
            name="posting_state_consistent",
        ),
        Index("ix_production_runs_date_status", "production_date", "status"),
        Index("ix_production_runs_product_date", "product_id", "production_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_number: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    product_sku_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    finished_item_code_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    finished_item_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    output_unit_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="RESTRICT"), nullable=False)
    bom_version_snapshot: Mapped[int] = mapped_column(nullable=False)
    batch_multiplier: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    expected_output_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'DRAFT'"))
    production_date: Mapped[object] = mapped_column(Date, nullable=False)
    supervisor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    posted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    lines: Mapped[list["ProductionRunLine"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ProductionRunLine.id"
    )


class ProductionRunLine(Base):
    __tablename__ = "production_run_lines"
    __table_args__ = (
        UniqueConstraint("production_run_id", "inventory_item_id", name="uq_production_run_lines_item"),
        CheckConstraint("line_type IN ('RAW_MATERIAL', 'PACKAGING')", name="line_type_valid"),
        CheckConstraint("quantity_per_batch_snapshot > 0", name="quantity_per_batch_positive"),
        CheckConstraint("planned_qty > 0", name="planned_qty_positive"),
        Index("ix_production_run_lines_inventory_item", "inventory_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    production_run_id: Mapped[int] = mapped_column(
        ForeignKey("production_runs.id", ondelete="RESTRICT"), nullable=False
    )
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    base_unit_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_per_batch_snapshot: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    planned_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    run: Mapped[ProductionRun] = relationship(back_populates="lines")
