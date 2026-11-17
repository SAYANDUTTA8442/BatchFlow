from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    CustomerSalesman,
    InventoryItem,
    InventoryLocation,
    Product,
    Role,
    Supplier,
    Unit,
    UnitConversion,
    User,
    UserRole,
)


def _conflict(exc: IntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="A master-data code or relationship already exists",
    )


def _active_unit(db: Session, unit_id: int) -> Unit:
    unit = db.get(Unit, unit_id)
    if unit is None or not unit.is_active:
        raise HTTPException(status_code=422, detail="Unit does not exist or is inactive")
    return unit


def _validate_salesmen(db: Session, user_ids: list[int]) -> list[int]:
    if len(user_ids) != len(set(user_ids)):
        raise HTTPException(status_code=422, detail="Duplicate salesman user id")
    if not user_ids:
        return []
    valid_ids = set(
        db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.id.in_(user_ids),
                User.is_active.is_(True),
                Role.code == "salesman",
            )
        ).all()
    )
    if valid_ids != set(user_ids):
        raise HTTPException(status_code=422, detail="Every assigned user must be an active salesman")
    return user_ids


def create_inventory_item(db: Session, payload) -> InventoryItem:
    db.rollback()
    try:
        with db.begin():
            _active_unit(db, payload.base_unit_id)
            item = InventoryItem(**payload.model_dump())
            db.add(item)
            db.flush()
        return item
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def update_inventory_item(db: Session, item_id: int, payload) -> InventoryItem:
    db.rollback()
    try:
        with db.begin():
            item = db.get(InventoryItem, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            values = payload.model_dump(exclude_unset=True)
            if "base_unit_id" in values and values["base_unit_id"] is not None:
                _active_unit(db, values["base_unit_id"])
            for key, value in values.items():
                setattr(item, key, value)
        return item
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def create_product(db: Session, payload) -> Product:
    db.rollback()
    try:
        with db.begin():
            item = db.get(InventoryItem, payload.inventory_item_id)
            if item is None or not item.is_active or item.category != "FINISHED_GOOD":
                raise HTTPException(status_code=422, detail="Product must reference an active FINISHED_GOOD item")
            if payload.pack_size_unit_id is not None:
                _active_unit(db, payload.pack_size_unit_id)
            product = Product(**payload.model_dump())
            db.add(product)
            db.flush()
        return product
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def update_product(db: Session, product_id: int, payload) -> Product:
    db.rollback()
    try:
        with db.begin():
            product = db.get(Product, product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            values = payload.model_dump(exclude_unset=True)
            if values.get("pack_size_unit_id") is not None:
                _active_unit(db, values["pack_size_unit_id"])
            for key, value in values.items():
                setattr(product, key, value)
        return product
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def create_customer(db: Session, payload, actor_user_id: int) -> Customer:
    db.rollback()
    try:
        with db.begin():
            salesman_ids = _validate_salesmen(db, payload.salesman_user_ids)
            values = payload.model_dump(exclude={"salesman_user_ids"})
            customer = Customer(**values)
            db.add(customer)
            db.flush()
            for salesman_id in salesman_ids:
                db.add(
                    CustomerSalesman(
                        customer_id=customer.id,
                        salesman_user_id=salesman_id,
                        assigned_by_user_id=actor_user_id,
                    )
                )
        return customer
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def update_customer(db: Session, customer_id: int, payload, actor_user_id: int) -> Customer:
    db.rollback()
    try:
        with db.begin():
            customer = db.get(Customer, customer_id)
            if customer is None:
                raise HTTPException(status_code=404, detail="Customer not found")
            values = payload.model_dump(exclude_unset=True)
            salesman_ids = values.pop("salesman_user_ids", None)
            for key, value in values.items():
                setattr(customer, key, value)
            if salesman_ids is not None:
                validated_ids = _validate_salesmen(db, salesman_ids)
                db.execute(
                    delete(CustomerSalesman).where(CustomerSalesman.customer_id == customer_id)
                )
                for salesman_id in validated_ids:
                    db.add(
                        CustomerSalesman(
                            customer_id=customer_id,
                            salesman_user_id=salesman_id,
                            assigned_by_user_id=actor_user_id,
                        )
                    )
        return customer
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def create_supplier(db: Session, payload) -> Supplier:
    db.rollback()
    try:
        with db.begin():
            supplier = Supplier(**payload.model_dump())
            db.add(supplier)
            db.flush()
        return supplier
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def create_unit_conversion(db: Session, payload) -> UnitConversion:
    db.rollback()
    try:
        with db.begin():
            from_unit = _active_unit(db, payload.from_unit_id)
            to_unit = _active_unit(db, payload.to_unit_id)
            if from_unit.id == to_unit.id or from_unit.dimension != to_unit.dimension:
                raise HTTPException(status_code=422, detail="Units must be distinct and dimensionally compatible")
            conversion = UnitConversion(**payload.model_dump())
            db.add(conversion)
            db.flush()
        return conversion
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def create_inventory_location(db: Session, payload) -> InventoryLocation:
    db.rollback()
    try:
        with db.begin():
            location = InventoryLocation(**payload.model_dump())
            db.add(location)
            db.flush()
        return location
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc) from exc


def customer_read(db: Session, customer: Customer) -> dict:
    salesman_ids = db.scalars(
        select(CustomerSalesman.salesman_user_id)
        .where(CustomerSalesman.customer_id == customer.id)
        .order_by(CustomerSalesman.salesman_user_id)
    ).all()
    return {
        "id": customer.id,
        "customer_code": customer.customer_code,
        "name": customer.name,
        "customer_type": customer.customer_type,
        "billing_address": customer.billing_address,
        "shipping_address": customer.shipping_address,
        "state_code": customer.state_code,
        "gstin": customer.gstin,
        "is_active": customer.is_active,
        "salesman_user_ids": list(salesman_ids),
    }
