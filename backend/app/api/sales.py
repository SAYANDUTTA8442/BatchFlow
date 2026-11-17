from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, require_roles
from app.db.session import get_db
from app.schemas.sales import SalesOrderCreate, SalesOrderRead
from app.services.sales import get_sales_order, list_sales_orders, submit_sales_order


router = APIRouter(prefix="/api/sales/orders", tags=["sales - orders"])
Db = Annotated[Session, Depends(get_db)]
SalesRead = Annotated[Principal, Depends(require_roles("admin", "owner", "auditor", "salesman"))]
SalesSubmit = Annotated[Principal, Depends(require_roles("admin", "salesman"))]


@router.get("", response_model=list[SalesOrderRead])
def get_orders(
    db: Db,
    principal: SalesRead,
    status_filter: Literal["SUBMITTED", "APPROVED", "REJECTED", "CANCELLED", "INVOICED", "DISPATCHED"] | None = Query(
        default=None, alias="status"
    ),
):
    return list_sales_orders(db, principal, status_filter)


@router.post("", response_model=SalesOrderRead, status_code=201)
def submit_order(
    payload: SalesOrderCreate,
    db: Db,
    principal: SalesSubmit,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
):
    if not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be blank")
    return submit_sales_order(db, payload, principal.user.id, idempotency_key)


@router.get("/{order_id}", response_model=SalesOrderRead)
def get_order(order_id: int, db: Db, principal: SalesRead):
    return get_sales_order(db, order_id, principal)
