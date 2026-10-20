"""Tests sdk_downloads — manifest depuis index.json + endpoint doc + by-filename."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.v1 import sdk_downloads as sd

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Crée un dossier releases/ avec index.json + quelques artefacts + docs."""
    # Artefacts
    (tmp_path / "harpocrate-0.4.0-py3-none-any.whl").write_bytes(b"wheel content")
    (tmp_path / "harpocrate-sdk-0.4.0.tar.gz").write_bytes(b"sdist content")
    (tmp_path / "harpocrate-cli-0.1.0.tar.gz").write_bytes(b"cli content")

    # Docs
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "python-fr.md").write_text("# Python\n\nDoc FR.", encoding="utf-8")
    (docs_dir / "bash-fr.md").write_text("# Bash\n\nDoc FR.", encoding="utf-8")

    # index.json
    index = {
        "schema_version": "1.0",
        "sdks": [
            {
                "id": "python",
                "name": "Python",
                "icon": "🐍",
                "status": "available",
                "artifacts": [
                    {
                        "kind": "wheel",
                        "version": "0.4.0",
                        "filename": "harpocrate-0.4.0-py3-none-any.whl",
                    },
                    {
                        "kind": "sdist",
                        "version": "0.4.0",
                        "filename": "harpocrate-sdk-0.4.0.tar.gz",
                    },
                ],
                "docs": {"fr": "python-fr.md"},
                "registry": {"name": "pypi", "package": "harpocrate", "version": "0.8.0"},
            },
            {
                "id": "bash",
                "name": "CLI Bash",
                "icon": "🖥️",
                "status": "available",
                "artifacts": [
                    {
                        "kind": "cli",
                        "version": "0.1.0",
                        "filename": "harpocrate-cli-0.1.0.tar.gz",
                    }
                ],
                "docs": {"fr": "bash-fr.md"},
            },
            {
                "id": "rust",
                "name": "Rust",
                "icon": "🦀",
                "status": "planned",
                "artifacts": [
                    {
                        "kind": "wheel",
                        "version": "0.0.0",
                        "filename": "harpocrate-rust-9.9.9.tar.gz",
                    }
                ],
                "docs": {"fr": "rust-fr.md"},
            },
        ],
    }
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")

    monkeypatch.setattr(sd, "_RELEASES_DIR", tmp_path)
    return tmp_path


# ─── _load_index ──────────────────────────────────────────────────────────────


def test_load_index_returns_empty_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sd, "_RELEASES_DIR", tmp_path)
    idx = sd._load_index()
    assert idx == {"schema_version": "1.0", "sdks": []}


