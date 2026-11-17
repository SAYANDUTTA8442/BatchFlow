import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Customer, InventoryItem, Product, Role, Unit, User
from app.services.auth import create_user


def _login(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_admin_can_create_inventory_item_and_product(
    client: TestClient, db: Session, user: User
) -> None:
    token = _login(client, user)
    packet_unit_id = db.scalar(select(Unit.id).where(Unit.code == "PACKET"))
    item_response = client.post(
        "/api/master-data/inventory-items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "code": f"FG-{uuid.uuid4().hex[:8]}",
            "name": "Murukku 200g",
            "category": "FINISHED_GOOD",
            "base_unit_id": packet_unit_id,
        },
    )
    assert item_response.status_code == 201
    item_id = item_response.json()["id"]

    product_response = client.post(
        "/api/master-data/products",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "inventory_item_id": item_id,
            "sku": f"MUR-200-{uuid.uuid4().hex[:6]}",
            "name": "Murukku 200g",
            "pack_size_value": "200",
            "pack_size_unit_id": db.scalar(select(Unit.id).where(Unit.code == "G")),
            "default_selling_price": "50.00",
            "hsn_code": "1905",
        },
    )
    assert product_response.status_code == 201
    assert product_response.json()["inventory_item_id"] == item_id


def test_product_rejects_non_finished_inventory_item(
    client: TestClient, db: Session, user: User
) -> None:
    token = _login(client, user)
    kg_id = db.scalar(select(Unit.id).where(Unit.code == "KG"))
    item = InventoryItem(
        code=f"RM-{uuid.uuid4().hex[:8]}",
        name="Flour",
        category="RAW_MATERIAL",
        base_unit_id=kg_id,
    )
    db.add(item)
    db.commit()
    response = client.post(
        "/api/master-data/products",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "inventory_item_id": item.id,
            "sku": f"INVALID-{uuid.uuid4().hex[:8]}",
            "name": "Invalid product",
            "default_selling_price": "10",
        },
    )
    assert response.status_code == 422


def test_customer_assignment_is_validated_and_salesman_list_is_scoped(
    client: TestClient, db: Session, user: User
) -> None:
    salesman = create_user(
        db,
        full_name="Assigned Salesman",
        email=f"sales-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["salesman"],
    )
    admin_token = _login(client, user)
    response = client.post(
        "/api/master-data/customers",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "customer_code": f"C-{uuid.uuid4().hex[:8]}",
            "name": "Retailer Example",
            "customer_type": "RETAILER",
            "state_code": "33",
            "salesman_user_ids": [salesman.id],
        },
    )
    assert response.status_code == 201
    assert response.json()["salesman_user_ids"] == [salesman.id]

    salesman_token = _login(client, salesman)
    visible = client.get(
        "/api/master-data/customers",
        headers={"Authorization": f"Bearer {salesman_token}"},
    )
    assert visible.status_code == 200
    assert [row["id"] for row in visible.json()] == [response.json()["id"]]


def test_unit_conversion_rejects_incompatible_dimensions(
    client: TestClient, db: Session, user: User
) -> None:
    token = _login(client, user)
    kg_id = db.scalar(select(Unit.id).where(Unit.code == "KG"))
    litre_id = db.scalar(select(Unit.id).where(Unit.code == "L"))
    response = client.post(
        "/api/master-data/unit-conversions",
        headers={"Authorization": f"Bearer {token}"},
        json={"from_unit_id": kg_id, "to_unit_id": litre_id, "factor": "1"},
    )
    assert response.status_code == 422


def test_salesman_cannot_write_master_data(
    client: TestClient, db: Session
) -> None:
    salesman = create_user(
        db,
        full_name="Restricted Salesman",
        email=f"sales-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["salesman"],
    )
    token = _login(client, salesman)
    unit_id = db.scalar(select(Unit.id).where(Unit.code == "KG"))
    response = client.post(
        "/api/master-data/inventory-items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "code": f"RM-{uuid.uuid4().hex[:8]}",
            "name": "Flour",
            "category": "RAW_MATERIAL",
            "base_unit_id": unit_id,
        },
    )
    assert response.status_code == 403
