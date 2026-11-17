from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditEvent, InventoryItem, Product, Unit
from app.models.bom import Bom
from app.models.production import ProductionRun, ProductionRunLine


QUANTITY_QUANTUM = Decimal("0.000001")


def _load_run(db: Session, run_id: int) -> ProductionRun:
    run = db.scalar(
        select(ProductionRun)
        .options(selectinload(ProductionRun.lines))
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
        .options(selectinload(ProductionRun.lines))
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
            multiplier = Decimal(payload.batch_multiplier).quantize(
                QUANTITY_QUANTUM, rounding=ROUND_HALF_UP
            )
            if multiplier <= 0:
                raise HTTPException(status_code=422, detail="Batch multiplier is below supported precision")
            expected_output = (Decimal(bom.expected_output_qty) * multiplier).quantize(
                QUANTITY_QUANTUM, rounding=ROUND_HALF_UP
            )
            if expected_output <= 0:
                raise HTTPException(status_code=422, detail="Scaled expected output must be positive")

            run_lines = []
            for line in bom.lines:
                planned_qty = (Decimal(line.quantity_per_batch) * multiplier).quantize(
                    QUANTITY_QUANTUM, rounding=ROUND_HALF_UP
                )
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
                    quantity_per_batch_snapshot=Decimal(line.quantity_per_batch),
                    planned_qty=planned_qty,
                ))

            run = ProductionRun(
                run_number="PENDING",
                product_id=product.id,
                product_sku_snapshot=product.sku,
                product_name_snapshot=product.name,
                finished_item_code_snapshot=finished_item.code,
                finished_item_name_snapshot=finished_item.name,
                output_unit_code_snapshot=finished_unit_code,
                bom_id=bom.id,
                bom_version_snapshot=bom.version,
                batch_multiplier=multiplier,
                expected_output_qty=expected_output,
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
                    "bom_id": bom.id,
                    "bom_version": bom.version,
                    "batch_multiplier": str(run.batch_multiplier),
                    "expected_output_qty": str(run.expected_output_qty),
                    "line_count": len(run.lines),
                },
            ))
            run_id = run.id
    return _load_run(db, run_id)
