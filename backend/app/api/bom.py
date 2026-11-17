from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_current_principal, require_roles
from app.db.session import get_db
from app.schemas.bom import BomCreate, BomRead, BomRetire, BomScaleRead, BomUpdate
from app.services.bom import (
    activate_bom, create_bom, get_bom, list_boms, retire_bom, scale_bom, update_bom,
)


router = APIRouter(prefix="/api/production/boms", tags=["production - BOM"])
Db = Annotated[Session, Depends(get_db)]
ReadPrincipal = Annotated[Principal, Depends(require_roles("admin", "owner", "auditor", "production"))]
WritePrincipal = Annotated[Principal, Depends(require_roles("admin", "owner"))]


@router.get("", response_model=list[BomRead])
def get_boms(
    db: Db,
    principal: ReadPrincipal,
    product_id: int | None = Query(default=None, gt=0),
    status_filter: Literal["DRAFT", "ACTIVE", "RETIRED"] | None = Query(default=None, alias="status"),
):
    return list_boms(db, product_id, status_filter)


@router.post("", response_model=BomRead, status_code=201)
def post_bom(payload: BomCreate, db: Db, principal: WritePrincipal):
    return create_bom(db, payload, principal.user.id)


@router.get("/{bom_id}", response_model=BomRead)
def get_bom_by_id(bom_id: int, db: Db, principal: ReadPrincipal):
    return get_bom(db, bom_id)


@router.put("/{bom_id}", response_model=BomRead)
def put_bom(bom_id: int, payload: BomUpdate, db: Db, principal: WritePrincipal):
    return update_bom(db, bom_id, payload, principal.user.id)


@router.post("/{bom_id}/activate", response_model=BomRead)
def post_activate_bom(bom_id: int, db: Db, principal: WritePrincipal):
    return activate_bom(db, bom_id, principal.user.id)


@router.post("/{bom_id}/retire", response_model=BomRead)
def post_retire_bom(bom_id: int, payload: BomRetire, db: Db, principal: WritePrincipal):
    return retire_bom(db, bom_id, payload.effective_to, principal.user.id)


@router.get("/{bom_id}/scale", response_model=BomScaleRead)
def get_scaled_bom(
    bom_id: int,
    db: Db,
    principal: ReadPrincipal,
    batch_multiplier: Decimal = Query(gt=0, allow_inf_nan=False),
):
    return scale_bom(db, bom_id, batch_multiplier)
