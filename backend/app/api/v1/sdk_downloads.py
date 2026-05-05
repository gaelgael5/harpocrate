"""Endpoints de téléchargement des artefacts SDK + CLI.

Discovery automatique : le module scanne `/app/releases/` (bind-mount côté
compose) et expose tout fichier dont le nom matche l'un des patterns
suivants :

- `harpocrate-{version}-py3-none-any.whl`              → SDK Python (wheel)
- `harpocrate-sdk-{version}.tar.gz`                    → SDK Python (sdist)
- `harpocrate-cli-{version}.tar.gz`                    → CLI Bash
- `harpocrate-sdk-typescript-{version}.tgz`            → SDK TypeScript (futur)
- `harpocrate-sdk-{lang}-{version}.{wheel|tar.gz|tgz}` → SDK générique (futur)

Pas d'auth — les artefacts sont publics par nature.

Endpoints :
- `GET /v1/sdk/manifest`                       → liste des artefacts trouvés
- `GET /v1/sdk/by-filename/{filename}`         → télécharge un fichier précis
- `GET /v1/sdk/{key}`                          → rétro-compat (legacy keys)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

_RELEASES_DIR = Path("/app/releases")

# ─── Patterns de discovery ────────────────────────────────────────────────────

# Chaque pattern capture la version dans son groupe nommé `version`.
# Tous les artefacts respectent le préfixe `harpocrate-` pour éviter d'exposer
# n'importe quel fichier déposé dans /app/releases/.

_PATTERN_PYTHON_WHEEL = re.compile(
    r"^harpocrate-(?P<version>\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?)"
    r"-py3-none-any\.whl$"
)
_PATTERN_PYTHON_SDIST = re.compile(
    # Accepte les 2 conventions :
    #  - `harpocrate-X.Y.Z.tar.gz`    (uv build moderne, par défaut)
    #  - `harpocrate-sdk-X.Y.Z.tar.gz` (convention historique, releases avant 0.4.0)
    r"^harpocrate(?:-sdk)?-(?P<version>\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?)\.tar\.gz$"
)
_PATTERN_CLI_BASH = re.compile(
    r"^harpocrate-cli-(?P<version>\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)?)\.tar\.gz$"
)


@dataclass(frozen=True)
class _ArtifactKind:
    pattern: re.Pattern[str]
    language: str  # 'python' | 'bash' | …
    kind: str  # 'wheel' | 'sdist' | 'cli' | …
    media_type: str
    legacy_key: str | None  # ancien identifiant (pour rétro-compat avec frontend pré-glob)


_ARTIFACT_KINDS: tuple[_ArtifactKind, ...] = (
    _ArtifactKind(
        _PATTERN_PYTHON_WHEEL, "python", "wheel", "application/octet-stream", "python-wheel"
    ),
    _ArtifactKind(_PATTERN_PYTHON_SDIST, "python", "sdist", "application/gzip", "python-sdist"),
    _ArtifactKind(_PATTERN_CLI_BASH, "bash", "cli", "application/gzip", "cli-bash"),
)


# ─── Discovery ────────────────────────────────────────────────────────────────


def _natural_version_key(version: str) -> tuple[int, ...]:
    """Tri naturel par version : 0.10.0 > 0.9.0. Tolère les suffixes (rc, beta...)."""
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _discover_artifacts() -> list[dict[str, object]]:
    """Scanne le dossier releases/ et retourne la liste des artefacts détectés.

    Pour chaque kind (python wheel, python sdist, cli bash) on inclut TOUTES
    les versions présentes (le frontend choisira laquelle afficher en haut).
    """
    if not _RELEASES_DIR.is_dir():
        return []

    items: list[dict[str, object]] = []
    for entry in sorted(_RELEASES_DIR.iterdir()):
        if not entry.is_file():
            continue
        for kind in _ARTIFACT_KINDS:
            m = kind.pattern.match(entry.name)
            if not m:
                continue
            version = m.group("version")
            items.append(
                {
                    "key": f"{kind.language}-{kind.kind}-{version}",
                    "language": kind.language,
                    "kind": kind.kind,
                    "version": version,
                    "filename": entry.name,
                    "media_type": kind.media_type,
                    "url": f"/v1/sdk/by-filename/{entry.name}",
                    "available": "true",
                    "size_bytes": entry.stat().st_size,
                }
            )
            break  # un fichier ne match qu'un seul kind

    items.sort(
        key=lambda a: (
            str(a["language"]),
            str(a["kind"]),
            _natural_version_key(str(a["version"])),
        ),
        reverse=False,
    )
    return items


def _legacy_artifacts() -> list[dict[str, str]]:
    """Rétro-compat : un item par legacy_key, pointant sur la version la plus récente.

    Garantit que le frontend actuel (qui consomme `key`, `filename`, `media_type`,
    `url`, `available`) continue de fonctionner sans modification.
    """
    discovered = _discover_artifacts()
    by_kind: dict[str, dict[str, object]] = {}
    for kind in _ARTIFACT_KINDS:
        if kind.legacy_key is None:
            continue
        candidates = [
            d for d in discovered if d["language"] == kind.language and d["kind"] == kind.kind
        ]
        if candidates:
            latest = max(candidates, key=lambda a: _natural_version_key(str(a["version"])))
            by_kind[kind.legacy_key] = latest

    legacy: list[dict[str, str]] = []
    for legacy_key, kind in [(k.legacy_key, k) for k in _ARTIFACT_KINDS if k.legacy_key]:
        if legacy_key in by_kind:
            a = by_kind[legacy_key]
            legacy.append(
                {
                    "key": legacy_key,
                    "filename": str(a["filename"]),
                    "media_type": str(a["media_type"]),
                    "url": f"/v1/sdk/{legacy_key}",
                    "available": "true",
                }
            )
        else:
            legacy.append(
                {
                    "key": legacy_key,
                    "filename": "",
                    "media_type": kind.media_type,
                    "url": f"/v1/sdk/{legacy_key}",
                    "available": "false",
                }
            )
    return legacy


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/sdk/manifest", include_in_schema=True)
async def sdk_manifest() -> JSONResponse:
    """Liste les artefacts SDK + CLI disponibles.

    Retourne :
    - `artifacts` : liste rétro-compat (un item par legacy_key, filename de la
      version la plus récente trouvée)
    - `all_versions` : liste exhaustive — toutes les versions de chaque kind,
      avec champs `language`, `kind`, `version`, `filename`, `url`, `media_type`.
      Utilisé par la nouvelle UI Intégration (sélecteur de SDK + version).
    """
    return JSONResponse(
        {
            "artifacts": _legacy_artifacts(),
            "all_versions": _discover_artifacts(),
        }
    )


_SAFE_FILENAME = re.compile(r"^harpocrate-[a-zA-Z0-9._+-]+\.(?:whl|tar\.gz|tgz)$")


@router.get("/sdk/by-filename/{filename}", include_in_schema=True)
async def download_by_filename(filename: str) -> FileResponse:
    """Télécharge un artefact par son nom de fichier exact.

    Sécurité : le nom doit matcher `_SAFE_FILENAME` (préfixe `harpocrate-`,
    extensions whitelistées). Refuse tout path traversal (`..`, `/`).
    """
    if "/" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_filename"},
        )
    if not _SAFE_FILENAME.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_filename",
                "message": "Filename does not match allowed pattern",
            },
        )

    # Vérifier que le fichier matche un des kinds supportés (sécurité : ne sert
    # pas n'importe quel fichier dans releases/, juste les artefacts officiels).
    matched_kind: _ArtifactKind | None = None
    for kind in _ARTIFACT_KINDS:
        if kind.pattern.match(filename):
            matched_kind = kind
            break
    if matched_kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_artifact"},
        )

    path = _RELEASES_DIR / filename
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "artifact_not_present",
                "message": (
                    f"L'artefact {filename} n'est pas disponible sur ce déploiement. "
                    "Vérifier le bind-mount ./releases:/app/releases:ro."
                ),
            },
        )

    return FileResponse(
        path=str(path),
        media_type=matched_kind.media_type,
        filename=filename,
    )


@router.get("/sdk/{key}", include_in_schema=True)
async def download_sdk_artifact(key: str) -> FileResponse:
    """Rétro-compat : ancien endpoint par legacy_key (`python-wheel`, `python-sdist`, `cli-bash`).

    Sert la version la plus récente trouvée par discovery. Préférer
    `/sdk/by-filename/{filename}` pour les nouveaux clients.
    """
    matched_kind: _ArtifactKind | None = None
    for k in _ARTIFACT_KINDS:
        if k.legacy_key == key:
            matched_kind = k
            break
    if matched_kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_artifact", "message": f"Unknown SDK key: {key}"},
        )

    discovered = _discover_artifacts()
    candidates = [
        d
        for d in discovered
        if d["language"] == matched_kind.language and d["kind"] == matched_kind.kind
    ]
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "artifact_not_present",
                "message": (
                    f"Aucun artefact trouvé pour {key}. "
                    "Vérifier le bind-mount ./releases:/app/releases:ro."
                ),
            },
        )
    latest = max(candidates, key=lambda a: _natural_version_key(str(a["version"])))
    filename = str(latest["filename"])
    path = _RELEASES_DIR / filename
    return FileResponse(
        path=str(path),
        media_type=matched_kind.media_type,
        filename=filename,
    )
