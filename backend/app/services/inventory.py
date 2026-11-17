import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.costing import (
    COST_SCALE,
    MONEY_SCALE,
    QTY_SCALE,
    ZERO,
    as_decimal as _decimal,
    issue_valuation,
    quantize as _quantize,
    receive_valuation,
)
from app.models import InventoryItem, InventoryLocation, Supplier
from app.models.inventory import (
    AuditEvent,
    IdempotencyRecord,
    InventoryBalance,
    InventoryValuation,
    PurchaseReceipt,
    PurchaseReceiptLine,
    StockAdjustment,
    StockAdjustmentLine,
    StockMovement,
)


def create_stock_adjustment(db: Session, payload, actor_user_id: int) -> StockAdjustment:
    db.rollback()
    try:
        with db.begin():
            if len({(line.inventory_item_id, line.inventory_location_id) for line in payload.lines}) != len(payload.lines):
                raise HTTPException(status_code=422, detail="Duplicate item/location in adjustment")
            if payload.reason == "OPENING_BALANCE" and any(line.quantity_delta <= 0 for line in payload.lines):
                raise HTTPException(status_code=422, detail="Opening balances must have positive quantities")
            for line in payload.lines:
                if line.quantity_delta == 0:
                    raise HTTPException(status_code=422, detail="Adjustment quantity cannot be zero")
                item = db.get(InventoryItem, line.inventory_item_id)
                location = db.get(InventoryLocation, line.inventory_location_id)
                if item is None or not item.is_active:
                    raise HTTPException(status_code=422, detail="Inventory item does not exist or is inactive")
                if location is None or not location.is_active:
                    raise HTTPException(status_code=422, detail="Inventory location does not exist or is inactive")
                if line.quantity_delta > 0 and line.unit_cost is None:
                    raise HTTPException(status_code=422, detail="Positive adjustments require a unit cost")
                if line.quantity_delta < 0 and line.unit_cost is not None:
                    raise HTTPException(status_code=422, detail="Negative adjustments use the current moving average cost")
            adjustment = StockAdjustment(
                adjustment_number=payload.adjustment_number,
                reason=payload.reason,
                note=payload.note,
                status="DRAFT",
                created_by_user_id=actor_user_id,
            )
            db.add(adjustment)
            db.flush()
            for line in payload.lines:
                db.add(
                    StockAdjustmentLine(
                        stock_adjustment_id=adjustment.id,
                        inventory_item_id=line.inventory_item_id,
                        inventory_location_id=line.inventory_location_id,
                        quantity_delta=_quantize(_decimal(line.quantity_delta), QTY_SCALE),
                        unit_cost=(
                            _quantize(_decimal(line.unit_cost), COST_SCALE)
                            if line.unit_cost is not None
                            else None
                        ),
                        note=line.note,
                    )
                )
            db.add(
                AuditEvent(
                    actor_user_id=actor_user_id,
                    action="STOCK_ADJUSTMENT_CREATED",
                    entity_type="stock_adjustment",
                    entity_id=adjustment.id,
                    after_data={
                        "adjustment_number": adjustment.adjustment_number,
                        "reason": adjustment.reason,
                        "line_count": len(payload.lines),
                        "status": "DRAFT",
                    },
                )
            )
            db.flush()
        return adjustment
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adjustment number or item/location line already exists",
        ) from exc


