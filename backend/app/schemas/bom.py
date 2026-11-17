from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BomLineInput(BaseModel):
    inventory_item_id: int = Field(gt=0)
    line_type: Literal["RAW_MATERIAL", "PACKAGING"]
    quantity_per_batch: Decimal = Field(gt=0, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=2000)


class BomCreate(BaseModel):
    product_id: int = Field(gt=0)
    expected_output_qty: Decimal = Field(gt=0, allow_inf_nan=False)
    effective_from: date
    effective_to: date | None = None
    lines: list[BomLineInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_effective_range(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        return self


class BomUpdate(BaseModel):
    expected_output_qty: Decimal = Field(gt=0, allow_inf_nan=False)
    effective_from: date
    effective_to: date | None = None
    lines: list[BomLineInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_effective_range(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        return self


class BomLineRead(ORMRead):
    id: int
    inventory_item_id: int
    line_type: str
    quantity_per_batch: Decimal
    notes: str | None


class BomRead(ORMRead):
    id: int
    product_id: int
    version: int
    status: str
    expected_output_qty: Decimal
    effective_from: date
    effective_to: date | None
    created_by_user_id: int
    created_at: object
    lines: list[BomLineRead]


class BomScaleLine(BaseModel):
    inventory_item_id: int
    line_type: str
    quantity_per_batch: Decimal
    planned_quantity: Decimal


class BomScaleRead(BaseModel):
    bom_id: int
    product_id: int
    version: int
    batch_multiplier: Decimal
    expected_output_qty_per_batch: Decimal
    expected_good_output_qty: Decimal
    lines: list[BomScaleLine]


class BomRetire(BaseModel):
    effective_to: date
