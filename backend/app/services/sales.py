import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditEvent, Customer, CustomerSalesman, IdempotencyRecord, InventoryItem,
    Product, SalesOrder, SalesOrderLine, Unit,
)


MONEY_SCALE = Decimal("0.01")
QUANTITY_SCALE = Decimal("0.000001")


def _load_order(db: Session, order_id: int) -> SalesOrder:
    order = db.scalar(
        select(SalesOrder)
        .options(selectinload(SalesOrder.lines))
        .where(SalesOrder.id == order_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Sales order not found")
    return order


def _visible_order_query(principal):
    query = select(SalesOrder).options(selectinload(SalesOrder.lines))
    if "salesman" in principal.roles and not principal.roles.intersection({"admin", "owner", "auditor"}):
        query = query.where(SalesOrder.salesman_user_id == principal.user.id)
    return query


def list_sales_orders(db: Session, principal, status_filter: str | None = None) -> list[SalesOrder]:
    query = _visible_order_query(principal).order_by(SalesOrder.submitted_at.desc(), SalesOrder.id.desc())
    if status_filter is not None:
        query = query.where(SalesOrder.status == status_filter)
    return list(db.scalars(query.limit(500)).unique().all())


def get_sales_order(db: Session, order_id: int, principal) -> SalesOrder:
    query = _visible_order_query(principal).where(SalesOrder.id == order_id)
    order = db.scalar(query)
    if order is None:
        # Do not disclose whether an order belonging to another salesman exists.
        raise HTTPException(status_code=404, detail="Sales order not found")
    return order


def submit_sales_order(db: Session, payload, actor_id: int, idempotency_key: str) -> SalesOrder:
    operation = "sales.order.submit"
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(f"{operation}:{canonical}".encode("utf-8")).hexdigest()
    db.rollback()
    try:
        with db.begin():
            db.execute(
                pg_insert(IdempotencyRecord)
                .values(
                    actor_user_id=actor_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        IdempotencyRecord.actor_user_id,
                        IdempotencyRecord.operation,
                        IdempotencyRecord.idempotency_key,
                    ]
                )
            )
            idem = db.scalar(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.actor_user_id == actor_id,
                    IdempotencyRecord.operation == operation,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if idem is None:
                raise HTTPException(status_code=500, detail="Could not claim idempotency key")
            if idem.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Idempotency key was used for a different request")
            if idem.completed_at is not None:
                target_order_id = int(idem.response_body["order_id"])
            else:
                customer = db.scalar(
                    select(Customer).where(Customer.id == payload.customer_id).with_for_update()
                )
                if customer is None or not customer.is_active:
                    raise HTTPException(status_code=422, detail="Customer does not exist or is inactive")

                actor_roles = db.execute(
                    select(CustomerSalesman.customer_id)
                    .where(
                        CustomerSalesman.customer_id == customer.id,
                        CustomerSalesman.salesman_user_id == actor_id,
                    )
                ).first()
                if actor_roles is None:
                    # Admin order entry is allowed by the requirements, but a salesman
                    # must be explicitly assigned to the selected customer.
                    from app.models import UserRole, Role
                    is_admin = db.scalar(
                        select(Role.id)
                        .join(UserRole, UserRole.role_id == Role.id)
                        .where(UserRole.user_id == actor_id, Role.code == "admin")
                        .limit(1)
                    ) is not None
                    if not is_admin:
                        raise HTTPException(status_code=403, detail="Customer is not assigned to this salesman")

                product_ids = [line.product_id for line in payload.lines]
                if len(product_ids) != len(set(product_ids)):
                    raise HTTPException(status_code=422, detail="An order cannot contain the same product twice")

                products = db.scalars(
                    select(Product)
                    .where(Product.id.in_(product_ids))
                    .order_by(Product.id)
                    .with_for_update()
                ).all()
                if len(products) != len(product_ids):
                    raise HTTPException(status_code=422, detail="One or more products do not exist")
                product_by_id = {product.id: product for product in products}
                inventory_ids = sorted({product.inventory_item_id for product in products})
                inventory_rows = db.scalars(
                    select(InventoryItem)
                    .where(InventoryItem.id.in_(inventory_ids))
                    .order_by(InventoryItem.id)
                    .with_for_update()
                ).all()
                item_by_id = {item.id: item for item in inventory_rows}
                unit_ids = sorted({item.base_unit_id for item in inventory_rows})
                units = db.scalars(select(Unit).where(Unit.id.in_(unit_ids)).order_by(Unit.id)).all()
                unit_by_id = {unit.id: unit for unit in units}

                with localcontext() as context:
                    context.prec = 28
                    order_lines = []
                    for requested in payload.lines:
                        product = product_by_id[requested.product_id]
                        item = item_by_id.get(product.inventory_item_id)
                        if not product.is_active or item is None or not item.is_active or item.category != "FINISHED_GOOD":
                            raise HTTPException(status_code=422, detail=f"Product {product.id} is inactive or not saleable")
                        unit = unit_by_id.get(item.base_unit_id)
                        if unit is None or not unit.is_active:
                            raise HTTPException(status_code=422, detail=f"Product {product.id} has no active base unit")
                        quantity = requested.quantity
                        quantum = Decimal("1").scaleb(-unit.input_decimal_places)
                        if quantity != quantity.quantize(quantum, rounding=ROUND_HALF_UP):
                            raise HTTPException(
                                status_code=422,
                                detail=f"Quantity for {product.sku} exceeds {unit.input_decimal_places}-decimal input precision",
                            )
                        quantity = quantity.quantize(QUANTITY_SCALE, rounding=ROUND_HALF_UP)
                        if quantity <= 0:
                            raise HTTPException(status_code=422, detail=f"Quantity for {product.sku} is below supported precision")
                        unit_price = Decimal(product.default_selling_price)
                        taxable_value = (quantity * unit_price).quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)
                        order_lines.append(SalesOrderLine(
                            product_id=product.id,
                            sku_snapshot=product.sku,
                            product_name_snapshot=product.name,
                            hsn_snapshot=product.hsn_code,
                            submitted_quantity=quantity,
                            submitted_unit_price=unit_price,
                            quantity=quantity,
                            unit_price=unit_price,
                            line_taxable_value=taxable_value,
                        ))

                now = datetime.now(UTC)
                order = SalesOrder(
                    order_number="PENDING",
                    customer_id=customer.id,
                    salesman_user_id=actor_id,
                    status="SUBMITTED",
                    submitted_at=now,
                    lines=order_lines,
                )
                db.add(order)
                db.flush()
                order.order_number = f"SO-{now:%Y%m%d}-{order.id:08d}"
                db.add(AuditEvent(
                    actor_user_id=actor_id,
                    action="SALES_ORDER_SUBMITTED",
                    entity_type="SALES_ORDER",
                    entity_id=order.id,
                    after_data={
                        "order_number": order.order_number,
                        "customer_id": customer.id,
                        "salesman_user_id": actor_id,
                        "status": "SUBMITTED",
                        "line_count": len(order_lines),
                        "lines": [
                            {
                                "product_id": line.product_id,
                                "quantity": str(line.submitted_quantity),
                                "unit_price": str(line.submitted_unit_price),
                                "line_taxable_value": str(line.line_taxable_value),
                            }
                            for line in order_lines
                        ],
                    },
                ))
                idem.response_status = 201
                idem.response_body = {"order_id": order.id}
                idem.completed_at = now
                target_order_id = order.id
                db.flush()
        return _load_order(db, target_order_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Sales order conflicts with an existing record") from exc
