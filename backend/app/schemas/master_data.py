from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UnitRead(ORMRead):
    id: int
    code: str
    name: str
    dimension: str
    input_decimal_places: int
    is_base_unit: bool
    is_active: bool


class InventoryItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=160)
    category: Literal["RAW_MATERIAL", "PACKAGING", "FINISHED_GOOD"]
    base_unit_id: int = Field(gt=0)
    is_active: bool = True


class InventoryItemUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=60)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_unit_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class InventoryItemRead(ORMRead):
    id: int
    code: str
    name: str
    category: str
    base_unit_id: int
    is_active: bool


class ProductCreate(BaseModel):
    inventory_item_id: int = Field(gt=0)
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=160)
    pack_size_value: Decimal | None = Field(default=None, gt=0)
    pack_size_unit_id: int | None = Field(default=None, gt=0)
    hsn_code: str | None = Field(default=None, max_length=20)
    default_selling_price: Decimal = Field(ge=0)
    is_active: bool = True


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=60)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    pack_size_value: Decimal | None = Field(default=None, gt=0)
    pack_size_unit_id: int | None = Field(default=None, gt=0)
    hsn_code: str | None = Field(default=None, max_length=20)
    default_selling_price: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductRead(ORMRead):
    id: int
    inventory_item_id: int
    sku: str
    name: str
    pack_size_value: Decimal | None
    pack_size_unit_id: int | None
    hsn_code: str | None
    default_selling_price: Decimal
    is_active: bool


class CustomerCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=180)
    customer_type: Literal["RETAILER", "DISTRIBUTOR"]
    billing_address: str | None = None
    shipping_address: str | None = None
    state_code: str = Field(pattern=r"^[0-9]{2}$")
    gstin: str | None = Field(default=None, min_length=15, max_length=15, pattern=r"^[0-9A-Z]{15}$")
    is_active: bool = True
    salesman_user_ids: list[int] = Field(default_factory=list)


class CustomerUpdate(BaseModel):
    customer_code: str | None = Field(default=None, min_length=1, max_length=60)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    customer_type: Literal["RETAILER", "DISTRIBUTOR"] | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    state_code: str | None = Field(default=None, pattern=r"^[0-9]{2}$")
    gstin: str | None = Field(default=None, min_length=15, max_length=15, pattern=r"^[0-9A-Z]{15}$")
    is_active: bool | None = None
    salesman_user_ids: list[int] | None = None


class CustomerRead(ORMRead):
    id: int
    customer_code: str
    name: str
    customer_type: str
    billing_address: str | None
    shipping_address: str | None
    state_code: str
    gstin: str | None
    is_active: bool
    salesman_user_ids: list[int] = Field(default_factory=list)


class SupplierCreate(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=180)
    address: str | None = None
    state_code: str | None = Field(default=None, pattern=r"^[0-9]{2}$")
    gstin: str | None = Field(default=None, min_length=15, max_length=15, pattern=r"^[0-9A-Z]{15}$")
    phone: str | None = Field(default=None, max_length=30)
    is_active: bool = True


class SupplierRead(ORMRead):
    id: int
    supplier_code: str
    name: str
    address: str | None
    state_code: str | None
    gstin: str | None
    phone: str | None
    is_active: bool


class UnitConversionCreate(BaseModel):
    from_unit_id: int = Field(gt=0)
    to_unit_id: int = Field(gt=0)
    factor: Decimal = Field(gt=0)


class UnitConversionRead(ORMRead):
    id: int
    from_unit_id: int
    to_unit_id: int
    factor: Decimal


class InventoryLocationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class InventoryLocationRead(ORMRead):
    id: int
    code: str
    name: str
    is_active: bool
