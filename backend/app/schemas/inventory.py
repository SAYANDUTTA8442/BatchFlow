from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StockAdjustmentLineCreate(BaseModel):
    inventory_item_id: int = Field(gt=0)
    inventory_location_id: int = Field(gt=0)
    quantity_delta: Decimal = Field(allow_inf_nan=False)
    unit_cost: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=2000)


class StockAdjustmentCreate(BaseModel):
    adjustment_number: str = Field(min_length=1, max_length=60)
    reason: Literal["OPENING_BALANCE", "COUNT_CORRECTION", "PRODUCTION_REVERSAL", "OTHER"]
    note: str | None = Field(default=None, max_length=4000)
    lines: list[StockAdjustmentLineCreate] = Field(min_length=1, max_length=200)


class StockAdjustmentRead(ORMRead):
    id: int
    adjustment_number: str
    reason: str
    note: str | None
    status: str
    created_by_user_id: int
    posted_by_user_id: int | None
    posted_at: object | None
    created_at: object


class StockAdjustmentPostRead(BaseModel):
    adjustment_id: int
    status: Literal["POSTED"]
    movement_count: int


class InventoryBalanceRead(BaseModel):
    inventory_item_id: int
    inventory_location_id: int
    on_hand_qty: Decimal
    valued_qty: Decimal
    inventory_value: Decimal
    average_unit_cost: Decimal


class StockMovementRead(ORMRead):
    id: int
    inventory_item_id: int
    inventory_location_id: int
    movement_type: str
    quantity_delta: Decimal
    unit_cost: Decimal | None
    extended_cost: Decimal | None
    stock_adjustment_line_id: int
    reverses_movement_id: int | None
    posted_at: object
    posted_by_user_id: int | None
