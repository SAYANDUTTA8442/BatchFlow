from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.master_data import router as master_data_router
from app.core.config import get_settings


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(settings.origin_allowlist),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(master_data_router)
