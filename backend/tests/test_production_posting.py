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
from app.models import (
    AuditEvent,
    InventoryBalance,
    InventoryItem,
    InventoryLocation,
    ProductionCostLine,
    ProductionRun,
    ProductionRunOutput,
    StockMovement,
    Supplier,
    Unit,
    User,
)
from app.services.auth import create_user


@pytest.fixture(scope="module")
def posting_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory.begin() as session:
        seed_reference_data(session)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(posting_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=posting_engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(posting_engine):
    factory = sessionmaker(bind=posting_engine, class_=Session, expire_on_commit=False)

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
        full_name="Posting Admin",
        email=f"posting-admin-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["admin"],
    )


@pytest.fixture
def supervisor(db: Session) -> User:
    return create_user(
        db,
        full_name="Posting Supervisor",
        email=f"posting-supervisor-{uuid.uuid4().hex}@example.com",
        password="A-Strong-Test-Password-123!",
        role_codes=["production"],
    )


def _token(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _fixture_data(db: Session):
    unit_ids = {
        code: db.scalar(select(Unit.id).where(Unit.code == code))
        for code in ("KG", "L", "PCS", "CARTON", "PACKET")
    }
    flour = InventoryItem(code=f"FLOUR-{uuid.uuid4().hex[:8]}", name="Flour", category="RAW_MATERIAL", base_unit_id=unit_ids["KG"])
    oil = InventoryItem(code=f"OIL-{uuid.uuid4().hex[:8]}", name="Oil", category="RAW_MATERIAL", base_unit_id=unit_ids["L"])
    spice = InventoryItem(code=f"SPICE-{uuid.uuid4().hex[:8]}", name="Spice mix", category="RAW_MATERIAL", base_unit_id=unit_ids["KG"])
    pouch = InventoryItem(code=f"POUCH-{uuid.uuid4().hex[:8]}", name="200g pouch", category="PACKAGING", base_unit_id=unit_ids["PCS"])
    carton = InventoryItem(code=f"CARTON-{uuid.uuid4().hex[:8]}", name="Carton", category="PACKAGING", base_unit_id=unit_ids["CARTON"])
    finished = InventoryItem(code=f"FG-{uuid.uuid4().hex[:8]}", name="Murukku", category="FINISHED_GOOD", base_unit_id=unit_ids["PACKET"])
    db.add_all([flour, oil, spice, pouch, carton, finished])
    db.flush()
    from app.models import Product

    product = Product(
        inventory_item_id=finished.id,
        sku=f"MUR-{uuid.uuid4().hex[:8]}",
        name="Murukku 200g",
        default_selling_price=Decimal("50"),
    )
    supplier = Supplier(
        supplier_code=f"SUP-{uuid.uuid4().hex[:8]}",
        name="Benchmark Supplier",
        state_code="33",
        is_active=True,
    )
    db.add_all([product, supplier])
    db.commit()
    return product, supplier, [flour, oil, spice, pouch, carton], finished


def _create_run(client, admin, supervisor, product, components):
    admin_token = _token(client, admin)
    response = client.post(
        "/api/production/boms",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "product_id": product.id,
            "expected_output_qty": "200",
            "effective_from": "2026-01-01",
            "lines": [
                {"inventory_item_id": components[0].id, "line_type": "RAW_MATERIAL", "quantity_per_batch": "40"},
                {"inventory_item_id": components[1].id, "line_type": "RAW_MATERIAL", "quantity_per_batch": "10"},
                {"inventory_item_id": components[2].id, "line_type": "RAW_MATERIAL", "quantity_per_batch": "1.2"},
                {"inventory_item_id": components[3].id, "line_type": "PACKAGING", "quantity_per_batch": "200"},
                {"inventory_item_id": components[4].id, "line_type": "PACKAGING", "quantity_per_batch": "10"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    bom_id = response.json()["id"]
    activated = client.post(f"/api/production/boms/{bom_id}/activate", headers={"Authorization": f"Bearer {admin_token}"})
    assert activated.status_code == 200, activated.text
    production_token = _token(client, supervisor)
    created = client.post(
        "/api/production/runs",
        headers={"Authorization": f"Bearer {production_token}"},
        json={"bom_id": bom_id, "production_date": "2026-11-17", "batch_multiplier": "1"},
    )
    assert created.status_code == 201, created.text
    return created.json(), admin_token, production_token


def _open_stock(client, admin_token, components, quantities, costs, key):
    # The seeded factory location is the only MVP inventory location.
    location = client.get("/api/master-data/locations", headers={"Authorization": f"Bearer {admin_token}"})
    if location.status_code == 200:
        location_id_value = next(x["id"] for x in location.json() if x["code"] == "FACTORY-01")
    else:
        raise AssertionError(location.text)
    lines = [
        {
            "inventory_item_id": item.id,
            "inventory_location_id": location_id_value,
            "quantity_delta": quantity,
            "unit_cost": cost,
        }
        for item, quantity, cost in zip(components, quantities, costs, strict=True)
        if Decimal(quantity) > 0
    ]
    draft = client.post(
        "/api/inventory/adjustments",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"adjustment_number": f"OPEN-{uuid.uuid4().hex[:10]}", "reason": "OPENING_BALANCE", "lines": lines},
    )
    assert draft.status_code == 201, draft.text
    posted = client.post(
        f"/api/inventory/adjustments/{draft.json()['id']}/post",
        headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": key},
    )
    assert posted.status_code == 200, posted.text


def _actual_payload(run, actuals, output="188"):
    return {
        "actual_lines": [
            {
                "line_id": line["id"],
                "actual_qty": actuals[line["inventory_item_id"]][0],
                "damaged_qty": actuals[line["inventory_item_id"]][1],
            }
            for line in run["lines"]
        ],
        "actual_good_output_qty": output,
        "cost_lines": [
            {"cost_type": "LABOUR", "description": "Production labour", "amount": "1200.00"},
            {"cost_type": "ENERGY", "description": "Gas and power", "amount": "600.00"},
        ],
        "wastage_note": "Six damaged pouches; eight packets remain loose.",
    }


def test_benchmark_production_posting_updates_ledger_wac_variances_and_cost(
    client, db, admin, supervisor
):
    product, supplier, components, finished = _fixture_data(db)
    run, admin_token, production_token = _create_run(client, admin, supervisor, product, components)

    _open_stock(
        client, admin_token, components,
        ["100", "30", "5", "500", "30"],
        ["42", "140", "200", "2.50", "15"],
        "production-opening-stock",
    )
    receipt = client.post(
        "/api/inventory/purchase-receipts",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "receipt_number": f"FLOUR-RECEIPT-{uuid.uuid4().hex[:8]}",
            "supplier_id": supplier.id,
            "received_at": "2026-11-17T09:00:00+05:30",
            "lines": [{
                "inventory_item_id": components[0].id,
                "inventory_location_id": db.scalar(select(InventoryLocation.id).where(InventoryLocation.code == "FACTORY-01")),
                "quantity_received": "60",
                "unit_cost": "45",
            }],
        },
    )
    assert receipt.status_code == 201, receipt.text
    receipt_post = client.post(
        f"/api/inventory/purchase-receipts/{receipt.json()['id']}/post",
        headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": "flour-receipt-post"},
    )
    assert receipt_post.status_code == 200, receipt_post.text

    actuals = {
        components[0].id: ("40", "0"),
        components[1].id: ("10.5", "0"),
        components[2].id: ("1.2", "0"),
        components[3].id: ("194", "6"),
        components[4].id: ("9", "0"),
    }
    payload = _actual_payload(run, actuals)
    headers = {"Authorization": f"Bearer {production_token}", "Idempotency-Key": "murukku-run-post"}
    posted = client.post(f"/api/production/runs/{run['id']}/post", headers=headers, json=payload)
    assert posted.status_code == 200, posted.text
    result = posted.json()

    assert result["status"] == "POSTED"
    assert Decimal(result["actual_good_output_qty"]) == Decimal("188.000000")
    assert Decimal(result["yield_variance_percent"]) == Decimal("-6.0000")
    assert result["yield_variance_alert"] is True
    assert Decimal(result["total_run_cost"]) == Decimal("5855.00")
    assert Decimal(result["cost_per_good_unit"]) == Decimal("31.143617")
    assert len(result["outputs"]) == 1
    assert len(result["cost_lines"]) == 2

    line_by_item = {line["inventory_item_id"]: line for line in result["lines"]}
    assert Decimal(line_by_item[components[1].id]["variance_percent"]) == Decimal("5.0000")
    assert line_by_item[components[1].id]["variance_alert"] is True
    assert Decimal(line_by_item[components[3].id]["actual_qty"]) == Decimal("194.000000")
    assert Decimal(line_by_item[components[3].id]["damaged_qty"]) == Decimal("6.000000")
    assert Decimal(line_by_item[components[3].id]["line_cost"]) == Decimal("485.00")

    balances = client.get("/api/inventory/balances", headers={"Authorization": f"Bearer {admin_token}"})
    by_item = {row["inventory_item_id"]: row for row in balances.json()}
    expected_closing = {
        components[0].id: Decimal("120"),
        components[1].id: Decimal("19.5"),
        components[2].id: Decimal("3.8"),
        components[3].id: Decimal("306"),
        components[4].id: Decimal("21"),
        finished.id: Decimal("188"),
    }
    for item_id, expected in expected_closing.items():
        assert Decimal(by_item[item_id]["on_hand_qty"]) == expected

    flour_value = by_item[components[0].id]
    assert Decimal(flour_value["average_unit_cost"]) == Decimal("43.125000")
    finished_value = by_item[finished.id]
    assert Decimal(finished_value["inventory_value"]) == Decimal("5855.00")
    assert Decimal(finished_value["average_unit_cost"]) == Decimal("31.143617")

    movements = db.scalars(
        select(StockMovement).where(
            StockMovement.production_run_line_id.is_not(None)
            | StockMovement.production_run_output_id.is_not(None)
        )
    ).all()
    assert len(movements) == 6
    assert sum(1 for movement in movements if movement.movement_type == "PRODUCTION_ISSUE") == 5
    assert sum(1 for movement in movements if movement.movement_type == "PRODUCTION_OUTPUT") == 1
    assert db.scalar(select(ProductionRunOutput.id).where(ProductionRunOutput.production_run_id == run["id"])) is not None
    assert len(db.scalars(select(ProductionCostLine).where(ProductionCostLine.production_run_id == run["id"])).all()) == 2
    assert db.scalar(select(AuditEvent.id).where(AuditEvent.entity_type == "PRODUCTION_RUN", AuditEvent.entity_id == run["id"], AuditEvent.action == "PRODUCTION_RUN_POSTED")) is not None

    replay = client.post(f"/api/production/runs/{run['id']}/post", headers=headers, json=payload)
    assert replay.status_code == 200
    assert replay.json() == result
    conflict = client.post(
        f"/api/production/runs/{run['id']}/post",
        headers={"Authorization": f"Bearer {production_token}", "Idempotency-Key": "different-key"},
        json=payload,
    )
    assert conflict.status_code == 409

    reconciliation = client.get("/api/inventory/reconciliation", headers={"Authorization": f"Bearer {admin_token}"})
    assert reconciliation.status_code == 200
    assert reconciliation.json()["is_reconciled"] is True


def test_failed_production_post_rolls_back_earlier_component_issue(
    client, db, admin, supervisor
):
    product, _, components, _ = _fixture_data(db)
    run, admin_token, production_token = _create_run(client, admin, supervisor, product, components)
    _open_stock(
        client, admin_token, components,
        ["100", "1", "5", "500", "30"],
        ["42", "140", "200", "2.50", "15"],
        "production-rollback-opening",
    )
    payload = _actual_payload(
        run,
        {
            components[0].id: ("40", "0"),
            components[1].id: ("10.5", "0"),
            components[2].id: ("1.2", "0"),
            components[3].id: ("194", "6"),
            components[4].id: ("9", "0"),
        },
    )
    response = client.post(
        f"/api/production/runs/{run['id']}/post",
        headers={"Authorization": f"Bearer {production_token}", "Idempotency-Key": "rollback-run"},
        json=payload,
    )
    assert response.status_code == 409
    assert db.get(ProductionRun, run["id"]).status == "DRAFT"
    run_line_ids = [line["id"] for line in run["lines"]]
    assert db.scalar(select(StockMovement.id).where(
        StockMovement.production_run_line_id.in_(run_line_ids)
    )) is None
    assert db.scalar(select(ProductionRunOutput.id).where(ProductionRunOutput.production_run_id == run["id"])) is None
    assert db.scalar(select(ProductionCostLine.id).where(ProductionCostLine.production_run_id == run["id"])) is None
    flour_balance = db.scalar(select(InventoryBalance).where(InventoryBalance.inventory_item_id == components[0].id))
    assert Decimal(flour_balance.on_hand_qty) == Decimal("100.000000")


def test_production_post_rejects_invalid_precision_and_non_production_actor(
    client, db, admin, supervisor
):
    product, _, components, _ = _fixture_data(db)
    run, admin_token, production_token = _create_run(client, admin, supervisor, product, components)
    payload = _actual_payload(
        run,
        {
            components[0].id: ("40", "0"),
            components[1].id: ("10.5001", "0"),
            components[2].id: ("1.2", "0"),
            components[3].id: ("194", "6"),
            components[4].id: ("9", "0"),
        },
    )
    invalid = client.post(
        f"/api/production/runs/{run['id']}/post",
        headers={"Authorization": f"Bearer {production_token}", "Idempotency-Key": "bad-precision"},
        json=payload,
    )
    assert invalid.status_code == 422
    unauthorized = client.post(
        f"/api/production/runs/{run['id']}/post",
        headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": "admin-production-post"},
        json=_actual_payload(
            run,
            {
                components[0].id: ("40", "0"),
                components[1].id: ("10.5", "0"),
                components[2].id: ("1.2", "0"),
                components[3].id: ("194", "6"),
                components[4].id: ("9", "0"),
            },
        ),
    )
    assert unauthorized.status_code == 403
