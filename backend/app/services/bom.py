from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditEvent, InventoryItem, Product
from app.models.bom import Bom, BomLine


def _validate_lines(db: Session, lines) -> list[dict]:
    item_ids = [line.inventory_item_id for line in lines]
    if len(item_ids) != len(set(item_ids)):
        raise HTTPException(status_code=422, detail="A BOM cannot contain the same inventory item twice")
    items = {
        item.id: item
        for item in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(item_ids))).all()
    }
    normalized = []
    for line in lines:
        item = items.get(line.inventory_item_id)
        expected_category = "RAW_MATERIAL" if line.line_type == "RAW_MATERIAL" else "PACKAGING"
        if item is None or not item.is_active:
            raise HTTPException(status_code=422, detail="Every BOM component must be an active inventory item")
        if item.category != expected_category:
            raise HTTPException(
                status_code=422,
                detail=f"Inventory item {item.code} category does not match BOM line type",
            )
        normalized.append({
            "inventory_item_id": item.id,
            "line_type": line.line_type,
            "quantity_per_batch": line.quantity_per_batch,
            "notes": line.notes,
        })
    return normalized


def _audit(db: Session, actor_id: int, action: str, bom: Bom, before: dict | None, after: dict) -> None:
    db.add(AuditEvent(
        actor_user_id=actor_id,
        action=action,
        entity_type="BOM",
        entity_id=bom.id,
        before_data=before,
        after_data=after,
    ))


def _load_bom(db: Session, bom_id: int) -> Bom:
    bom = db.scalar(select(Bom).options(selectinload(Bom.lines)).where(Bom.id == bom_id))
    if bom is None:
        raise HTTPException(status_code=404, detail="BOM not found")
    return bom


def list_boms(db: Session, product_id: int | None = None, status_filter: str | None = None) -> list[Bom]:
    query = select(Bom).options(selectinload(Bom.lines)).order_by(Bom.product_id, Bom.version.desc())
    if product_id is not None:
        query = query.where(Bom.product_id == product_id)
    if status_filter is not None:
        query = query.where(Bom.status == status_filter)
    return list(db.scalars(query.limit(500)).unique().all())


def get_bom(db: Session, bom_id: int) -> Bom:
    return _load_bom(db, bom_id)


def create_bom(db: Session, payload, actor_id: int) -> Bom:
    db.rollback()
    with db.begin():
        product = db.scalar(select(Product).where(Product.id == payload.product_id).with_for_update())
        if product is None or not product.is_active:
            raise HTTPException(status_code=422, detail="BOM must reference an active product")
        finished_item = db.get(InventoryItem, product.inventory_item_id)
        if finished_item is None or not finished_item.is_active or finished_item.category != "FINISHED_GOOD":
            raise HTTPException(status_code=422, detail="Product must map to an active FINISHED_GOOD item")
        if payload.effective_to is not None and payload.effective_to < payload.effective_from:
            raise HTTPException(status_code=422, detail="effective_to cannot precede effective_from")
        lines = _validate_lines(db, payload.lines)
        next_version = (db.scalar(
            select(func.coalesce(func.max(Bom.version), 0)).where(Bom.product_id == product.id)
        ) or 0) + 1
        bom = Bom(
            product_id=product.id,
            version=next_version,
            status="DRAFT",
            expected_output_qty=payload.expected_output_qty,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            created_by_user_id=actor_id,
            lines=[BomLine(**line) for line in lines],
        )
        db.add(bom)
        db.flush()
        _audit(db, actor_id, "BOM_DRAFT_CREATED", bom, None, {
            "product_id": product.id,
            "version": next_version,
            "expected_output_qty": str(payload.expected_output_qty),
            "line_count": len(lines),
        })
        bom_id = bom.id
    return _load_bom(db, bom_id)


def update_bom(db: Session, bom_id: int, payload, actor_id: int) -> Bom:
    db.rollback()
    with db.begin():
        bom = db.scalar(select(Bom).where(Bom.id == bom_id).with_for_update())
        if bom is None:
            raise HTTPException(status_code=404, detail="BOM not found")
        if bom.status != "DRAFT":
            raise HTTPException(status_code=409, detail="Only draft BOM versions can be edited")
        if payload.effective_to is not None and payload.effective_to < payload.effective_from:
            raise HTTPException(status_code=422, detail="effective_to cannot precede effective_from")
        lines = _validate_lines(db, payload.lines)
        before = {
            "expected_output_qty": str(bom.expected_output_qty),
            "effective_from": bom.effective_from.isoformat(),
            "effective_to": bom.effective_to.isoformat() if bom.effective_to else None,
            "line_count": len(bom.lines),
        }
        bom.lines.clear()
        bom.expected_output_qty = payload.expected_output_qty
        bom.effective_from = payload.effective_from
        bom.effective_to = payload.effective_to
        bom.lines.extend(BomLine(**line) for line in lines)
        _audit(db, actor_id, "BOM_DRAFT_UPDATED", bom, before, {
            "expected_output_qty": str(payload.expected_output_qty),
            "effective_from": payload.effective_from.isoformat(),
            "effective_to": payload.effective_to.isoformat() if payload.effective_to else None,
            "line_count": len(lines),
        })
    return _load_bom(db, bom_id)


