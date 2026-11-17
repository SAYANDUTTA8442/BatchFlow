from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_current_principal, require_roles
from app.db.session import get_db
from app.schemas.inventory import (
    InventoryBalanceRead,
    InventoryReconciliationRead,
    PurchaseReceiptCreate,
    PurchaseReceiptPostRead,
    PurchaseReceiptRead,
    StockAdjustmentCreate,
    StockAdjustmentPostRead,
    StockAdjustmentRead,
    StockMovementRead,
)
from app.services.inventory import (
    create_stock_adjustment,
    list_inventory_balances,
    list_stock_movements,
    post_stock_adjustment,
    create_purchase_receipt,
    post_purchase_receipt,
    reconcile_inventory,
)


router = APIRouter(prefix="/api/inventory", tags=["inventory"])
Db = Annotated[Session, Depends(get_db)]
PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
InventoryReadDep = Annotated[
    Principal, Depends(require_roles("admin", "owner", "auditor", "production"))
]
InventoryWriteDep = Annotated[Principal, Depends(require_roles("admin", "owner"))]


@router.post("/adjustments", response_model=StockAdjustmentRead, status_code=201)
def create_adjustment(payload: StockAdjustmentCreate, db: Db, principal: InventoryWriteDep):
    return create_stock_adjustment(db, payload, principal.user.id)


@router.post("/adjustments/{adjustment_id}/post", response_model=StockAdjustmentPostRead)
def post_adjustment(
    adjustment_id: int,
    db: Db,
    principal: InventoryWriteDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
):
    if not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be blank")
    return post_stock_adjustment(db, adjustment_id, principal.user.id, idempotency_key)


@router.get("/balances", response_model=list[InventoryBalanceRead])
def get_balances(db: Db, principal: InventoryReadDep):
    return list_inventory_balances(db)


@router.get("/movements", response_model=list[StockMovementRead])
def get_movements(db: Db, principal: InventoryReadDep):
    return list_stock_movements(db)



@router.post("/purchase-receipts", response_model=PurchaseReceiptRead, status_code=201)
def create_receipt(payload: PurchaseReceiptCreate, db: Db, principal: InventoryWriteDep):
    return create_purchase_receipt(db, payload, principal.user.id)


@router.post("/purchase-receipts/{receipt_id}/post", response_model=PurchaseReceiptPostRead)
def post_receipt(
    receipt_id: int,
    db: Db,
    principal: InventoryWriteDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
):
    if not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be blank")
    return post_purchase_receipt(db, receipt_id, principal.user.id, idempotency_key)


@router.get("/reconciliation", response_model=InventoryReconciliationRead)
def get_reconciliation(db: Db, principal: InventoryReadDep):
    return reconcile_inventory(db)