def post_stock_adjustment(
    db: Session, adjustment_id: int, actor_user_id: int, idempotency_key: str
) -> dict:
    operation = "inventory.adjustment.post"
    request_hash = hashlib.sha256(f"{operation}:{adjustment_id}".encode()).hexdigest()
    db.rollback()
    try:
        with db.begin():
            db.execute(
                pg_insert(IdempotencyRecord)
                .values(
                    actor_user_id=actor_user_id,
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
                    IdempotencyRecord.actor_user_id == actor_user_id,
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
                return_body = dict(idem.response_body)
            else:
                adjustment = db.scalar(
                    select(StockAdjustment)
                    .where(StockAdjustment.id == adjustment_id)
                    .with_for_update()
                )
                if adjustment is None:
                    raise HTTPException(status_code=404, detail="Stock adjustment not found")
                if adjustment.status != "DRAFT":
                    raise HTTPException(status_code=409, detail="Only DRAFT adjustments can be posted")
                lines = db.scalars(
                    select(StockAdjustmentLine)
                    .where(StockAdjustmentLine.stock_adjustment_id == adjustment_id)
                    .order_by(
                        StockAdjustmentLine.inventory_item_id,
                        StockAdjustmentLine.inventory_location_id,
                        StockAdjustmentLine.id,
                    )
                ).all()
                if not lines:
                    raise HTTPException(status_code=422, detail="Cannot post an empty stock adjustment")

                keys = sorted({(line.inventory_item_id, line.inventory_location_id) for line in lines})
                for item_id, location_id in keys:
                    db.execute(
                        pg_insert(InventoryBalance)
                        .values(inventory_item_id=item_id, inventory_location_id=location_id, on_hand_qty=ZERO)
                        .on_conflict_do_nothing(
                            index_elements=[
                                InventoryBalance.inventory_item_id,
                                InventoryBalance.inventory_location_id,
                            ]
                        )
                    )
                for item_id, location_id in keys:
                    db.execute(
                        pg_insert(InventoryValuation)
                        .values(
                            inventory_item_id=item_id,
                            inventory_location_id=location_id,
                            valued_qty=ZERO,
                            inventory_value=ZERO,
                            average_unit_cost=ZERO,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                InventoryValuation.inventory_item_id,
                                InventoryValuation.inventory_location_id,
                            ]
                        )
                    )

                balances = {}
                valuations = {}
                for item_id, location_id in keys:
                    balances[(item_id, location_id)] = db.scalar(
                        select(InventoryBalance)
                        .where(
                            InventoryBalance.inventory_item_id == item_id,
                            InventoryBalance.inventory_location_id == location_id,
                        )
                        .with_for_update()
                    )
                for item_id, location_id in keys:
                    valuations[(item_id, location_id)] = db.scalar(
                        select(InventoryValuation)
                        .where(
                            InventoryValuation.inventory_item_id == item_id,
                            InventoryValuation.inventory_location_id == location_id,
                        )
                        .with_for_update()
                    )

                now = datetime.now(UTC)
                movement_count = 0
                for line in lines:
                    key = (line.inventory_item_id, line.inventory_location_id)
                    balance = balances[key]
                    valuation = valuations[key]
                    on_hand = _decimal(balance.on_hand_qty)
                    valued_qty = _decimal(valuation.valued_qty)
                    inventory_value = _decimal(valuation.inventory_value)
                    if on_hand != valued_qty:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Inventory projection mismatch for item {line.inventory_item_id}",
                        )
                    delta = _decimal(line.quantity_delta)
                    if delta > 0:
                        if line.unit_cost is None:
                            raise HTTPException(status_code=422, detail="Positive adjustments require unit cost")
                        movement_unit_cost, extended_cost, new_qty, new_value, new_average = receive_valuation(
                            delta, _decimal(line.unit_cost), valued_qty, inventory_value
                        )
                    else:
                        issue_qty = -delta
                        if issue_qty > valued_qty:
                            raise HTTPException(
                                status_code=409,
                                detail=f"Insufficient stock for item {line.inventory_item_id}",
                            )
                        movement_unit_cost, extended_cost, new_qty, new_value, new_average = issue_valuation(
                            issue_qty, valued_qty, inventory_value
                        )
                    balance.on_hand_qty = _quantize(on_hand + delta, QTY_SCALE)
                    balance.updated_at = now
                    valuation.valued_qty = _quantize(new_qty, QTY_SCALE)
                    valuation.inventory_value = _quantize(new_value, MONEY_SCALE)
                    valuation.average_unit_cost = new_average
                    valuation.updated_at = now
                    db.add(
                        StockMovement(
                            inventory_item_id=line.inventory_item_id,
                            inventory_location_id=line.inventory_location_id,
                            movement_type=(
                                "OPENING" if adjustment.reason == "OPENING_BALANCE" else "ADJUSTMENT"
                            ),
                            quantity_delta=delta,
                            unit_cost=movement_unit_cost,
                            extended_cost=extended_cost,
                            stock_adjustment_line_id=line.id,
                            posted_at=now,
                            posted_by_user_id=actor_user_id,
                        )
                    )
                    movement_count += 1

                adjustment.status = "POSTED"
                adjustment.posted_at = now
                adjustment.posted_by_user_id = actor_user_id
                db.add(
                    AuditEvent(
                        actor_user_id=actor_user_id,
                        action="STOCK_ADJUSTMENT_POSTED",
                        entity_type="stock_adjustment",
                        entity_id=adjustment.id,
                        after_data={
                            "adjustment_number": adjustment.adjustment_number,
                            "reason": adjustment.reason,
                            "movement_count": movement_count,
                            "status": "POSTED",
                        },
                    )
                )
                return_body = {
                    "adjustment_id": adjustment.id,
                    "status": "POSTED",
                    "movement_count": movement_count,
                }
                idem.response_status = 200
                idem.response_body = return_body
                idem.completed_at = now
                db.flush()
        return return_body
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Stock adjustment conflicts with an existing posting") from exc


