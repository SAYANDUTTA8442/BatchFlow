import uuid
from collections.abc import Generator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import Principal, require_roles
from app.core.config import get_settings
from app.db.base import Base
from app.db.seed_reference_data import seed_reference_data
from app.db.session import get_db
from app.main import app
from app.models import User
from app.services.auth import create_user


@pytest.fixture(scope="module")
def auth_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory.begin() as session:
        seed_reference_data(session)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(auth_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=auth_engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(db: Session):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user(db: Session) -> User:
    return create_user(
        db,
        full_name="IAM Test User",
        email=f"iam-{uuid.uuid4().hex}@example.test",
        password="A-Strong-Test-Password-123!",
        role_codes=["admin"],
    )


def test_login_me_and_refresh_rotation(client: TestClient, user: User) -> None:
    origin = {"Origin": "http://localhost:5173"}
    login = client.post(
        "/api/auth/login", headers=origin,
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert login.json()["user"]["roles"] == ["admin"]
    assert "batchflow_refresh" in login.cookies
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "batchflow_refresh" not in str(login.json())

    access = login.json()["access_token"]
    me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == user.email

    rotated = client.post("/api/auth/refresh", headers=origin, cookies=login.cookies)
    assert rotated.status_code == 200
    assert rotated.json()["access_token"] != access
    assert rotated.cookies.get("batchflow_refresh") != login.cookies.get("batchflow_refresh")


def test_consumed_refresh_token_reuse_revokes_family(client: TestClient, user: User) -> None:
    origin = {"Origin": "http://localhost:5173"}
    login = client.post(
        "/api/auth/login", headers=origin,
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    old_cookie = login.cookies.get("batchflow_refresh")
    rotated = client.post("/api/auth/refresh", headers=origin, cookies=login.cookies)
    assert rotated.status_code == 200

    reuse = client.post(
        "/api/auth/refresh", headers=origin,
        cookies={"batchflow_refresh": old_cookie},
    )
    assert reuse.status_code == 401
    assert "reuse detected" in reuse.json()["detail"]

    successor_rejected = client.post(
        "/api/auth/refresh", headers=origin, cookies=rotated.cookies,
    )
    assert successor_rejected.status_code == 401


def test_logout_revokes_refresh_family(client: TestClient, user: User) -> None:
    origin = {"Origin": "http://localhost:5173"}
    login = client.post(
        "/api/auth/login", headers=origin,
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    access = login.json()["access_token"]
    logout = client.post(
        "/api/auth/logout",
        headers={**origin, "Authorization": f"Bearer {access}"},
    )
    assert logout.status_code == 204
    assert "batchflow_refresh" in logout.headers.get("set-cookie", "")
    rejected = client.post("/api/auth/refresh", headers=origin, cookies=login.cookies)
    assert rejected.status_code == 401


def test_origin_and_password_validation(client: TestClient, user: User) -> None:
    bad_origin = client.post(
        "/api/auth/login", headers={"Origin": "https://attacker.example"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert bad_origin.status_code == 403
    wrong_password = client.post(
        "/api/auth/login", headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "wrong-password"},
    )
    assert wrong_password.status_code == 401


def test_role_policy_denies_missing_role(user: User) -> None:
    principal = Principal(user=user, session_id=uuid.uuid4(), roles=frozenset({"admin"}))
    with pytest.raises(HTTPException) as error:
        require_roles("owner")(principal)
    assert error.value.status_code == 403
