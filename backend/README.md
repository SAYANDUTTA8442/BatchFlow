# BatchFlow Backend

FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL foundation.

## Requirements

- Python 3.12+
- Docker Engine with the Compose plugin

## Local setup

From the repository root:

1. Copy the local PostgreSQL environment template: cp .env.example .env
2. Start PostgreSQL: docker compose up -d postgres
3. Enter backend/: cd backend
4. Copy backend settings: cp .env.example .env
5. Create a virtual environment: python -m venv .venv
6. Activate it (Linux/macOS: source .venv/bin/activate; PowerShell: .venv\Scripts\Activate.ps1).
7. Install dependencies: python -m pip install -e ".[dev]"
8. Apply migrations: alembic upgrade head
9. Seed reference data: python -m app.db.seed_reference_data
10. Start the API: uvicorn app.main:app --reload

The API listens on http://127.0.0.1:8000. Interactive documentation is at /docs.

## Health endpoints

- GET /health/live — process liveness; no database required.
- GET /health/ready — runs SELECT 1 against PostgreSQL.

## Quality checks

Run from backend/: ruff check ., pytest, and alembic upgrade head.

The database dependency closes its request-scoped SQLAlchemy session but does not commit.
Application services own transaction boundaries. This foundation does not yet implement
authentication or business workflows.
