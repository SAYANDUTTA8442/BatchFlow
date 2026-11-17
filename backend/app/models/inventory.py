from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockAdjustment(Base):
    __tablename__ = "stock_adjustments"
    __table_args__ = (
        UniqueConstraint("adjustment_number", name="uq_stock_adjustments_number"),
        CheckConstraint(
            "reason IN ('OPENING_BALANCE', 'COUNT_CORRECTION', 'PRODUCTION_REVERSAL', 'OTHER')",
            name="reason_valid",
        ),
        CheckConstraint("status IN ('DRAFT', 'POSTED')", name="status_valid"),
        CheckConstraint(
            "(status = 'DRAFT' AND posted_at IS NULL AND posted_by_user_id IS NULL) OR "
            "(status = 'POSTED' AND posted_at IS NOT NULL AND posted_by_user_id IS NOT NULL)",
            name="posting_state_consistent",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    adjustment_number: Mapped[str] = mapped_column(String(60), nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'DRAFT'"))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockAdjustmentLine(Base):
    __tablename__ = "stock_adjustment_lines"
    __table_args__ = (
        UniqueConstraint(
            "stock_adjustment_id",
            "inventory_item_id",
            "inventory_location_id",
            name="uq_stock_adjustment_lines_item_location",
        ),
        CheckConstraint("quantity_delta <> 0", name="quantity_nonzero"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_nonnegative"),
        Index("ix_stock_adjustment_lines_item_location", "inventory_item_id", "inventory_location_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    stock_adjustment_id: Mapped[int] = mapped_column(
        ForeignKey("stock_adjustments.id", ondelete="RESTRICT"), nullable=False
    )
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    inventory_location_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_delta: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost: Mapped[object | None] = mapped_column(Numeric(18, 6))
    note: Mapped[str | None] = mapped_column(Text)


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        CheckConstraint("on_hand_qty >= 0", name="on_hand_nonnegative"),
        Index("ix_inventory_balances_location_item", "inventory_location_id", "inventory_item_id"),
    )

    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), primary_key=True
    )
    inventory_location_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"), primary_key=True
    )
    on_hand_qty: Mapped[object] = mapped_column(
        Numeric(18, 6), nullable=False, server_default=text("0")
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InventoryValuation(Base):
    __tablename__ = "inventory_valuations"
    __table_args__ = (
        CheckConstraint("valued_qty >= 0", name="valued_qty_nonnegative"),
        CheckConstraint("inventory_value >= 0", name="inventory_value_nonnegative"),
        CheckConstraint("average_unit_cost >= 0", name="average_unit_cost_nonnegative"),
        CheckConstraint(
            "valued_qty > 0 OR (inventory_value = 0 AND average_unit_cost = 0)",
            name="zero_quantity_zero_value",
        ),
    )

    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), primary_key=True
    )
    inventory_location_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"), primary_key=True
    )
    valued_qty: Mapped[object] = mapped_column(
        Numeric(18, 6), nullable=False, server_default=text("0")
    )
    inventory_value: Mapped[object] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    average_unit_cost: Mapped[object] = mapped_column(
        Numeric(18, 6), nullable=False, server_default=text("0")
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('OPENING', 'ADJUSTMENT', 'REVERSAL')",
            name="movement_type_valid",
        ),
        CheckConstraint("quantity_delta <> 0", name="quantity_nonzero"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_nonnegative"),
        CheckConstraint("extended_cost IS NULL OR extended_cost >= 0", name="extended_cost_nonnegative"),
        UniqueConstraint("stock_adjustment_line_id", name="uq_stock_movements_adjustment_line"),
        UniqueConstraint("reverses_movement_id", name="uq_stock_movements_reversal"),
        Index("ix_stock_movements_item_location_posted", "inventory_item_id", "inventory_location_id", "posted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    inventory_location_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_delta: Mapped[object] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost: Mapped[object | None] = mapped_column(Numeric(18, 6))
    extended_cost: Mapped[object | None] = mapped_column(Numeric(18, 2))
    stock_adjustment_line_id: Mapped[int] = mapped_column(
        ForeignKey("stock_adjustment_lines.id", ondelete="RESTRICT"), nullable=False
    )
    reverses_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="RESTRICT")
    )
    posted_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity_time", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_actor_time", "actor_user_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    after_data: Mapped[dict | None] = mapped_column(JSONB)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "actor_user_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"
        ),
        CheckConstraint(
            "(response_status IS NULL AND response_body IS NULL AND completed_at IS NULL) OR "
            "(response_status IS NOT NULL AND response_body IS NOT NULL AND completed_at IS NOT NULL)",
            name="completion_consistent",
        ),
        Index("ix_idempotency_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_status: Mapped[int | None] = mapped_column()
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
