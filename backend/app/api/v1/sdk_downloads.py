"""Endpoints SDK + CLI : manifest, téléchargement de binaires, doc markdown.

Source de vérité : `/app/releases/index.json` (bind-mount depuis le repo Git).

Layout attendu sur disque :
- `/app/releases/index.json`        — catalogue complet (cf. schéma plus bas)
- `/app/releases/<filename>`        — artefacts binaires (.whl, .tar.gz)
- `/app/releases/docs/<filename>`   — documentation markdown par SDK et par langue

Endpoints :
- `GET /v1/sdk/manifest`                    → manifest enrichi (catalogue + dispo physique)
- `GET /v1/sdk/by-filename/{filename}`      → télécharge un binaire SDK
- `GET /v1/sdk/doc/{filename}`              → sert un fichier markdown
- `GET /v1/sdk/{key}`                       → legacy keys (python-wheel, python-sdist, cli-bash)

Schéma `index.json` (v1.0) :
{
  "schema_version": "1.0",
  "sdks": [
    {
      "id": "python",                        // identifiant unique
      "name": "Python",                      // nom affiché
      "icon": "🐍",                          // emoji
      "status": "available" | "planned",     // si planned → pas de bouton download
      "artifacts": [
        { "kind": "wheel"|"sdist"|"cli"|...,
          "version": "0.4.0",
          "filename": "harpocrate-0.4.0-py3-none-any.whl" }
      ],
      "docs": { "fr": "python-fr.md", "en": "python-en.md" }
    }
  ]
}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

router = APIRouter()

_RELEASES_DIR = Path("/app/releases")
_DOCS_SUBDIR = "docs"
_INDEX_FILENAME = "index.json"

# ─── Mapping kind → (media_type, legacy_key) ─────────────────────────────────
# legacy_key sert uniquement aux endpoints rétrocompat /v1/sdk/{key}.

_KIND_META: dict[str, dict[str, str | None]] = {
    "wheel": {"media_type": "application/octet-stream", "legacy_key": "python-wheel"},
    "sdist": {"media_type": "application/gzip", "legacy_key": "python-sdist"},
    "cli": {"media_type": "application/gzip", "legacy_key": "cli-bash"},
}
_DEFAULT_MEDIA_TYPE = "application/octet-stream"


# ─── Lecture index.json ──────────────────────────────────────────────────────


def _load_index() -> dict[str, Any]:
    """Charge `index.json` depuis le bind mount. Retourne un manifest vide si absent.

    Vide plutôt que 500 pour ne pas casser la page Intégration sur un déploiement
    qui n'a pas encore récupéré l'index (le frontend affichera juste "aucun SDK").
    """
    path = _RELEASES_DIR / _INDEX_FILENAME
    if not path.is_file():
        return {"schema_version": "1.0", "sdks": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "sdks": []}


def _annotate_sdks(raw_sdks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrichit chaque artefact avec `available` (présence physique) et `media_type`."""
    annotated: list[dict[str, Any]] = []
    for sdk in raw_sdks:
        artifacts_in: list[dict[str, Any]] = list(sdk.get("artifacts") or [])
        artifacts_out: list[dict[str, Any]] = []
        for art in artifacts_in:
            filename = str(art.get("filename") or "")
            kind = str(art.get("kind") or "")
            file_path = _RELEASES_DIR / filename
            available = bool(filename) and file_path.is_file()
            kind_meta = _KIND_META.get(kind, {})
            artifacts_out.append(
                {
                    "kind": kind,
                    "version": art.get("version"),
                    "filename": filename,
                    "media_type": kind_meta.get("media_type", _DEFAULT_MEDIA_TYPE),
                    "url": f"/v1/sdk/by-filename/{filename}" if filename else "",
                    "available": available,
                    "size_bytes": file_path.stat().st_size if available else None,
                }
            )

        docs_in: dict[str, Any] = dict(sdk.get("docs") or {})
        docs_out: dict[str, dict[str, Any]] = {}
        for lang, doc_filename in docs_in.items():
            doc_path = _RELEASES_DIR / _DOCS_SUBDIR / str(doc_filename)
            docs_out[str(lang)] = {
                "filename": str(doc_filename),
                "url": f"/v1/sdk/doc/{doc_filename}",
                "available": doc_path.is_file(),
            }

        annotated.append(
            {
                "id": sdk.get("id"),
                "name": sdk.get("name"),
                "icon": sdk.get("icon"),
                "status": sdk.get("status", "planned"),
                "artifacts": artifacts_out,
                "docs": docs_out,
            }
        )
    return annotated


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/sdk/manifest", include_in_schema=True)
async def sdk_manifest() -> JSONResponse:
    """Manifest complet : catalogue SDKs depuis index.json + flag `available` par
    artefact (et par doc) selon la présence physique en local."""
    idx = _load_index()
    sdks = _annotate_sdks(list(idx.get("sdks") or []))
    return JSONResponse(
        {
            "schema_version": idx.get("schema_version", "1.0"),
            "sdks": sdks,
        }
    )


