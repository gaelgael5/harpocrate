"""Endpoints de telechargement des artefacts SDK + CLI.

GET /v1/sdk/python-wheel    -> harpocrate-0.2.0-py3-none-any.whl
GET /v1/sdk/python-sdist    -> harpocrate-sdk-0.2.0.tar.gz
GET /v1/sdk/cli-bash        -> harpocrate-cli-0.1.0.tar.gz

Les fichiers sont servis depuis /app/releases/ (bind-mount cote compose).
Endpoints publics (pas d'auth) — l'utilisateur peut les telecharger pour
brancher son automation. Le contenu est public de toute facon.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

_RELEASES_DIR = Path("/app/releases")

# Mapping endpoint key → (filename sur disque, media-type, suggested filename)
_ARTIFACTS: dict[str, tuple[str, str, str]] = {
    "python-wheel": (
        "harpocrate-0.2.0-py3-none-any.whl",
        "application/octet-stream",
        "harpocrate-0.2.0-py3-none-any.whl",
    ),
    "python-sdist": (
        "harpocrate-sdk-0.2.0.tar.gz",
        "application/gzip",
        "harpocrate-sdk-0.2.0.tar.gz",
    ),
    "cli-bash": (
        "harpocrate-cli-0.1.0.tar.gz",
        "application/gzip",
        "harpocrate-cli-0.1.0.tar.gz",
    ),
}


@router.get("/sdk/manifest", include_in_schema=True)
async def sdk_manifest() -> JSONResponse:
    """Liste les artefacts disponibles avec leur URL de telechargement."""
    items: list[dict[str, str]] = []
    for key, (filename, media_type, _) in _ARTIFACTS.items():
        path = _RELEASES_DIR / filename
        items.append(
            {
                "key": key,
                "filename": filename,
                "media_type": media_type,
                "url": f"/v1/sdk/{key}",
                "available": "true" if path.is_file() else "false",
            }
        )
    return JSONResponse({"artifacts": items})


@router.get("/sdk/{key}", include_in_schema=True)
async def download_sdk_artifact(key: str) -> FileResponse:
    if key not in _ARTIFACTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_artifact", "message": f"Unknown SDK key: {key}"},
        )
    filename, media_type, suggested = _ARTIFACTS[key]
    path = _RELEASES_DIR / filename
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "artifact_not_present",
                "message": (
                    f"L'artefact {filename} n'est pas disponible sur ce deploiement. "
                    "Verifier le bind-mount ./releases:/app/releases:ro."
                ),
            },
        )
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=suggested,
    )
