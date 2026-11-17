import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import Principal, require_roles
from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_refresh_token
from app.db.base import Base
from app.db.seed_reference_data import seed_reference_data
from app.db.session import get_db
from app.main import app
from app.models import AuthRefreshToken, AuthSession, User
from app.services.auth import create_user, rotate_refresh_token


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
        email=f"iam-{uuid.uuid4().hex}@example.com",
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

    rotated = client.post("/api/auth/refresh", headers=origin)
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
    rotated = client.post("/api/auth/refresh", headers=origin)
    assert rotated.status_code == 200

    client.cookies.set("batchflow_refresh", old_cookie, path="/api/auth/refresh")
    reuse = client.post("/api/auth/refresh", headers=origin)
    assert reuse.status_code == 401
    assert "reuse detected" in reuse.json()["detail"]

    client.cookies.set(
        "batchflow_refresh",
        rotated.cookies.get("batchflow_refresh"),
        path="/api/auth/refresh",
    )
    successor_rejected = client.post("/api/auth/refresh", headers=origin)
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
    # Access JWTs remain valid until their 15-minute expiry; refresh capability is revoked.
    still_valid = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert still_valid.status_code == 200
    client.cookies.set(
        "batchflow_refresh",
        login.cookies.get("batchflow_refresh"),
        path="/api/auth/refresh",
    )
    rejected = client.post("/api/auth/refresh", headers=origin)
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


def _signed_test_token(secret: str, **claim_overrides: object) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": "123",
        "sid": str(uuid.uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    claims.update(claim_overrides)
    return jwt.encode(
        claims,
        secret,
        algorithm="HS256",
        headers={"kid": settings.jwt_key_id},
    )


def test_access_token_validation_rejects_invalid_claims_and_signatures() -> None:
    settings = get_settings()
    valid = create_access_token(123, uuid.uuid4())
    assert decode_access_token(valid)["sub"] == "123"

    invalid_tokens = [
        "not-a-jwt",
        _signed_test_token(settings.jwt_secret_key, exp=datetime.now(UTC) - timedelta(seconds=1)),
        _signed_test_token(settings.jwt_secret_key, iss="wrong-issuer"),
        _signed_test_token(settings.jwt_secret_key, aud="wrong-audience"),
        _signed_test_token("different-signing-secret-that-is-long-enough"),
    ]
    for token in invalid_tokens:
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(token)

    unsupported_algorithm = jwt.encode(
        {
            "sub": "123",
            "sid": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "jti": str(uuid.uuid4()),
            "typ": "access",
        },
        settings.jwt_secret_key,
        algorithm="HS384",
        headers={"kid": settings.jwt_key_id},
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(unsupported_algorithm)


def test_refresh_token_hash_is_persisted_but_raw_token_is_not(
    client: TestClient,
    db: Session,
    user: User,
) -> None:
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert login.status_code == 200
    raw_refresh = login.cookies.get("batchflow_refresh")
    session_id = uuid.UUID(decode_access_token(login.json()["access_token"])["sid"])
    stored_hash = db.scalar(
        select(AuthRefreshToken.token_hash).where(AuthRefreshToken.session_id == session_id)
    )
    assert stored_hash == hash_refresh_token(raw_refresh)
    assert raw_refresh not in stored_hash


def test_inactive_user_cannot_login_or_refresh(
    client: TestClient,
    db: Session,
    user: User,
) -> None:
    origin = {"Origin": "http://localhost:5173"}
    email = user.email
    login = client.post(
        "/api/auth/login",
        headers=origin,
        json={"email": email, "password": "A-Strong-Test-Password-123!"},
    )
    assert login.status_code == 200
    access = login.json()["access_token"]
    claims = decode_access_token(access)

    user.is_active = False
    db.commit()

    refresh = client.post("/api/auth/refresh", headers=origin)
    assert refresh.status_code == 401
    session = db.get(AuthSession, uuid.UUID(claims["sid"]))
    assert session is not None
    assert session.revoked_at is not None
    assert session.revoke_reason == "inactive_user"
    db.rollback()

    login_again = client.post(
        "/api/auth/login",
        headers=origin,
        json={"email": email, "password": "A-Strong-Test-Password-123!"},
    )
    assert login_again.status_code == 403


def test_concurrent_refresh_requests_rotate_only_once(
    client: TestClient,
    auth_engine,
    user: User,
) -> None:
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"email": user.email, "password": "A-Strong-Test-Password-123!"},
    )
    assert login.status_code == 200
    raw_refresh = login.cookies.get("batchflow_refresh")
    barrier = Barrier(2)
    factory = sessionmaker(bind=auth_engine, class_=Session, expire_on_commit=False)

    def attempt_refresh() -> int:
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                rotate_refresh_token(session, raw_refresh)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt_refresh(), range(2)))

    assert sorted(outcomes) == [200, 401]


def test_cors_preflight_allows_configured_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/api/auth/refresh",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
