import uuid

import pytest
from collections.abc import Generator
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.seed_reference_data import seed_reference_data
from app.db.session import get_db
from app.main import app
from app.models import (
    InventoryBalance,
    InventoryItem,
    InventoryLocation,
    StockMovement,
    Unit,
    User,
)
from app.services.auth import create_user


@pytest.fixture(scope="module")
def inventory_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory.begin() as session:
        seed_reference_data(session)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(inventory_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=inventory_engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(inventory_engine):
    factory = sessionmaker(bind=inventory_engine, class_=Session, expire_on_commit=False)

    def override_db():
        with factory() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin(db: Session) -> User:
    return create_user(
        db,
        full_name="Inventory Admin",
        email=f"inventory-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["admin"],
    )


def _token(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _item_and_location(db: Session) -> tuple[int, int]:
    kg_id = db.scalar(select(Unit.id).where(Unit.code == "KG"))
    item = InventoryItem(
        code=f"FLOUR-{uuid.uuid4().hex[:8]}",
        name="Flour",
        category="RAW_MATERIAL",
        base_unit_id=kg_id,
    )
    location = db.scalar(select(InventoryLocation).where(InventoryLocation.code == "FACTORY-01"))
    db.add(item)
    db.commit()
    return item.id, location.id


def _adjust(
    client: TestClient,
    token: str,
    item_id: int,
    location_id: int,
    number: str,
    reason: str,
    quantity: str,
    unit_cost: str | None,
    key: str,
):
    return client.post(
        "/api/inventory/adjustments",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "adjustment_number": number,
            "reason": reason,
            "lines": [{
                "inventory_item_id": item_id,
                "inventory_location_id": location_id,
                "quantity_delta": quantity,
                "unit_cost": unit_cost,
            }],
        },
    )


def _post(client: TestClient, token: str, adjustment_id: int, key: str):
    return client.post(
        f"/api/inventory/adjustments/{adjustment_id}/post",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )


def test_opening_balance_and_receipt_use_deterministic_wac(
    client: TestClient, db: Session, admin: User
) -> None:
    token = _token(client, admin)
    item_id, location_id = _item_and_location(db)

    opening = _adjust(client, token, item_id, location_id, "OPEN-001", "OPENING_BALANCE", "100", "42", "unused")
    assert opening.status_code == 201
    posted_opening = _post(client, token, opening.json()["id"], "opening-001")
    assert posted_opening.status_code == 200
    assert posted_opening.json()["movement_count"] == 1

    receipt = _adjust(client, token, item_id, location_id, "COUNT-002", "OTHER", "60", "45", "unused")
    assert receipt.status_code == 201
    posted_receipt = _post(client, token, receipt.json()["id"], "receipt-002")
    assert posted_receipt.status_code == 200

    balance = client.get(
        "/api/inventory/balances", headers={"Authorization": f"Bearer {token}"}
    )
    assert balance.status_code == 200
    row = next(value for value in balance.json() if value["inventory_item_id"] == item_id)
    assert Decimal(row["on_hand_qty"]) == Decimal("160.000000")
    assert Decimal(row["inventory_value"]) == Decimal("6900.00")
    assert Decimal(row["average_unit_cost"]) == Decimal("43.125000")
    assert Decimal(row["valued_qty"]) == Decimal("160.000000")

    movements = db.scalars(
        select(StockMovement).where(StockMovement.inventory_item_id == item_id)
    ).all()
    assert len(movements) == 2
    assert sum((Decimal(m.quantity_delta) for m in movements), Decimal("0")) == Decimal("160.000000")


def test_idempotent_post_does_not_duplicate_stock_movement(
    client: TestClient, db: Session, admin: User
) -> None:
    token = _token(client, admin)
    item_id, location_id = _item_and_location(db)
    draft = _adjust(client, token, item_id, location_id, "OPEN-RETRY", "OPENING_BALANCE", "5", "10", "unused")
    assert draft.status_code == 201
    adjustment_id = draft.json()["id"]

    first = _post(client, token, adjustment_id, "same-post-key")
    second = _post(client, token, adjustment_id, "same-post-key")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    count = len(
        db.scalars(
            select(StockMovement).where(StockMovement.inventory_item_id == item_id)
        ).all()
    )
    assert count == 1


def test_insufficient_stock_rolls_back_entire_adjustment(
    client: TestClient, db: Session, admin: User
) -> None:
    token = _token(client, admin)
    item_id, location_id = _item_and_location(db)
    draft = _adjust(client, token, item_id, location_id, "NEGATIVE-001", "COUNT_CORRECTION", "-1", None, "unused")
    assert draft.status_code == 201
    failed = _post(client, token, draft.json()["id"], "negative-key")
    assert failed.status_code == 409
    assert db.scalar(
        select(StockMovement.id).where(StockMovement.inventory_item_id == item_id)
    ) is None
    balance = db.get(InventoryBalance, (item_id, location_id))
    assert balance is None or Decimal(balance.on_hand_qty) == Decimal("0")


def test_opening_balance_requires_positive_quantity_and_cost(
    client: TestClient, admin: User, db: Session
) -> None:
    token = _token(client, admin)
    item_id, location_id = _item_and_location(db)
    negative = _adjust(client, token, item_id, location_id, "OPEN-BAD-1", "OPENING_BALANCE", "-2", None, "unused")
    assert negative.status_code == 422
    no_cost = _adjust(client, token, item_id, location_id, "OPEN-BAD-2", "OPENING_BALANCE", "2", None, "unused")
    assert no_cost.status_code == 422


def test_adjustment_post_requires_admin_or_owner(
    client: TestClient, db: Session
) -> None:
    salesman = create_user(
        db,
        full_name="Inventory Salesman",
        email=f"sales-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["salesman"],
    )
    token = _token(client, salesman)
    response = client.get("/api/inventory/balances", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
