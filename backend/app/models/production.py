from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index,
    Numeric, String, UniqueConstraint, func, text,
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
        CheckConstraint("variance_tolerance_percent >= 0", name="variance_tolerance_nonnegative"),
        CheckConstraint("actual_good_output_qty IS NULL OR actual_good_output_qty > 0", name="actual_output_positive"),
        CheckConstraint("total_run_cost IS NULL OR total_run_cost >= 0", name="total_cost_nonnegative"),
        CheckConstraint("cost_per_good_unit IS NULL OR cost_per_good_unit >= 0", name="unit_cost_nonnegative"),
        CheckConstraint("status IN ('DRAFT', 'POSTED', 'REVERSED')", name="status_valid"),
        CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL AND posted_by_user_id IS NULL) OR "
            "(status IN ('POSTED', 'REVERSED') AND posted_at IS NOT NULL AND posted_by_user_id IS NOT NULL)",
            name="posting_state_consistent",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND actual_good_output_qty IS NULL AND total_run_cost IS NULL AND cost_per_good_unit IS NULL) OR "
            "(status IN ('POSTED', 'REVERSED') AND actual_good_output_qty IS NOT NULL AND total_run_cost IS NOT NULL AND cost_per_good_unit IS NOT NULL)",
            name="posting_cost_state_consistent",
        ),
        Index("ix_production_runs_date_status", "production_date", "status"),
        Index("ix_production_runs_product_date", "product_id", "production_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_number: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    finished_inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_sku_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    finished_item_code_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    finished_item_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    output_unit_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="RESTRICT"), nullable=False)
    bom_version_snapshot: Mapped[int] = mapped_column(nullable=False)
    batch_multiplier: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    expected_output_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    actual_good_output_qty: Mapped[object | None] = mapped_column(Numeric(18, 6))
    yield_variance_qty: Mapped[object | None] = mapped_column(Numeric(18, 6))
    yield_variance_percent: Mapped[object | None] = mapped_column(Numeric(12, 4))
    yield_variance_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    variance_tolerance_percent: Mapped[object] = mapped_column(Numeric(12, 4), nullable=False, server_default=text("3.0000"))
    total_run_cost: Mapped[object | None] = mapped_column(Numeric(18, 2))
    cost_per_good_unit: Mapped[object | None] = mapped_column(Numeric(18, 6))
    wastage_note: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'DRAFT'"))
    production_date: Mapped[object] = mapped_column(Date, nullable=False)
    supervisor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    posted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    lines: Mapped[list["ProductionRunLine"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="ProductionRunLine.id")
    outputs: Mapped[list["ProductionRunOutput"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="ProductionRunOutput.id")
    cost_lines: Mapped[list["ProductionCostLine"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="ProductionCostLine.id")


class ProductionRunLine(Base):
    __tablename__ = "production_run_lines"
    __table_args__ = (
        UniqueConstraint("production_run_id", "inventory_item_id", name="uq_production_run_lines_item"),
        CheckConstraint("line_type IN ('RAW_MATERIAL', 'PACKAGING')", name="line_type_valid"),
        CheckConstraint("quantity_per_batch_snapshot > 0", name="quantity_per_batch_positive"),
        CheckConstraint("planned_qty > 0", name="planned_qty_positive"),
        CheckConstraint("actual_qty IS NULL OR actual_qty >= 0", name="actual_qty_nonnegative"),
        CheckConstraint("damaged_qty >= 0", name="damaged_qty_nonnegative"),
        CheckConstraint("actual_qty IS NULL OR damaged_qty <= actual_qty", name="damaged_not_over_actual"),
        CheckConstraint("unit_cost_snapshot IS NULL OR unit_cost_snapshot >= 0", name="unit_cost_nonnegative"),
        CheckConstraint("line_cost IS NULL OR line_cost >= 0", name="line_cost_nonnegative"),
        Index("ix_production_run_lines_inventory_item", "inventory_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    production_run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id", ondelete="RESTRICT"), nullable=False)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    base_unit_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_per_batch_snapshot: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    planned_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    actual_qty: Mapped[object | None] = mapped_column(Numeric(18, 6))
    damaged_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False, server_default=text("0"))
    variance_qty: Mapped[object | None] = mapped_column(Numeric(18, 6))
    variance_percent: Mapped[object | None] = mapped_column(Numeric(12, 4))
    variance_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    unit_cost_snapshot: Mapped[object | None] = mapped_column(Numeric(18, 6))
    line_cost: Mapped[object | None] = mapped_column(Numeric(18, 2))
    run: Mapped[ProductionRun] = relationship(back_populates="lines")


class ProductionRunOutput(Base):
    __tablename__ = "production_run_outputs"
    __table_args__ = (
        UniqueConstraint("production_run_id", name="uq_production_run_outputs_run"),
        CheckConstraint("good_qty > 0", name="good_qty_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    production_run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    good_qty: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    base_unit_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    run: Mapped[ProductionRun] = relationship(back_populates="outputs")


class ProductionCostLine(Base):
    __tablename__ = "production_cost_lines"
    __table_args__ = (
        CheckConstraint("cost_type IN ('LABOUR', 'ENERGY', 'OTHER')", name="cost_type_valid"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        Index("ix_production_cost_lines_run", "production_run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    production_run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id", ondelete="RESTRICT"), nullable=False)
    cost_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(180), nullable=False)
    amount: Mapped[object] = mapped_column(Numeric(18, 2), nullable=False)
    run: Mapped[ProductionRun] = relationship(back_populates="cost_lines")
