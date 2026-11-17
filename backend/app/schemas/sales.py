from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SalesOrderLineCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, allow_inf_nan=False)


class SalesOrderCreate(BaseModel):
    customer_id: int = Field(gt=0)
    lines: list[SalesOrderLineCreate] = Field(min_length=1, max_length=100)


class SalesOrderLineRead(ORMRead):
    id: int
    product_id: int
    sku_snapshot: str
    product_name_snapshot: str
    hsn_snapshot: str | None
    submitted_quantity: Decimal
    submitted_unit_price: Decimal
    quantity: Decimal
    unit_price: Decimal
    line_taxable_value: Decimal
    created_at: datetime


class SalesOrderRead(ORMRead):
    id: int
    order_number: str
    customer_id: int
    salesman_user_id: int
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: int | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[SalesOrderLineRead]
