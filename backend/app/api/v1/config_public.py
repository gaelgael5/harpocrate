"""Endpoint /v1/config/public — expose les floors et le catalogue de générateurs."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

_VERSION = "0.1.0"
_SUPPORTED_GENERATORS: list[str] = [
    "random",
    "uuid",
    "bytes",
    "passphrase",
    "rsa_keypair",
    "ssh_keypair",
    "tls_certificate",
    "bcrypt_password",
    "template",
]


@router.get("/config/public")
async def config_public() -> dict[str, object]:
    return {
        "kdf_floors": {
            "memory_kb": settings.kdf_memory_kb,
            "iterations": settings.kdf_iterations,
            "parallelism": settings.kdf_parallelism,
        },
        "rsa_minimum_key_size": settings.rsa_key_size_min,
        "passphrase_minimum_length": settings.passphrase_length_min,
        "supported_generators": _SUPPORTED_GENERATORS,
        "audit_retention_days": settings.audit_retention_days,
        "version": _VERSION,
    }
