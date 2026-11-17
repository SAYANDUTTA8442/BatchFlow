from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, require_roles
from app.db.session import get_db
from app.schemas.production import ProductionRunCreate, ProductionRunPost, ProductionRunRead
from app.services.production import (
    create_production_run,
    get_production_run,
    list_production_runs,
    post_production_run,
)


router = APIRouter(prefix="/api/production/runs", tags=["production - runs"])
Db = Annotated[Session, Depends(get_db)]
ReadPrincipal = Annotated[
    Principal, Depends(require_roles("admin", "owner", "auditor", "production"))
]
ProductionPrincipal = Annotated[Principal, Depends(require_roles("production"))]


@router.get("", response_model=list[ProductionRunRead])
def get_runs(
    db: Db,
    principal: ReadPrincipal,
    production_date: date | None = None,
    status_filter: Literal["DRAFT", "POSTED", "REVERSED"] | None = Query(default=None, alias="status"),
):
    return list_production_runs(db, production_date, status_filter)


@router.post("", response_model=ProductionRunRead, status_code=201)
def create_run_draft(payload: ProductionRunCreate, db: Db, principal: ProductionPrincipal):
    return create_production_run(db, payload, principal.user.id)


@router.get("/{run_id}", response_model=ProductionRunRead)
def get_run_by_id(run_id: int, db: Db, principal: ReadPrincipal):
    return get_production_run(db, run_id)


@router.post("/{run_id}/post", response_model=ProductionRunRead)
def post_run(
    run_id: int,
    payload: ProductionRunPost,
    db: Db,
    principal: ProductionPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
):
    if not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be blank")
    return post_production_run(db, run_id, principal.user.id, idempotency_key, payload)