def list_inventory_balances(db: Session) -> list[dict]:
    rows = db.execute(
        select(InventoryBalance, InventoryValuation)
        .join(
            InventoryValuation,
            (InventoryValuation.inventory_item_id == InventoryBalance.inventory_item_id)
            & (InventoryValuation.inventory_location_id == InventoryBalance.inventory_location_id),
        )
        .order_by(InventoryBalance.inventory_item_id, InventoryBalance.inventory_location_id)
        .limit(1000)
    ).all()
    return [
        {
            "inventory_item_id": balance.inventory_item_id,
            "inventory_location_id": balance.inventory_location_id,
            "on_hand_qty": balance.on_hand_qty,
            "valued_qty": valuation.valued_qty,
            "inventory_value": valuation.inventory_value,
            "average_unit_cost": valuation.average_unit_cost,
        }
        for balance, valuation in rows
    ]


def list_stock_movements(db: Session) -> list[StockMovement]:
    return db.scalars(
        select(StockMovement)
        .order_by(StockMovement.posted_at.desc(), StockMovement.id.desc())
        .limit(1000)
    ).all()



def create_purchase_receipt(db: Session, payload, actor_user_id: int) -> PurchaseReceipt:
    db.rollback()
    try:
        with db.begin():
            supplier = db.get(Supplier, payload.supplier_id)
            if supplier is None or not supplier.is_active:
                raise HTTPException(status_code=422, detail="Supplier does not exist or is inactive")
            if len({(line.inventory_item_id, line.inventory_location_id) for line in payload.lines}) != len(payload.lines):
                raise HTTPException(status_code=422, detail="Duplicate item/location in purchase receipt")
            for line in payload.lines:
                item = db.get(InventoryItem, line.inventory_item_id)
                location = db.get(InventoryLocation, line.inventory_location_id)
                if item is None or not item.is_active:
                    raise HTTPException(status_code=422, detail="Inventory item does not exist or is inactive")
                if location is None or not location.is_active:
                    raise HTTPException(status_code=422, detail="Inventory location does not exist or is inactive")
                quantity = _quantize(_decimal(line.quantity_received), QTY_SCALE)
                cost = _quantize(_decimal(line.unit_cost), COST_SCALE)
                if quantity <= ZERO:
                    raise HTTPException(status_code=422, detail="Received quantity must be positive")
                if cost < ZERO:
                    raise HTTPException(status_code=422, detail="Unit cost cannot be negative")
            receipt = PurchaseReceipt(
                receipt_number=payload.receipt_number,
                supplier_id=payload.supplier_id,
                supplier_invoice_number=payload.supplier_invoice_number,
                received_at=payload.received_at,
                note=payload.note,
                status="DRAFT",
                created_by_user_id=actor_user_id,
            )
            db.add(receipt)
            db.flush()
            for line in payload.lines:
                db.add(
                    PurchaseReceiptLine(
                        purchase_receipt_id=receipt.id,
                        inventory_item_id=line.inventory_item_id,
                        inventory_location_id=line.inventory_location_id,
                        quantity_received=_quantize(_decimal(line.quantity_received), QTY_SCALE),
                        unit_cost=_quantize(_decimal(line.unit_cost), COST_SCALE),
                        note=line.note,
                    )
                )
            db.add(
                AuditEvent(
                    actor_user_id=actor_user_id,
                    action="PURCHASE_RECEIPT_CREATED",
                    entity_type="purchase_receipt",
                    entity_id=receipt.id,
                    after_data={
                        "receipt_number": receipt.receipt_number,
                        "supplier_id": receipt.supplier_id,
                        "line_count": len(payload.lines),
                        "status": "DRAFT",
                    },
                )
            )
            db.flush()
        return receipt
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Receipt number, supplier invoice number, or item/location line already exists",
        ) from exc


