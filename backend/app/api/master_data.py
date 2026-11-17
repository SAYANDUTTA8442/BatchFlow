from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_current_principal, require_roles
from app.db.session import get_db
from app.models import (
    CustomerSalesman,
    InventoryItem,
    InventoryLocation,
    Supplier,
    Unit,
    UnitConversion,
)
from app.schemas.master_data import (
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    InventoryLocationCreate,
    InventoryLocationRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    SupplierCreate,
    SupplierRead,
    UnitConversionCreate,
    UnitConversionRead,
    UnitRead,
)
from app.services.master_data import (
    create_customer,
    create_inventory_item,
    create_inventory_location,
    create_product,
    create_supplier,
    create_unit_conversion,
    customer_read,
    update_customer,
    update_inventory_item,
    update_product,
)


router = APIRouter(prefix="/api/master-data", tags=["master data"])
Db = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
AdminDep = Annotated[Principal, Depends(require_roles("admin", "owner"))]


@router.get("/units", response_model=list[UnitRead])
def list_units(db: Db, principal: PrincipalDep):
    return db.scalars(select(Unit).where(Unit.is_active.is_(True)).order_by(Unit.code)).all()


@router.get("/unit-conversions", response_model=list[UnitConversionRead])
def list_unit_conversions(db: Db, principal: PrincipalDep):
    return db.scalars(select(UnitConversion).order_by(UnitConversion.from_unit_id)).all()


@router.post("/unit-conversions", response_model=UnitConversionRead, status_code=201)
def add_unit_conversion(payload: UnitConversionCreate, db: Db, principal: AdminDep):
    return create_unit_conversion(db, payload)


@router.get("/inventory-items", response_model=list[InventoryItemRead])
def list_inventory_items(db: Db, principal: Annotated[Principal, Depends(require_roles("admin", "owner", "auditor", "production"))]):
    return db.scalars(select(InventoryItem).order_by(InventoryItem.code).limit(500)).all()


@router.post("/inventory-items", response_model=InventoryItemRead, status_code=201)
def add_inventory_item(payload: InventoryItemCreate, db: Db, principal: AdminDep):
    return create_inventory_item(db, payload)


@router.put("/inventory-items/{item_id}", response_model=InventoryItemRead)
def edit_inventory_item(item_id: int, payload: InventoryItemUpdate, db: Db, principal: AdminDep):
    return update_inventory_item(db, item_id, payload)


@router.get("/products", response_model=list[ProductRead])
def list_products(db: Db, principal: PrincipalDep):
    return db.scalars(select(Product).order_by(Product.sku).limit(500)).all()


@router.post("/products", response_model=ProductRead, status_code=201)
def add_product(payload: ProductCreate, db: Db, principal: AdminDep):
    return create_product(db, payload)


@router.put("/products/{product_id}", response_model=ProductRead)
def edit_product(product_id: int, payload: ProductUpdate, db: Db, principal: AdminDep):
    return update_product(db, product_id, payload)


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(
    db: Db,
    principal: Annotated[Principal, Depends(require_roles("admin", "owner", "auditor", "salesman"))],
):
    query = select(Customer).order_by(Customer.customer_code)
    if "salesman" in principal.roles and not principal.roles.intersection({"admin", "owner", "auditor"}):
        query = query.join(
            CustomerSalesman,
            CustomerSalesman.customer_id == Customer.id,
        ).where(CustomerSalesman.salesman_user_id == principal.user.id)
    customers = db.scalars(query.limit(500)).unique().all()
    return [customer_read(db, customer) for customer in customers]


@router.post("/customers", response_model=CustomerRead, status_code=201)
def add_customer(payload: CustomerCreate, db: Db, principal: AdminDep):
    customer = create_customer(db, payload, principal.user.id)
    return customer_read(db, customer)


@router.put("/customers/{customer_id}", response_model=CustomerRead)
def edit_customer(customer_id: int, payload: CustomerUpdate, db: Db, principal: AdminDep):
    customer = update_customer(db, customer_id, payload, principal.user.id)
    return customer_read(db, customer)


@router.get("/suppliers", response_model=list[SupplierRead])
def list_suppliers(
    db: Db,
    principal: Annotated[Principal, Depends(require_roles("admin", "owner", "auditor"))],
):
    return db.scalars(select(Supplier).order_by(Supplier.supplier_code).limit(500)).all()


@router.post("/suppliers", response_model=SupplierRead, status_code=201)
def add_supplier(payload: SupplierCreate, db: Db, principal: AdminDep):
    return create_supplier(db, payload)


@router.get("/locations", response_model=list[InventoryLocationRead])
def list_locations(db: Db, principal: PrincipalDep):
    return db.scalars(
        select(InventoryLocation).where(InventoryLocation.is_active.is_(True)).order_by(InventoryLocation.code)
    ).all()


@router.post("/locations", response_model=InventoryLocationRead, status_code=201)
def add_location(payload: InventoryLocationCreate, db: Db, principal: AdminDep):
    return create_inventory_location(db, payload)
