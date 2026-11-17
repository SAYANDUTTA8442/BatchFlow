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
9. Seed roles, units, kg/g conversions and the factory location: python -m app.db.seed_reference_data
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

## Master-data endpoints

All routes require a bearer access token. Writes require the admin or owner role.

- GET /api/master-data/units and /unit-conversions
- GET, POST, PUT /api/master-data/inventory-items
- GET, POST, PUT /api/master-data/products
- GET, POST, PUT /api/master-data/customers
- GET, POST /api/master-data/suppliers
- GET, POST /api/master-data/locations

Salesmen can read only customers assigned to them. Product records must reference an active FINISHED_GOOD inventory item. Unit conversions are rejected when units have different dimensions. Master-data records do not accept opening-stock quantities; stock initialization will be implemented through the inventory ledger.

## Production BOM endpoints

BOM writes require the admin or owner role; reads are available to admin, owner, auditor and production roles.

- GET, POST /api/production/boms
- GET, PUT /api/production/boms/{bom_id}
- POST /api/production/boms/{bom_id}/activate
- POST /api/production/boms/{bom_id}/retire
- GET /api/production/boms/{bom_id}/scale?batch_multiplier=1.5

BOM versions are assigned per product under a product-row lock. Drafts can be edited; activated versions and their lines are protected by PostgreSQL triggers. Activation rejects overlapping active effective-date ranges. Component categories must match the line type, and quantities are stored in the component inventory item's base unit. Batch scaling uses Decimal and returns six-place quantities. Production posting and stock effects are not part of this BOM milestone.

## Security boundary

Refresh-token raw values are returned only as HttpOnly cookies; only SHA-256 hashes are persisted. Consumed token hashes are retained for reuse detection. Reuse revokes the entire session family. Access JWTs are stateless and may remain valid until their 15-minute expiry after logout, as specified in ADR-008.

## Transaction ownership

The request-scoped SQLAlchemy dependency closes the session but does not commit. Authentication services own explicit transaction boundaries.

## Current implementation boundary

IAM includes user/role persistence, Argon2 password hashing, bearer JWT authentication, rotating refresh sessions, Origin validation, logout and a user-provisioning CLI. Master data includes inventory items, products, customers and salesman assignments, suppliers, unit conversions and the factory location. Stock ledger posting, opening balances and versioned BOM management are implemented. Production-run posting, sales, billing, dispatch, collections and frontend workflows remain unimplemented.
