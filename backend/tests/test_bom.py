import uuid
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
from app.models import InventoryItem, Product, Unit, User
from app.services.auth import create_user


@pytest.fixture(scope="module")
def bom_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory.begin() as session:
        seed_reference_data(session)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(bom_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=bom_engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(bom_engine):
    factory = sessionmaker(bind=bom_engine, class_=Session, expire_on_commit=False)

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
        full_name="BOM Admin",
        email=f"bom-admin-{uuid.uuid4().hex}@example.com",
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


def _master_data(db: Session) -> tuple[int, int, int]:
    kg_id = db.scalar(select(Unit.id).where(Unit.code == "KG"))
    litre_id = db.scalar(select(Unit.id).where(Unit.code == "L"))
    packet_id = db.scalar(select(Unit.id).where(Unit.code == "PACKET"))
    flour = InventoryItem(code=f"FLOUR-{uuid.uuid4().hex[:8]}", name="Flour", category="RAW_MATERIAL", base_unit_id=kg_id)
    oil = InventoryItem(code=f"OIL-{uuid.uuid4().hex[:8]}", name="Oil", category="RAW_MATERIAL", base_unit_id=litre_id)
    pouch = InventoryItem(code=f"POUCH-{uuid.uuid4().hex[:8]}", name="Pouch", category="PACKAGING", base_unit_id=packet_id)
    carton = InventoryItem(code=f"CARTON-{uuid.uuid4().hex[:8]}", name="Carton", category="PACKAGING", base_unit_id=packet_id)
    finished = InventoryItem(code=f"FG-{uuid.uuid4().hex[:8]}", name="Murukku", category="FINISHED_GOOD", base_unit_id=packet_id)
    db.add_all([flour, oil, pouch, carton, finished])
    db.flush()
    product = Product(
        inventory_item_id=finished.id,
        sku=f"MUR-{uuid.uuid4().hex[:8]}",
        name="Murukku 200g",
        default_selling_price=Decimal("50"),
    )
    db.add(product)
    db.commit()
    return product.id, flour.id, pouch.id


def _payload(product_id: int, flour_id: int, pouch_id: int, start="2026-01-01"):
    return {
        "product_id": product_id,
        "expected_output_qty": "200",
        "effective_from": start,
        "lines": [
            {"inventory_item_id": flour_id, "line_type": "RAW_MATERIAL", "quantity_per_batch": "40"},
            {"inventory_item_id": pouch_id, "line_type": "PACKAGING", "quantity_per_batch": "200"},
        ],
    }


def test_admin_can_create_activate_and_scale_versioned_bom(client, db, admin):
    token = _token(client, admin)
    product_id, flour_id, pouch_id = _master_data(db)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/api/production/boms", headers=headers, json=_payload(product_id, flour_id, pouch_id))
    assert created.status_code == 201, created.text
    assert created.json()["version"] == 1
    assert created.json()["status"] == "DRAFT"

    activated = client.post(f"/api/production/boms/{created.json()['id']}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"

    scaled = client.get(
        f"/api/production/boms/{created.json()['id']}/scale",
        headers=headers,
        params={"batch_multiplier": "1.5"},
    )
    assert scaled.status_code == 200, scaled.text
    result = scaled.json()
    assert Decimal(result["expected_good_output_qty"]) == Decimal("300.000000")
    planned = {line["inventory_item_id"]: Decimal(line["planned_quantity"]) for line in result["lines"]}
    assert planned[flour_id] == Decimal("60.000000")
    assert planned[pouch_id] == Decimal("300.000000")


def test_bom_rejects_component_category_mismatch(client, db, admin):
    token = _token(client, admin)
    product_id, flour_id, pouch_id = _master_data(db)
    payload = _payload(product_id, flour_id, pouch_id)
    payload["lines"][0]["line_type"] = "PACKAGING"
    response = client.post("/api/production/boms", headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert response.status_code == 422


def test_active_bom_is_immutable_and_overlapping_version_rejected(client, db, admin):
    token = _token(client, admin)
    product_id, flour_id, pouch_id = _master_data(db)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post("/api/production/boms", headers=headers, json=_payload(product_id, flour_id, pouch_id))
    assert first.status_code == 201
    first_id = first.json()["id"]
    assert client.post(f"/api/production/boms/{first_id}/activate", headers=headers).status_code == 200

    changed = _payload(product_id, flour_id, pouch_id)
    changed["expected_output_qty"] = "210"
    update = client.put(f"/api/production/boms/{first_id}", headers=headers, json=changed)
    assert update.status_code == 409

    second = client.post("/api/production/boms", headers=headers, json=_payload(product_id, flour_id, pouch_id, "2026-06-01"))
    assert second.status_code == 201
    assert second.json()["version"] == 2
    conflict = client.post(f"/api/production/boms/{second.json()['id']}/activate", headers=headers)
    assert conflict.status_code == 409


def test_retirement_closes_effective_range_and_allows_next_version(client, db, admin):
    token = _token(client, admin)
    product_id, flour_id, pouch_id = _master_data(db)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post("/api/production/boms", headers=headers, json=_payload(product_id, flour_id, pouch_id))
    first_id = first.json()["id"]
    assert client.post(f"/api/production/boms/{first_id}/activate", headers=headers).status_code == 200
    retired = client.post(
        f"/api/production/boms/{first_id}/retire",
        headers=headers,
        json={"effective_to": "2026-05-31"},
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "RETIRED"
    second = client.post(
        "/api/production/boms",
        headers=headers,
        json=_payload(product_id, flour_id, pouch_id, "2026-06-01"),
    )
    assert second.status_code == 201
    assert client.post(f"/api/production/boms/{second.json()['id']}/activate", headers=headers).status_code == 200


def test_bom_write_requires_admin_or_owner(client, db):
    salesman = create_user(
        db,
        full_name="BOM Salesman",
        email=f"bom-sales-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["salesman"],
    )
    token = _token(client, salesman)
    product_id, flour_id, pouch_id = _master_data(db)
    response = client.post(
        "/api/production/boms",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(product_id, flour_id, pouch_id),
    )
    assert response.status_code == 403
