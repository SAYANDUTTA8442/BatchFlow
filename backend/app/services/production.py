import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.domain.costing import (
    COST_SCALE,
    MONEY_SCALE,
    QTY_SCALE,
    ZERO,
    as_decimal,
    issue_valuation,
    quantize,
    receive_output_valuation,
)
from app.models import (
    AuditEvent,
    IdempotencyRecord,
    InventoryBalance,
    InventoryItem,
    InventoryLocation,
    InventoryValuation,
    Product,
    ProductionCostLine,
    ProductionRun,
    ProductionRunLine,
    ProductionRunOutput,
    StockMovement,
    Unit,
)
from app.models.bom import Bom, BomLine


PERCENT_SCALE = Decimal("0.0001")


def _load_run(db: Session, run_id: int) -> ProductionRun:
    run = db.scalar(
        select(ProductionRun)
        .options(
            selectinload(ProductionRun.lines),
            selectinload(ProductionRun.outputs),
            selectinload(ProductionRun.cost_lines),
        )
        .where(ProductionRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Production run not found")
    return run


def list_production_runs(
    db: Session, production_date: date | None = None, status_filter: str | None = None
) -> list[ProductionRun]:
    query = (
        select(ProductionRun)
        .options(
            selectinload(ProductionRun.lines),
            selectinload(ProductionRun.outputs),
            selectinload(ProductionRun.cost_lines),
        )
        .order_by(ProductionRun.production_date.desc(), ProductionRun.id.desc())
    )
    if production_date is not None:
        query = query.where(ProductionRun.production_date == production_date)
    if status_filter is not None:
        query = query.where(ProductionRun.status == status_filter)
    return list(db.scalars(query.limit(500)).unique().all())


def get_production_run(db: Session, run_id: int) -> ProductionRun:
    return _load_run(db, run_id)


def create_production_run(db: Session, payload, actor_id: int) -> ProductionRun:
    db.rollback()
    with db.begin():
        bom = db.scalar(
            select(Bom)
            .options(selectinload(Bom.lines))
            .where(Bom.id == payload.bom_id)
            .with_for_update()
        )
        if bom is None:
            raise HTTPException(status_code=404, detail="BOM not found")
        if bom.status not in {"ACTIVE", "RETIRED"}:
            raise HTTPException(status_code=409, detail="Production requires an activated BOM version")
        if payload.production_date < bom.effective_from or (
            bom.effective_to is not None and payload.production_date > bom.effective_to
        ):
            raise HTTPException(status_code=409, detail="BOM is not effective on the production date")

        product = db.scalar(select(Product).where(Product.id == bom.product_id).with_for_update())
        if product is None or not product.is_active:
            raise HTTPException(status_code=409, detail="BOM product is inactive or unavailable")
        finished_item = db.scalar(
            select(InventoryItem).where(InventoryItem.id == product.inventory_item_id).with_for_update()
        )
        if finished_item is None or not finished_item.is_active or finished_item.category != "FINISHED_GOOD":
            raise HTTPException(status_code=409, detail="Finished-good inventory item is inactive or invalid")
        finished_unit_code = db.scalar(select(Unit.code).where(Unit.id == finished_item.base_unit_id))
        if finished_unit_code is None:
            raise HTTPException(status_code=409, detail="Finished-good base unit is unavailable")

        item_ids = [line.inventory_item_id for line in bom.lines]
        item_rows = db.execute(
            select(InventoryItem, Unit.code)
            .join(Unit, Unit.id == InventoryItem.base_unit_id)
            .where(InventoryItem.id.in_(item_ids))
            .order_by(InventoryItem.id)
            .with_for_update(of=InventoryItem)
        ).all()
        items = {item.id: (item, unit_code) for item, unit_code in item_rows}
        if len(items) != len(item_ids):
            raise HTTPException(status_code=409, detail="A BOM component is no longer available")
        for line in bom.lines:
            item, _ = items[line.inventory_item_id]
            expected_category = "RAW_MATERIAL" if line.line_type == "RAW_MATERIAL" else "PACKAGING"
            if not item.is_active or item.category != expected_category:
                raise HTTPException(
                    status_code=409,
                    detail=f"BOM component {item.code} is inactive or no longer matches its line type",
                )

        with localcontext() as context:
            context.prec = 28
            multiplier = quantize(as_decimal(payload.batch_multiplier), QTY_SCALE)
            if multiplier <= 0:
                raise HTTPException(status_code=422, detail="Batch multiplier is below supported precision")
            expected_output = quantize(as_decimal(bom.expected_output_qty) * multiplier, QTY_SCALE)
            if expected_output <= 0:
                raise HTTPException(status_code=422, detail="Scaled expected output must be positive")
            run_lines = []
            for line in bom.lines:
                planned_qty = quantize(as_decimal(line.quantity_per_batch) * multiplier, QTY_SCALE)
                if planned_qty <= 0:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Scaled quantity for inventory item {line.inventory_item_id} is below supported precision",
                    )
                item, unit_code = items[line.inventory_item_id]
                run_lines.append(ProductionRunLine(
                    inventory_item_id=item.id,
                    line_type=line.line_type,
                    item_code_snapshot=item.code,
                    item_name_snapshot=item.name,
                    base_unit_code_snapshot=unit_code,
                    quantity_per_batch_snapshot=as_decimal(line.quantity_per_batch),
                    planned_qty=planned_qty,
                ))

            tolerance = quantize(
                as_decimal(get_settings().production_variance_tolerance_percent), PERCENT_SCALE
            )
            run = ProductionRun(
                run_number="PENDING",
                product_id=product.id,
                finished_inventory_item_id=finished_item.id,
                product_sku_snapshot=product.sku,
                product_name_snapshot=product.name,
                finished_item_code_snapshot=finished_item.code,
                finished_item_name_snapshot=finished_item.name,
                output_unit_code_snapshot=finished_unit_code,
                bom_id=bom.id,
                bom_version_snapshot=bom.version,
                batch_multiplier=multiplier,
                expected_output_qty=expected_output,
                variance_tolerance_percent=tolerance,
                status="DRAFT",
                production_date=payload.production_date,
                supervisor_user_id=actor_id,
                lines=run_lines,
            )
            db.add(run)
            db.flush()
            run.run_number = f"PR-{payload.production_date:%Y%m%d}-{run.id:08d}"
            db.add(AuditEvent(
                actor_user_id=actor_id,
                action="PRODUCTION_RUN_DRAFT_CREATED",
                entity_type="PRODUCTION_RUN",
                entity_id=run.id,
                after_data={
                    "run_number": run.run_number,
                    "product_id": product.id,
                    "finished_inventory_item_id": finished_item.id,
                    "bom_id": bom.id,
                    "bom_version": bom.version,
                    "batch_multiplier": str(run.batch_multiplier),
                    "expected_output_qty": str(run.expected_output_qty),
                    "variance_tolerance_percent": str(tolerance),
                    "line_count": len(run.lines),
                },
            ))
            run_id = run.id
    return _load_run(db, run_id)


def _validate_input_precision(quantity: Decimal, decimal_places: int, label: str) -> Decimal:
    if quantity < ZERO:
        raise HTTPException(status_code=422, detail=f"{label} cannot be negative")
    quantum = Decimal("1").scaleb(-decimal_places)
    if quantity != quantity.quantize(quantum, rounding=ROUND_HALF_UP):
        raise HTTPException(
            status_code=422,
            detail=f"{label} exceeds the base unit's {decimal_places}-decimal input precision",
        )
    normalized = quantize(quantity, QTY_SCALE)
    if normalized != quantity:
        raise HTTPException(status_code=422, detail=f"{label} exceeds six-place quantity precision")
    return normalized


def post_production_run(db: Session, run_id: int, actor_id: int, idempotency_key: str, payload) -> ProductionRun:
    operation = "production.run.post"
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(f"{operation}:{run_id}:{canonical}".encode()).hexdigest()
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
                target_run_id = int(idem.response_body["run_id"])
            else:
                run = db.scalar(
                    select(ProductionRun).where(ProductionRun.id == run_id).with_for_update()
                )
                if run is None:
                    raise HTTPException(status_code=404, detail="Production run not found")
                if run.status != "DRAFT":
                    raise HTTPException(status_code=409, detail="Only DRAFT production runs can be posted")

                bom = db.scalar(select(Bom).where(Bom.id == run.bom_id).with_for_update())
                if (
                    bom is None
                    or bom.product_id != run.product_id
                    or bom.version != run.bom_version_snapshot
                    or bom.status not in {"ACTIVE", "RETIRED"}
                    or run.production_date < bom.effective_from
                    or (bom.effective_to is not None and run.production_date > bom.effective_to)
                ):
                    raise HTTPException(status_code=409, detail="The run's BOM version is no longer valid for its production date")

                product = db.scalar(select(Product).where(Product.id == run.product_id).with_for_update())
                if (
                    product is None
                    or not product.is_active
                    or product.inventory_item_id != run.finished_inventory_item_id
                ):
                    raise HTTPException(status_code=409, detail="The planned product or finished-good mapping is no longer valid")

                run_lines = db.scalars(
                    select(ProductionRunLine)
                    .where(ProductionRunLine.production_run_id == run.id)
                    .order_by(ProductionRunLine.inventory_item_id, ProductionRunLine.id)
                    .with_for_update()
                ).all()
                bom_lines = db.scalars(
                    select(BomLine)
                    .where(BomLine.bom_id == bom.id)
                    .order_by(BomLine.inventory_item_id)
                ).all()
                if not run_lines or {x.inventory_item_id for x in run_lines} != {
                    x.inventory_item_id for x in bom_lines
                }:
                    raise HTTPException(status_code=409, detail="Production plan does not match its BOM snapshot")
                bom_line_map = {x.inventory_item_id: x for x in bom_lines}
                for line in run_lines:
                    source_line = bom_line_map[line.inventory_item_id]
                    expected_planned = quantize(
                        as_decimal(source_line.quantity_per_batch) * as_decimal(run.batch_multiplier),
                        QTY_SCALE,
                    )
                    if (
                        source_line.line_type != line.line_type
                        or as_decimal(source_line.quantity_per_batch) != as_decimal(line.quantity_per_batch_snapshot)
                        or expected_planned != as_decimal(line.planned_qty)
                    ):
                        raise HTTPException(status_code=409, detail="Stored production plan does not match its BOM snapshot")

                actual_by_line = {entry.line_id: entry for entry in payload.actual_lines}
                if len(actual_by_line) != len(payload.actual_lines) or set(actual_by_line) != {
                    line.id for line in run_lines
                }:
                    raise HTTPException(status_code=422, detail="Supply exactly one actual quantity for every planned BOM line")

                item_ids = sorted({line.inventory_item_id for line in run_lines} | {run.finished_inventory_item_id})
                item_rows = db.execute(
                    select(InventoryItem, Unit.code, Unit.input_decimal_places)
                    .join(Unit, Unit.id == InventoryItem.base_unit_id)
                    .where(InventoryItem.id.in_(item_ids))
                    .order_by(InventoryItem.id)
                    .with_for_update(of=InventoryItem)
                ).all()
                items = {item.id: (item, unit_code, places) for item, unit_code, places in item_rows}
                if len(items) != len(item_ids):
                    raise HTTPException(status_code=409, detail="A production inventory item or unit is unavailable")
                for line in run_lines:
                    item, unit_code, _ = items[line.inventory_item_id]
                    expected_category = "RAW_MATERIAL" if line.line_type == "RAW_MATERIAL" else "PACKAGING"
                    if (
                        not item.is_active
                        or item.category != expected_category
                        or unit_code != line.base_unit_code_snapshot
                    ):
                        raise HTTPException(
                            status_code=409,
                            detail=f"Component {line.item_code_snapshot} is inactive or its base unit changed",
                        )
                finished_item, finished_unit_code, finished_places = items[run.finished_inventory_item_id]
                if (
                    not finished_item.is_active
                    or finished_item.category != "FINISHED_GOOD"
                    or finished_unit_code != run.output_unit_code_snapshot
                ):
                    raise HTTPException(status_code=409, detail="Finished-good item is inactive or its base unit changed")

                location = db.scalar(
                    select(InventoryLocation)
                    .where(InventoryLocation.code == "FACTORY-01")
                    .with_for_update()
                )
                if location is None or not location.is_active:
                    raise HTTPException(status_code=409, detail="The factory inventory location is unavailable")

                actuals: dict[int, tuple[Decimal, Decimal]] = {}
                for line in run_lines:
                    request_line = actual_by_line[line.id]
                    item, _, places = items[line.inventory_item_id]
                    actual_qty = _validate_input_precision(
                        as_decimal(request_line.actual_qty), places, f"Actual quantity for {line.item_code_snapshot}"
                    )
                    damaged_qty = _validate_input_precision(
                        as_decimal(request_line.damaged_qty), places, f"Damaged quantity for {line.item_code_snapshot}"
                    )
                    if damaged_qty > actual_qty:
                        raise HTTPException(status_code=422, detail="Damaged quantity cannot exceed actual packaging consumption")
                    if line.line_type != "PACKAGING" and damaged_qty != ZERO:
                        raise HTTPException(status_code=422, detail="Damaged quantity can only be recorded for packaging lines")
                    actuals[line.id] = (actual_qty, damaged_qty)

                actual_output = _validate_input_precision(
                    as_decimal(payload.actual_good_output_qty),
                    finished_places,
                    "Actual good output quantity",
                )
                if actual_output <= ZERO:
                    raise HTTPException(status_code=422, detail="Actual good output must be positive")

                cost_inputs = []
                for entry in payload.cost_lines:
                    amount = as_decimal(entry.amount)
                    rounded_amount = quantize(amount, MONEY_SCALE)
                    if amount != rounded_amount:
                        raise HTTPException(status_code=422, detail="Cost entries must have at most two decimal places")
                    if not entry.description.strip():
                        raise HTTPException(status_code=422, detail="Cost descriptions cannot be blank")
                    cost_inputs.append((entry.cost_type, entry.description.strip(), rounded_amount))

                stock_keys = sorted(
                    {(line.inventory_item_id, location.id) for line in run_lines}
                    | {(run.finished_inventory_item_id, location.id)}
                )
                for item_id, location_id in stock_keys:
                    db.execute(
                        pg_insert(InventoryBalance)
                        .values(inventory_item_id=item_id, inventory_location_id=location_id, on_hand_qty=ZERO)
                        .on_conflict_do_nothing(
                            index_elements=[InventoryBalance.inventory_item_id, InventoryBalance.inventory_location_id]
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
                            index_elements=[InventoryValuation.inventory_item_id, InventoryValuation.inventory_location_id]
                        )
                    )
                balances = {}
                valuations = {}
                for item_id, location_id in stock_keys:
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
                material_cost = ZERO
                movement_count = 0
                for line in run_lines:
                    actual_qty, damaged_qty = actuals[line.id]
                    key = (line.inventory_item_id, location.id)
                    balance = balances.get(key)
                    valuation = valuations.get(key)
                    if balance is None or valuation is None:
                        raise HTTPException(status_code=500, detail="Inventory projections were not initialized")
                    on_hand = as_decimal(balance.on_hand_qty)
                    valued_qty = as_decimal(valuation.valued_qty)
                    inventory_value = as_decimal(valuation.inventory_value)
                    if on_hand != valued_qty:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Inventory quantity projection mismatch for item {line.inventory_item_id}",
                        )
                    if actual_qty > on_hand:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Insufficient stock for {line.item_code_snapshot}: required {actual_qty}, available {on_hand}",
                        )
                    if actual_qty > ZERO:
                        unit_cost, extended_cost, new_qty, new_value, new_average = issue_valuation(
                            actual_qty, valued_qty, inventory_value
                        )
                        balance.on_hand_qty = quantize(on_hand - actual_qty, QTY_SCALE)
                        valuation.valued_qty = quantize(new_qty, QTY_SCALE)
                        valuation.inventory_value = quantize(new_value, MONEY_SCALE)
                        valuation.average_unit_cost = new_average
                        balance.updated_at = now
                        valuation.updated_at = now
                        db.add(StockMovement(
                            inventory_item_id=line.inventory_item_id,
                            inventory_location_id=location.id,
                            movement_type="PRODUCTION_ISSUE",
                            quantity_delta=-actual_qty,
                            unit_cost=unit_cost,
                            extended_cost=extended_cost,
                            production_run_line_id=line.id,
                            posted_at=now,
                            posted_by_user_id=actor_id,
                        ))
                        movement_count += 1
                    else:
                        unit_cost = (
                            quantize(inventory_value / valued_qty, COST_SCALE)
                            if valued_qty > ZERO else ZERO
                        )
                        extended_cost = ZERO

                    variance_qty = quantize(actual_qty - as_decimal(line.planned_qty), QTY_SCALE)
                    variance_percent = quantize(
                        (variance_qty / as_decimal(line.planned_qty)) * Decimal("100"),
                        PERCENT_SCALE,
                    )
                    line.actual_qty = actual_qty
                    line.damaged_qty = damaged_qty
                    line.variance_qty = variance_qty
                    line.variance_percent = variance_percent
                    line.variance_alert = abs(variance_percent) > as_decimal(run.variance_tolerance_percent)
                    line.unit_cost_snapshot = unit_cost
                    line.line_cost = quantize(extended_cost, MONEY_SCALE)
                    material_cost += line.line_cost

                cost_total = sum((amount for _, _, amount in cost_inputs), ZERO)
                total_run_cost = quantize(material_cost + cost_total, MONEY_SCALE)
                with localcontext() as context:
                    context.prec = 28
                    cost_per_good_unit = quantize(total_run_cost / actual_output, COST_SCALE)
                yield_variance_qty = quantize(actual_output - as_decimal(run.expected_output_qty), QTY_SCALE)
                yield_variance_percent = quantize(
                    (yield_variance_qty / as_decimal(run.expected_output_qty)) * Decimal("100"),
                    PERCENT_SCALE,
                )

                for cost_type, description, amount in cost_inputs:
                    db.add(ProductionCostLine(
                        production_run_id=run.id,
                        cost_type=cost_type,
                        description=description,
                        amount=amount,
                    ))

                output = ProductionRunOutput(
                    production_run_id=run.id,
                    product_id=run.product_id,
                    inventory_item_id=run.finished_inventory_item_id,
                    good_qty=actual_output,
                    base_unit_code_snapshot=run.output_unit_code_snapshot,
                )
                db.add(output)
                db.flush()

                output_key = (run.finished_inventory_item_id, location.id)
                output_balance = balances[output_key]
                output_valuation = valuations[output_key]
                output_on_hand = as_decimal(output_balance.on_hand_qty)
                output_qty = as_decimal(output_valuation.valued_qty)
                output_value = as_decimal(output_valuation.inventory_value)
                if output_on_hand != output_qty:
                    raise HTTPException(status_code=409, detail="Finished-goods quantity projection mismatch")
                output_unit_cost, output_extended_cost, new_output_qty, new_output_value, new_output_average = receive_output_valuation(
                    actual_output, total_run_cost, output_qty, output_value
                )
                output_balance.on_hand_qty = quantize(output_on_hand + actual_output, QTY_SCALE)
                output_balance.updated_at = now
                output_valuation.valued_qty = quantize(new_output_qty, QTY_SCALE)
                output_valuation.inventory_value = quantize(new_output_value, MONEY_SCALE)
                output_valuation.average_unit_cost = new_output_average
                output_valuation.updated_at = now
                db.add(StockMovement(
                    inventory_item_id=run.finished_inventory_item_id,
                    inventory_location_id=location.id,
                    movement_type="PRODUCTION_OUTPUT",
                    quantity_delta=actual_output,
                    unit_cost=output_unit_cost,
                    extended_cost=output_extended_cost,
                    production_run_output_id=output.id,
                    posted_at=now,
                    posted_by_user_id=actor_id,
                ))
                movement_count += 1

                db.flush()
                run.actual_good_output_qty = actual_output
                run.yield_variance_qty = yield_variance_qty
                run.yield_variance_percent = yield_variance_percent
                run.yield_variance_alert = abs(yield_variance_percent) > as_decimal(run.variance_tolerance_percent)
                run.total_run_cost = total_run_cost
                run.cost_per_good_unit = cost_per_good_unit
                run.wastage_note = payload.wastage_note
                run.status = "POSTED"
                run.posted_at = now
                run.posted_by_user_id = actor_id
                db.add(AuditEvent(
                    actor_user_id=actor_id,
                    action="PRODUCTION_RUN_POSTED",
                    entity_type="PRODUCTION_RUN",
                    entity_id=run.id,
                    after_data={
                        "run_number": run.run_number,
                        "movement_count": movement_count,
                        "actual_good_output_qty": str(actual_output),
                        "yield_variance_percent": str(yield_variance_percent),
                        "yield_variance_alert": run.yield_variance_alert,
                        "material_cost": str(quantize(material_cost, MONEY_SCALE)),
                        "production_costs": str(quantize(cost_total, MONEY_SCALE)),
                        "total_run_cost": str(total_run_cost),
                        "cost_per_good_unit": str(cost_per_good_unit),
                        "status": "POSTED",
                    },
                ))
                idem.response_status = 200
                idem.response_body = {"run_id": run.id}
                idem.completed_at = now
                target_run_id = run.id
                db.flush()
        return _load_run(db, target_run_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Production run conflicts with an existing posting") from exc