def post_purchase_receipt(
    db: Session, receipt_id: int, actor_user_id: int, idempotency_key: str
) -> dict:
    operation = "inventory.purchase_receipt.post"
    request_hash = hashlib.sha256(f"{operation}:{receipt_id}".encode()).hexdigest()
    db.rollback()
    try:
        with db.begin():
            db.execute(
                pg_insert(IdempotencyRecord)
                .values(
                    actor_user_id=actor_user_id,
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
                    IdempotencyRecord.actor_user_id == actor_user_id,
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
                return_body = dict(idem.response_body)
            else:
                receipt = db.scalar(
                    select(PurchaseReceipt)
                    .where(PurchaseReceipt.id == receipt_id)
                    .with_for_update()
                )
                if receipt is None:
                    raise HTTPException(status_code=404, detail="Purchase receipt not found")
                if receipt.status != "DRAFT":
                    raise HTTPException(status_code=409, detail="Only DRAFT receipts can be posted")
                supplier = db.get(Supplier, receipt.supplier_id)
                if supplier is None or not supplier.is_active:
                    raise HTTPException(status_code=409, detail="Supplier is inactive; receipt cannot be posted")
                lines = db.scalars(
                    select(PurchaseReceiptLine)
                    .where(PurchaseReceiptLine.purchase_receipt_id == receipt_id)
                    .order_by(
                        PurchaseReceiptLine.inventory_item_id,
                        PurchaseReceiptLine.inventory_location_id,
                        PurchaseReceiptLine.id,
                    )
                ).all()
                if not lines:
                    raise HTTPException(status_code=422, detail="Cannot post an empty purchase receipt")
                keys = sorted({(line.inventory_item_id, line.inventory_location_id) for line in lines})
                for item_id, location_id in keys:
                    item = db.get(InventoryItem, item_id)
                    location = db.get(InventoryLocation, location_id)
                    if item is None or not item.is_active or location is None or not location.is_active:
                        raise HTTPException(status_code=409, detail="Receipt contains an inactive item or location")
                    db.execute(
                        pg_insert(InventoryBalance)
                        .values(inventory_item_id=item_id, inventory_location_id=location_id, on_hand_qty=ZERO)
                        .on_conflict_do_nothing(
                            index_elements=[
                                InventoryBalance.inventory_item_id,
                                InventoryBalance.inventory_location_id,
                            ]
                        )
                    )
                    db.execute(
                        pg_insert(InventoryValuation)
                        .values(
                            inventory_item_id=item_id,
                            inventory_location_id=location_id,
                            valued_qty=ZERO,
                            inventory_value=ZERO,
                            average_unit_cost=ZERO,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                InventoryValuation.inventory_item_id,
                                InventoryValuation.inventory_location_id,
                            ]
                        )
                    )
                balances = {}
                valuations = {}
                for item_id, location_id in keys:
                    balances[(item_id, location_id)] = db.scalar(
                        select(InventoryBalance)
                        .where(
                            InventoryBalance.inventory_item_id == item_id,
                            InventoryBalance.inventory_location_id == location_id,
                        )
                        .with_for_update()
                    )
                    valuations[(item_id, location_id)] = db.scalar(
                        select(InventoryValuation)
                        .where(
                            InventoryValuation.inventory_item_id == item_id,
                            InventoryValuation.inventory_location_id == location_id,
                        )
                        .with_for_update()
                    )
                now = datetime.now(UTC)
                total_cost = ZERO
                for line in lines:
                    key = (line.inventory_item_id, line.inventory_location_id)
                    balance = balances[key]
                    valuation = valuations[key]
                    on_hand = _decimal(balance.on_hand_qty)
                    valued_qty = _decimal(valuation.valued_qty)
                    inventory_value = _decimal(valuation.inventory_value)
                    if on_hand != valued_qty:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Inventory quantity projection mismatch for item {line.inventory_item_id}",
                        )
                    quantity = _quantize(_decimal(line.quantity_received), QTY_SCALE)
                    unit_cost, extended_cost, new_qty, new_value, average_cost = receive_valuation(
                        quantity, _decimal(line.unit_cost), valued_qty, inventory_value
                    )
                    balance.on_hand_qty = _quantize(on_hand + quantity, QTY_SCALE)
                    balance.updated_at = now
                    valuation.valued_qty = _quantize(new_qty, QTY_SCALE)
                    valuation.inventory_value = _quantize(new_value, MONEY_SCALE)
                    valuation.average_unit_cost = average_cost
                    valuation.updated_at = now
                    db.add(
                        StockMovement(
                            inventory_item_id=line.inventory_item_id,
                            inventory_location_id=line.inventory_location_id,
                            movement_type="RECEIPT",
                            quantity_delta=quantity,
                            unit_cost=unit_cost,
                            extended_cost=extended_cost,
                            purchase_receipt_line_id=line.id,
                            posted_at=now,
                            posted_by_user_id=actor_user_id,
                        )
                    )
                    total_cost += extended_cost
                receipt.status = "POSTED"
                receipt.posted_at = now
                receipt.posted_by_user_id = actor_user_id
                db.add(
                    AuditEvent(
                        actor_user_id=actor_user_id,
                        action="PURCHASE_RECEIPT_POSTED",
                        entity_type="purchase_receipt",
                        entity_id=receipt.id,
                        after_data={
                            "receipt_number": receipt.receipt_number,
                            "supplier_id": receipt.supplier_id,
                            "movement_count": len(lines),
                            "total_receipt_cost": str(_quantize(total_cost, MONEY_SCALE)),
                            "status": "POSTED",
                        },
                    )
                )
                return_body = {
                    "receipt_id": receipt.id,
                    "status": "POSTED",
                    "movement_count": len(lines),
                    "total_receipt_cost": _quantize(total_cost, MONEY_SCALE),
                }
                idem.response_status = 200
                idem.response_body = {
                    **return_body,
                    "total_receipt_cost": str(return_body["total_receipt_cost"]),
                }
                idem.completed_at = now
                db.flush()
        if isinstance(return_body.get("total_receipt_cost"), str):
            return_body["total_receipt_cost"] = Decimal(return_body["total_receipt_cost"])
        return return_body
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Purchase receipt conflicts with an existing posting") from exc


