from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductionRunCreate(BaseModel):
    bom_id: int = Field(gt=0)
    production_date: date
    batch_multiplier: Decimal = Field(gt=0, allow_inf_nan=False)


class ProductionRunLineRead(ORMRead):
    id: int
    inventory_item_id: int
    line_type: str
    item_code_snapshot: str
    item_name_snapshot: str
    base_unit_code_snapshot: str
    quantity_per_batch_snapshot: Decimal
    planned_qty: Decimal


class ProductionRunRead(ORMRead):
    id: int
    run_number: str
    product_id: int
    product_sku_snapshot: str
    product_name_snapshot: str
    finished_item_code_snapshot: str
    finished_item_name_snapshot: str
    output_unit_code_snapshot: str
    bom_id: int
    bom_version_snapshot: int
    batch_multiplier: Decimal
    expected_output_qty: Decimal
    status: str
    production_date: date
    supervisor_user_id: int
    posted_at: object | None
    posted_by_user_id: int | None
    created_at: object
    updated_at: object
    lines: list[ProductionRunLineRead]
