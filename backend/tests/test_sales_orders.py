import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.seed_reference_data import seed_reference_data
from app.db.session import get_db
from app.main import app
from app.models import Customer, CustomerSalesman, InventoryItem, Product, SalesOrder, SalesOrderLine, Unit
from app.services.auth import create_user


@pytest.fixture(scope="module")
def sales_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory.begin() as session:
        seed_reference_data(session)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(sales_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=sales_engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(sales_engine):
    factory = sessionmaker(bind=sales_engine, class_=Session, expire_on_commit=False)

    def override_db():
        with factory() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sales_setup(db: Session):
    admin = create_user(
        db, full_name="Sales Admin", email=f"admin-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!", role_codes=["admin"],
    )
    salesman = create_user(
        db, full_name="Field Sales", email=f"sales-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!", role_codes=["salesman"],
    )
    other_salesman = create_user(
        db, full_name="Other Sales", email=f"other-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!", role_codes=["salesman"],
    )
    packet = db.scalar(select(Unit).where(Unit.code == "PACKET"))
    gram = db.scalar(select(Unit).where(Unit.code == "G"))
    item = InventoryItem(
        code=f"FG-{uuid.uuid4().hex[:8]}", name="Murukku 200g",
        category="FINISHED_GOOD", base_unit_id=packet.id,
    )
    db.add(item)
    db.flush()
    product = Product(
        inventory_item_id=item.id, sku=f"MUR-{uuid.uuid4().hex[:8]}",
        name="Murukku 200g", pack_size_value="200", pack_size_unit_id=gram.id,
        hsn_code="1905", default_selling_price="50.00",
    )
    customer = Customer(
        customer_code=f"C-{uuid.uuid4().hex[:8]}", name="Retailer A",
        customer_type="RETAILER", state_code="33", is_active=True,
    )
    db.add_all([product, customer])
    db.flush()
    db.add(CustomerSalesman(customer_id=customer.id, salesman_user_id=salesman.id, assigned_by_user_id=admin.id))
    db.commit()
    return admin, salesman, other_salesman, customer, product


def _token(client: TestClient, user) -> str:
    response = client.post(
        "/api/auth/login", headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_salesman_submits_order_with_server_price_snapshot_and_idempotency(client, db, sales_setup):
    admin, salesman, other_salesman, customer, product = sales_setup
    token = _token(client, salesman)
    payload = {"customer_id": customer.id, "lines": [{"product_id": product.id, "quantity": "12"}]}
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "submit-001"}
    response = client.post("/api/sales/orders", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    assert response.json()["status"] == "SUBMITTED"
    line = response.json()["lines"][0]
    assert line["submitted_quantity"] == "12.000000"
    assert line["submitted_unit_price"] == "50.000000"
    assert line["line_taxable_value"] == "600.00"

    replay = client.post("/api/sales/orders", headers=headers, json=payload)
    assert replay.status_code == 201
    assert replay.json()["id"] == order_id
    assert db.scalar(select(SalesOrder).where(SalesOrder.id == order_id)).status == "SUBMITTED"
    assert len(db.scalars(select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order_id)).all()) == 1

    changed = {"customer_id": customer.id, "lines": [{"product_id": product.id, "quantity": "13"}]}
    conflict = client.post("/api/sales/orders", headers=headers, json=changed)
    assert conflict.status_code == 409


def test_salesman_cannot_submit_for_unassigned_customer_or_view_other_orders(client, db, sales_setup):
    admin, salesman, other_salesman, customer, product = sales_setup
    other_customer = Customer(
        customer_code=f"C-{uuid.uuid4().hex[:8]}", name="Private Retailer",
        customer_type="RETAILER", state_code="33", is_active=True,
    )
    db.add(other_customer)
    db.commit()

    token = _token(client, salesman)
    denied = client.post(
        "/api/sales/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "submit-002"},
        json={"customer_id": other_customer.id, "lines": [{"product_id": product.id, "quantity": "1"}]},
    )
    assert denied.status_code == 403

    own = client.post(
        "/api/sales/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "submit-003"},
        json={"customer_id": customer.id, "lines": [{"product_id": product.id, "quantity": "1"}]},
    )
    assert own.status_code == 201
    other_token = _token(client, other_salesman)
    hidden = client.get(f"/api/sales/orders/{own.json()['id']}", headers={"Authorization": f"Bearer {other_token}"})
    assert hidden.status_code == 404
    visible = client.get("/api/sales/orders", headers={"Authorization": f"Bearer {other_token}"})
    assert visible.status_code == 200
    assert visible.json() == []


def test_order_quantity_respects_finished_good_unit_precision(client, sales_setup):
    admin, salesman, other_salesman, customer, product = sales_setup
    token = _token(client, salesman)
    response = client.post(
        "/api/sales/orders",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "submit-004"},
        json={"customer_id": customer.id, "lines": [{"product_id": product.id, "quantity": "1.5"}]},
    )
    assert response.status_code == 422