def reconcile_inventory(db: Session) -> dict:
    movements = db.scalars(
        select(StockMovement).order_by(
            StockMovement.inventory_item_id,
            StockMovement.inventory_location_id,
            StockMovement.posted_at,
            StockMovement.id,
        )
    ).all()
    replay: dict[tuple[int, int], dict[str, Decimal]] = {}
    for movement in movements:
        key = (movement.inventory_item_id, movement.inventory_location_id)
        state = replay.setdefault(key, {"quantity": ZERO, "value": ZERO})
        quantity_delta = _decimal(movement.quantity_delta)
        if movement.extended_cost is None:
            state["value"] = Decimal("-1")
        elif quantity_delta > ZERO:
            state["value"] += _decimal(movement.extended_cost)
        else:
            state["value"] -= _decimal(movement.extended_cost)
        state["quantity"] += quantity_delta

    balance_rows = db.scalars(select(InventoryBalance)).all()
    valuation_rows = db.scalars(select(InventoryValuation)).all()
    balances = {(row.inventory_item_id, row.inventory_location_id): _decimal(row.on_hand_qty) for row in balance_rows}
    valuations = {
        (row.inventory_item_id, row.inventory_location_id): row for row in valuation_rows
    }
    keys = sorted(set(replay) | set(balances) | set(valuations))
    mismatches = []
    for item_id, location_id in keys:
        state = replay.get((item_id, location_id), {"quantity": ZERO, "value": ZERO})
        balance_qty = balances.get((item_id, location_id), ZERO)
        valuation = valuations.get((item_id, location_id))
        valuation_qty = _decimal(valuation.valued_qty) if valuation else ZERO
        projected_value = _decimal(valuation.inventory_value) if valuation else ZERO
        ledger_value = state["value"]
        ledger_qty = state["quantity"]
        ledger_average = (
            _quantize(ledger_value / ledger_qty, COST_SCALE)
            if ledger_qty > ZERO and ledger_value >= ZERO
            else ZERO
        )
        projected_average = _decimal(valuation.average_unit_cost) if valuation else ZERO
        consistent = (
            ledger_qty == balance_qty == valuation_qty
            and ledger_value == projected_value
            and ledger_average == projected_average
            and state["value"] >= ZERO
        )
        if not consistent:
            mismatches.append(
                {
                    "inventory_item_id": item_id,
                    "inventory_location_id": location_id,
                    "ledger_quantity": ledger_qty,
                    "balance_quantity": balance_qty,
                    "valuation_quantity": valuation_qty,
                    "ledger_value": ledger_value,
                    "projected_value": projected_value,
                    "ledger_average_unit_cost": ledger_average,
                    "projected_average_unit_cost": projected_average,
                    "is_consistent": False,
                }
            )
    return {
        "is_reconciled": not mismatches,
        "checked_item_locations": len(keys),
        "mismatches": mismatches,
    }