def activate_bom(db: Session, bom_id: int, actor_id: int) -> Bom:
    db.rollback()
    with db.begin():
        bom = db.scalar(select(Bom).where(Bom.id == bom_id).with_for_update())
        if bom is None:
            raise HTTPException(status_code=404, detail="BOM not found")
        if bom.status != "DRAFT":
            raise HTTPException(status_code=409, detail="Only draft BOM versions can be activated")
        product = db.scalar(select(Product).where(Product.id == bom.product_id).with_for_update())
        if product is None or not product.is_active:
            raise HTTPException(status_code=409, detail="BOM product is inactive or unavailable")
        if not bom.lines:
            raise HTTPException(status_code=409, detail="A BOM must contain at least one component")
        overlap = db.scalar(
            select(Bom.id).where(
                Bom.product_id == bom.product_id,
                Bom.status == "ACTIVE",
                Bom.id != bom.id,
                or_(Bom.effective_to.is_(None), Bom.effective_to >= bom.effective_from),
                or_(bom.effective_to is None, Bom.effective_from <= bom.effective_to),
            ).limit(1)
        )
        if overlap is not None:
            raise HTTPException(status_code=409, detail="An active BOM already covers part of this effective date range")
        bom.status = "ACTIVE"
        _audit(db, actor_id, "BOM_ACTIVATED", bom, {"status": "DRAFT"}, {
            "status": "ACTIVE",
            "version": bom.version,
            "effective_from": bom.effective_from.isoformat(),
            "effective_to": bom.effective_to.isoformat() if bom.effective_to else None,
        })
    return _load_bom(db, bom_id)


def retire_bom(db: Session, bom_id: int, effective_to: date, actor_id: int) -> Bom:
    db.rollback()
    with db.begin():
        bom = db.scalar(select(Bom).where(Bom.id == bom_id).with_for_update())
        if bom is None:
            raise HTTPException(status_code=404, detail="BOM not found")
        if bom.status != "ACTIVE":
            raise HTTPException(status_code=409, detail="Only active BOM versions can be retired")
        if effective_to < bom.effective_from:
            raise HTTPException(status_code=422, detail="Retirement date cannot precede effective_from")
        if bom.effective_to is not None and effective_to > bom.effective_to:
            raise HTTPException(status_code=422, detail="Retirement cannot extend the configured effective range")
        before = {"status": bom.status, "effective_to": bom.effective_to.isoformat() if bom.effective_to else None}
        bom.status = "RETIRED"
        bom.effective_to = effective_to
        _audit(db, actor_id, "BOM_RETIRED", bom, before, {
            "status": "RETIRED", "effective_to": effective_to.isoformat(),
        })
    return _load_bom(db, bom_id)


def scale_bom(db: Session, bom_id: int, multiplier: Decimal) -> dict:
    if multiplier <= 0 or not multiplier.is_finite():
        raise HTTPException(status_code=422, detail="Batch multiplier must be a finite positive decimal")
    bom = _load_bom(db, bom_id)
    if bom.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Only active BOM versions can be scaled")
    with localcontext() as context:
        context.prec = 28
        output = (Decimal(bom.expected_output_qty) * multiplier).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        scaled_lines = [
            {
                "inventory_item_id": line.inventory_item_id,
                "line_type": line.line_type,
                "quantity_per_batch": Decimal(line.quantity_per_batch),
                "planned_quantity": (Decimal(line.quantity_per_batch) * multiplier).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                ),
            }
            for line in bom.lines
        ]
    return {
        "bom_id": bom.id,
        "product_id": bom.product_id,
        "version": bom.version,
        "batch_multiplier": multiplier,
        "expected_output_qty_per_batch": Decimal(bom.expected_output_qty),
        "expected_good_output_qty": output,
        "lines": scaled_lines,
    }
