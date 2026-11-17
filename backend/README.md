# BatchFlow Backend

FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL.

## Requirements

- Python 3.12+
- Docker Engine with the Compose plugin

## Local setup

From the repository root:

1. Copy the local PostgreSQL environment template: cp .env.example .env
2. Start PostgreSQL: docker compose up -d postgres
3. Enter backend/: cd backend
4. Copy backend settings: cp .env.example .env
5. Replace JWT_SECRET_KEY with a fresh random value of at least 32 characters.
6. Create and activate a virtual environment: python -m venv .venv
7. Install dependencies: python -m pip install -e ".[dev]"
8. Apply migrations: alembic upgrade head
9. Seed roles and units: python -m app.db.seed_reference_data
10. Create the first user: python -m app.cli.create_user --name "Factory Owner" --email owner@example.com --roles owner,admin
11. Start the API: uvicorn app.main:app --reload

The API listens on http://127.0.0.1:8000. Interactive documentation is at /docs.

## Authentication endpoints

- POST /api/auth/login — verifies credentials, issues a 15-minute access JWT and sets the rotating refresh cookie.
- POST /api/auth/refresh — validates Origin and rotates the refresh token.
- POST /api/auth/logout — revokes the authenticated session family and clears the refresh cookie.
- GET /api/auth/me — returns the authenticated user's profile and roles.

Protected business routes must use get_current_principal and explicit require_roles(...) policies. Send access JWTs in the Authorization: Bearer header and keep them in frontend memory only. The refresh cookie is HttpOnly, SameSite=Lax, and scoped to /api/auth/refresh.

Production must use a unique secret-manager supplied JWT_SECRET_KEY and REFRESH_COOKIE_SECURE=true. ALLOWED_ORIGINS must list exact trusted frontend origins. JWT_KEY_ID identifies the active signing key; JWT_PREVIOUS_KEYS accepts comma-separated kid=secret entries during a bounded rotation overlap. Remove old keys after all tokens signed by them have expired.

## Security boundary

Refresh-token raw values are returned only as HttpOnly cookies; only SHA-256 hashes are persisted. Consumed token hashes are retained for reuse detection. Reuse revokes the entire session family. Access JWTs are stateless and may remain valid until their 15-minute expiry after logout, as specified in ADR-008.

## Transaction ownership

The request-scoped SQLAlchemy dependency closes the session but does not commit. Authentication services own explicit transaction boundaries.

## Current implementation boundary

IAM includes user/role persistence, Argon2 password hashing, bearer JWT authentication, rotating refresh sessions, Origin validation, logout, user provisioning CLI and PostgreSQL integration tests. Inventory, production, sales, billing, dispatch and frontend workflows remain unimplemented.
