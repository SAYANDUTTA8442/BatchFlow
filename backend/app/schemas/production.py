from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductionRunCreate(BaseModel):
    bom_id: int = Field(gt=0)
    production_date: date
    batch_multiplier: Decimal = Field(gt=0, allow_inf_nan=False)


class ProductionRunLineActual(BaseModel):
    line_id: int = Field(gt=0)
    actual_qty: Decimal = Field(ge=0, allow_inf_nan=False)
    damaged_qty: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)


class ProductionCostLineCreate(BaseModel):
    cost_type: Literal["LABOUR", "ENERGY", "OTHER"]
    description: str = Field(min_length=1, max_length=180)
    amount: Decimal = Field(ge=0, allow_inf_nan=False)


class ProductionRunPost(BaseModel):
    actual_lines: list[ProductionRunLineActual] = Field(min_length=1, max_length=200)
    actual_good_output_qty: Decimal = Field(gt=0, allow_inf_nan=False)
    cost_lines: list[ProductionCostLineCreate] = Field(default_factory=list, max_length=100)
    wastage_note: str | None = Field(default=None, max_length=2000)


class ProductionRunLineRead(ORMRead):
    id: int
    inventory_item_id: int
    line_type: str
    item_code_snapshot: str
    item_name_snapshot: str
    base_unit_code_snapshot: str
    quantity_per_batch_snapshot: Decimal
    planned_qty: Decimal
    actual_qty: Decimal | None
    damaged_qty: Decimal
    variance_qty: Decimal | None
    variance_percent: Decimal | None
    variance_alert: bool
    unit_cost_snapshot: Decimal | None
    line_cost: Decimal | None


class ProductionRunOutputRead(ORMRead):
    id: int
    product_id: int
    inventory_item_id: int
    good_qty: Decimal
    base_unit_code_snapshot: str


class ProductionCostLineRead(ORMRead):
    id: int
    cost_type: str
    description: str
    amount: Decimal


class ProductionRunRead(ORMRead):
    id: int
    run_number: str
    product_id: int
    finished_inventory_item_id: int
    product_sku_snapshot: str
    product_name_snapshot: str
    finished_item_code_snapshot: str
    finished_item_name_snapshot: str
    output_unit_code_snapshot: str
    bom_id: int
    bom_version_snapshot: int
    batch_multiplier: Decimal
    expected_output_qty: Decimal
    actual_good_output_qty: Decimal | None
    yield_variance_qty: Decimal | None
    yield_variance_percent: Decimal | None
    yield_variance_alert: bool
    variance_tolerance_percent: Decimal
    total_run_cost: Decimal | None
    cost_per_good_unit: Decimal | None
    wastage_note: str | None
    status: str
    production_date: date
    supervisor_user_id: int
    posted_at: datetime | None
    posted_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    lines: list[ProductionRunLineRead]
    outputs: list[ProductionRunOutputRead]
    cost_lines: list[ProductionCostLineRead]
