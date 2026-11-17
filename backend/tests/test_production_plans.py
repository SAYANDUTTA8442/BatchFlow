import uuid
from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.seed_reference_data import seed_reference_data
from app.db.session import get_db
from app.main import app
from app.models import InventoryItem, Product, StockMovement, Unit, User
from app.models.production import ProductionRun
from app.services.auth import create_user


@pytest.fixture(scope="module")
def production_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory.begin() as session:
        seed_reference_data(session)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(production_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=production_engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(production_engine):
    factory = sessionmaker(bind=production_engine, class_=Session, expire_on_commit=False)

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
        db, full_name="Production Admin", email=f"prod-admin-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!", role_codes=["admin"],
    )


@pytest.fixture
def supervisor(db: Session) -> User:
    return create_user(
        db, full_name="Production Supervisor", email=f"prod-supervisor-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!", role_codes=["production"],
    )


def _token(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _master_data(db: Session):
    kg_id = db.scalar(select(Unit.id).where(Unit.code == "KG"))
    litre_id = db.scalar(select(Unit.id).where(Unit.code == "L"))
    packet_id = db.scalar(select(Unit.id).where(Unit.code == "PACKET"))
    flour = InventoryItem(code=f"FLOUR-{uuid.uuid4().hex[:8]}", name="Flour", category="RAW_MATERIAL", base_unit_id=kg_id)
    oil = InventoryItem(code=f"OIL-{uuid.uuid4().hex[:8]}", name="Oil", category="RAW_MATERIAL", base_unit_id=litre_id)
    pouch = InventoryItem(code=f"POUCH-{uuid.uuid4().hex[:8]}", name="Pouch", category="PACKAGING", base_unit_id=packet_id)
    finished = InventoryItem(code=f"FG-{uuid.uuid4().hex[:8]}", name="Murukku", category="FINISHED_GOOD", base_unit_id=packet_id)
    db.add_all([flour, oil, pouch, finished])
    db.flush()
    product = Product(
        inventory_item_id=finished.id, sku=f"MUR-{uuid.uuid4().hex[:8]}",
        name="Murukku 200g", default_selling_price=Decimal("50"),
    )
    db.add(product)
    db.commit()
    return product, flour, oil, pouch, finished


def _create_active_bom(client, admin, product, flour, oil, pouch):
    headers = {"Authorization": f"Bearer {_token(client, admin)}"}
    response = client.post("/api/production/boms", headers=headers, json={
        "product_id": product.id,
        "expected_output_qty": "200",
        "effective_from": "2026-01-01",
        "lines": [
            {"inventory_item_id": flour.id, "line_type": "RAW_MATERIAL", "quantity_per_batch": "40"},
            {"inventory_item_id": oil.id, "line_type": "RAW_MATERIAL", "quantity_per_batch": "10"},
            {"inventory_item_id": pouch.id, "line_type": "PACKAGING", "quantity_per_batch": "200"},
        ],
    })
    assert response.status_code == 201, response.text
    bom_id = response.json()["id"]
    activated = client.post(f"/api/production/boms/{bom_id}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    return bom_id


def test_production_supervisor_creates_scaled_draft_plan(client, db, admin, supervisor):
    product, flour, oil, pouch, finished = _master_data(db)
    bom_id = _create_active_bom(client, admin, product, flour, oil, pouch)
    headers = {"Authorization": f"Bearer {_token(client, supervisor)}"}
    response = client.post("/api/production/runs", headers=headers, json={
        "bom_id": bom_id, "production_date": "2026-11-17", "batch_multiplier": "0.94",
    })
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "DRAFT"
    assert run["run_number"].startswith("PR-20261117-")
    assert run["bom_version_snapshot"] == 1
    assert Decimal(run["expected_output_qty"]) == Decimal("188.000000")
    planned = {line["inventory_item_id"]: Decimal(line["planned_qty"]) for line in run["lines"]}
    assert planned[flour.id] == Decimal("37.600000")
    assert planned[oil.id] == Decimal("9.400000")
    assert planned[pouch.id] == Decimal("188.000000")
    assert run["product_sku_snapshot"] == product.sku
    assert run["finished_item_code_snapshot"] == finished.code


def test_plan_rejects_bom_outside_effective_date(client, db, admin, supervisor):
    product, flour, oil, pouch, _ = _master_data(db)
    bom_id = _create_active_bom(client, admin, product, flour, oil, pouch)
    headers = {"Authorization": f"Bearer {_token(client, supervisor)}"}
    response = client.post("/api/production/runs", headers=headers, json={
        "bom_id": bom_id, "production_date": "2025-12-31", "batch_multiplier": "1",
    })
    assert response.status_code == 409


def test_only_production_role_can_create_run_plan(client, db, admin):
    product, flour, oil, pouch, _ = _master_data(db)
    bom_id = _create_active_bom(client, admin, product, flour, oil, pouch)
    headers = {"Authorization": f"Bearer {_token(client, admin)}"}
    response = client.post("/api/production/runs", headers=headers, json={
        "bom_id": bom_id, "production_date": "2026-11-17", "batch_multiplier": "1",
    })
    assert response.status_code == 403


def test_plan_snapshots_survive_later_master_data_changes(client, db, admin, supervisor):
    product, flour, oil, pouch, _ = _master_data(db)
    bom_id = _create_active_bom(client, admin, product, flour, oil, pouch)
    headers = {"Authorization": f"Bearer {_token(client, supervisor)}"}
    created = client.post("/api/production/runs", headers=headers, json={
        "bom_id": bom_id, "production_date": "2026-11-17", "batch_multiplier": "1",
    })
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    flour.name = "Renamed Flour"
    db.commit()
    fetched = client.get(f"/api/production/runs/{run_id}", headers=headers)
    assert fetched.status_code == 200
    line = next(row for row in fetched.json()["lines"] if row["inventory_item_id"] == flour.id)
    assert line["item_name_snapshot"] == "Flour"
    assert line["planned_qty"] == "40.000000"
    assert db.scalar(select(ProductionRun).where(ProductionRun.id == run_id)).status == "DRAFT"


def test_draft_plan_does_not_create_stock_movements(client, db, admin, supervisor):
    product, flour, oil, pouch, _ = _master_data(db)
    bom_id = _create_active_bom(client, admin, product, flour, oil, pouch)
    headers = {"Authorization": f"Bearer {_token(client, supervisor)}"}
    response = client.post("/api/production/runs", headers=headers, json={
        "bom_id": bom_id, "production_date": "2026-11-17", "batch_multiplier": "1",
    })
    assert response.status_code == 201, response.text
    assert db.scalar(select(ProductionRun).where(ProductionRun.id == response.json()["id"])).status == "DRAFT"
    assert db.scalar(select(StockMovement.id).limit(1)) is None
