import hashlib
from datetime import UTC, datetime
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import InventoryItem, InventoryLocation
from app.models.inventory import (
    AuditEvent,
    IdempotencyRecord,
    InventoryBalance,
    InventoryValuation,
    StockAdjustment,
    StockAdjustmentLine,
    StockMovement,
)


QTY_SCALE = Decimal("0.000001")
COST_SCALE = Decimal("0.000001")
MONEY_SCALE = Decimal("0.01")
ZERO = Decimal("0")


def _quantize(value: Decimal, scale: Decimal) -> Decimal:
    return value.quantize(scale, rounding=ROUND_HALF_UP)


def _decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


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
                        movement_unit_cost = _quantize(_decimal(line.unit_cost), COST_SCALE)
                        extended_cost = _quantize(delta * movement_unit_cost, MONEY_SCALE)
                        new_qty = valued_qty + delta
                        new_value = inventory_value + extended_cost
                    else:
                        issue_qty = -delta
                        if issue_qty > valued_qty:
                            raise HTTPException(
                                status_code=409,
                                detail=f"Insufficient stock for item {line.inventory_item_id}",
                            )
                        movement_unit_cost = (
                            _quantize(inventory_value / valued_qty, COST_SCALE)
                            if valued_qty > ZERO
                            else ZERO
                        )
                        if issue_qty == valued_qty:
                            extended_cost = inventory_value
                            new_qty = ZERO
                            new_value = ZERO
                        else:
                            with localcontext(Context(prec=28, rounding=ROUND_HALF_UP)):
                                extended_cost = _quantize(
                                    issue_qty * (inventory_value / valued_qty), MONEY_SCALE
                                )
                            new_qty = valued_qty - issue_qty
                            new_value = inventory_value - extended_cost
                    new_average = (
                        _quantize(new_value / new_qty, COST_SCALE) if new_qty > ZERO else ZERO
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