def test_load_index_returns_empty_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.json").write_text("not valid json {")
    monkeypatch.setattr(sd, "_RELEASES_DIR", tmp_path)
    idx = sd._load_index()
    assert idx["sdks"] == []


def test_load_index_returns_parsed_content(fake_releases: Path) -> None:
    idx = sd._load_index()
    assert idx["schema_version"] == "1.0"
    assert len(idx["sdks"]) == 3


# ─── _annotate_sdks ───────────────────────────────────────────────────────────


def test_annotate_marks_present_artifacts_available(fake_releases: Path) -> None:
    idx = sd._load_index()
    annotated = sd._annotate_sdks(idx["sdks"])
    python = next(s for s in annotated if s["id"] == "python")
    assert all(a["available"] for a in python["artifacts"])
    assert python["artifacts"][0]["size_bytes"] is not None


def test_annotate_marks_missing_artifacts_unavailable(fake_releases: Path) -> None:
    """Le SDK Rust référence un fichier qui n'existe pas physiquement."""
    idx = sd._load_index()
    annotated = sd._annotate_sdks(idx["sdks"])
    rust = next(s for s in annotated if s["id"] == "rust")
    assert rust["artifacts"][0]["available"] is False
    assert rust["artifacts"][0]["size_bytes"] is None


def test_annotate_exposes_registry_distribution(fake_releases: Path) -> None:
    annotated = sd._annotate_sdks(sd._load_index()["sdks"])
    python = next(s for s in annotated if s["id"] == "python")
    assert python["registry"]["url"] == "https://pypi.org/project/harpocrate/"
    assert python["registry"]["install_commands"][0] == "pip install harpocrate"


def test_annotate_without_registry_is_none(fake_releases: Path) -> None:
    """Index 1.0 ou SDK distribué par fichier : `registry` vaut null, rien ne casse."""
    annotated = sd._annotate_sdks(sd._load_index()["sdks"])
    bash = next(s for s in annotated if s["id"] == "bash")
    assert bash["registry"] is None
    assert bash["artifacts"][0]["available"] is True


def test_annotate_propagates_status(fake_releases: Path) -> None:
    idx = sd._load_index()
    annotated = sd._annotate_sdks(idx["sdks"])
    statuses = {s["id"]: s["status"] for s in annotated}
    assert statuses == {"python": "available", "bash": "available", "rust": "planned"}


def test_annotate_marks_docs_availability(fake_releases: Path) -> None:
    idx = sd._load_index()
    annotated = sd._annotate_sdks(idx["sdks"])
    python = next(s for s in annotated if s["id"] == "python")
    assert python["docs"]["fr"]["available"] is True
    rust = next(s for s in annotated if s["id"] == "rust")
    assert rust["docs"]["fr"]["available"] is False  # rust-fr.md n'existe pas


# ─── Validation des filenames (sécurité) ──────────────────────────────────────


def test_validate_filename_rejects_path_traversal() -> None:
    for bad in ["../etc/passwd", "../../x.whl", "foo/bar.whl", "x..whl"]:
        with pytest.raises(HTTPException) as exc:
            sd._validate_filename(bad, pattern=sd._SAFE_BINARY_FILENAME)
        assert exc.value.status_code == 400


def test_validate_binary_filename_accepts_real_artifacts() -> None:
    # Ne lève pas
    sd._validate_filename("harpocrate-0.4.0-py3-none-any.whl", pattern=sd._SAFE_BINARY_FILENAME)
    sd._validate_filename("harpocrate-sdk-0.4.0.tar.gz", pattern=sd._SAFE_BINARY_FILENAME)


def test_validate_doc_filename_accepts_md_only() -> None:
    sd._validate_filename("python-fr.md", pattern=sd._SAFE_DOC_FILENAME)
    with pytest.raises(HTTPException):
        sd._validate_filename("python-fr.txt", pattern=sd._SAFE_DOC_FILENAME)


# ─── Routes legacy du SDK Python retirées (feature 3 de l'epic SDK) ─────────


@pytest.mark.parametrize("key", ["python-wheel", "python-sdist"])
async def test_retired_python_key_answers_gone_with_pypi_install(
    fake_releases: Path, key: str
) -> None:
    """Le wheel n'est plus servi par l'instance : 410 qui dit où installer, jamais un fichier."""
    with pytest.raises(HTTPException) as exc:
        await sd.download_sdk_artifact(key)
    assert exc.value.status_code == 410
    detail = exc.value.detail
    assert detail["error"] == "sdk_moved_to_registry"
    assert detail["install_commands"] == ["pip install harpocrate", "uv add harpocrate"]
    assert detail["url"] == "https://pypi.org/project/harpocrate/"


async def test_retired_python_key_is_gone_even_without_registry_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Index absent ou sans `registry` : toujours 410 (jamais un vieux wheel resté sur disque)."""
    (tmp_path / "harpocrate-0.4.0-py3-none-any.whl").write_bytes(b"old wheel")
    monkeypatch.setattr(sd, "_RELEASES_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        await sd.download_sdk_artifact("python-wheel")
    assert exc.value.status_code == 410
    assert exc.value.detail["error"] == "sdk_moved_to_registry"


async def test_cli_bash_legacy_key_still_served(fake_releases: Path) -> None:
    response = await sd.download_sdk_artifact("cli-bash")
    assert response.path.endswith("harpocrate-cli-0.1.0.tar.gz")
