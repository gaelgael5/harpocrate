"""Placeholder app — Task 8 finalizes lifespan and full router setup."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import config_public, health

app = FastAPI(title="Harpocrate", version="0.1.0")
app.include_router(health.router, prefix="/v1")
app.include_router(config_public.router, prefix="/v1")