_SAFE_BINARY_FILENAME = re.compile(r"^[A-Za-z0-9._+-]+\.(?:whl|tar\.gz|tgz|zip)$")
_SAFE_DOC_FILENAME = re.compile(r"^[A-Za-z0-9._+-]+\.md$")


def _validate_filename(filename: str, *, pattern: re.Pattern[str]) -> None:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_filename"},
        )
    if not pattern.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_filename"},
        )


@router.get("/sdk/by-filename/{filename}", include_in_schema=True)
async def download_by_filename(filename: str) -> FileResponse:
    """Télécharge un artefact binaire listé dans index.json."""
    _validate_filename(filename, pattern=_SAFE_BINARY_FILENAME)

    # Le fichier doit être référencé par index.json (sinon on ne sert pas n'importe quoi)
    idx = _load_index()
    declared_filenames: set[str] = set()
    declared_kind: dict[str, str] = {}
    for sdk in idx.get("sdks") or []:
        for art in sdk.get("artifacts") or []:
            fn = str(art.get("filename") or "")
            if fn:
                declared_filenames.add(fn)
                declared_kind[fn] = str(art.get("kind") or "")
    if filename not in declared_filenames:
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
                    f"L'artefact {filename} est listé dans index.json mais absent du "
                    "déploiement. Relancer le script de refresh sur le serveur."
                ),
            },
        )

    kind = declared_kind.get(filename, "")
    media_type = _KIND_META.get(kind, {}).get("media_type", _DEFAULT_MEDIA_TYPE)
    return FileResponse(
        path=str(path), media_type=media_type or _DEFAULT_MEDIA_TYPE, filename=filename
    )


@router.get("/sdk/doc/{filename}", include_in_schema=True)
async def download_doc(filename: str) -> PlainTextResponse:
    """Sert le contenu d'un fichier markdown listé dans index.json (`docs[lang]`)."""
    _validate_filename(filename, pattern=_SAFE_DOC_FILENAME)

    # Vérifier que ce nom est bien référencé par au moins un SDK (sinon 404)
    idx = _load_index()
    declared_docs: set[str] = set()
    for sdk in idx.get("sdks") or []:
        for doc_filename in (sdk.get("docs") or {}).values():
            if doc_filename:
                declared_docs.add(str(doc_filename))
    if filename not in declared_docs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_doc"},
        )

    path = _RELEASES_DIR / _DOCS_SUBDIR / filename
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "doc_not_present",
                "message": (
                    f"La doc {filename} est listée dans index.json mais absente du "
                    "déploiement. Relancer le script de refresh sur le serveur."
                ),
            },
        )

    return PlainTextResponse(
        content=path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/sdk/{key}", include_in_schema=True)
async def download_sdk_artifact(key: str) -> FileResponse:
    """Rétrocompat : ancien endpoint par legacy_key (`python-wheel`, `python-sdist`, `cli-bash`).

    Sert la version la plus récente trouvée dans index.json pour le kind correspondant.
    Préférer `/v1/sdk/by-filename/{filename}` pour les nouveaux clients.
    """
    target_kind: str | None = None
    for kind, meta in _KIND_META.items():
        if meta.get("legacy_key") == key:
            target_kind = kind
            break
    if target_kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_artifact", "message": f"Unknown SDK key: {key}"},
        )

    idx = _load_index()
    candidates: list[dict[str, Any]] = []
    for sdk in idx.get("sdks") or []:
        for art in sdk.get("artifacts") or []:
            if str(art.get("kind") or "") == target_kind:
                fn = str(art.get("filename") or "")
                if fn and (_RELEASES_DIR / fn).is_file():
                    candidates.append(art)
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "artifact_not_present",
                "message": f"Aucun artefact disponible pour {key}.",
            },
        )

    latest = max(candidates, key=lambda a: _natural_version_key(str(a.get("version") or "0")))
    filename = str(latest["filename"])
    path = _RELEASES_DIR / filename
    media_type = _KIND_META[target_kind].get("media_type") or _DEFAULT_MEDIA_TYPE
    return FileResponse(path=str(path), media_type=media_type, filename=filename)


def _natural_version_key(version: str) -> tuple[int, ...]:
    """Tri naturel par version : 0.10.0 > 0.9.0. Tolère les suffixes (rc, beta...)."""
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
