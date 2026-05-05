"""Tests P-fix — sdk_downloads avec glob discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.v1 import sdk_downloads as sd


@pytest.fixture
def fake_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Crée un dossier releases/ avec quelques fichiers fictifs."""
    (tmp_path / "harpocrate-0.3.0-py3-none-any.whl").write_bytes(b"x")
    (tmp_path / "harpocrate-0.4.0-py3-none-any.whl").write_bytes(b"x")
    (tmp_path / "harpocrate-sdk-0.3.0.tar.gz").write_bytes(b"x")
    (tmp_path / "harpocrate-sdk-0.4.0.tar.gz").write_bytes(b"x")
    (tmp_path / "harpocrate-cli-0.1.0.tar.gz").write_bytes(b"x")
    (tmp_path / "README.md").write_text("ignored")  # pas un artefact
    (tmp_path / "evil.tar.gz").write_text("ignored")  # pas un artefact (pas le préfixe)
    monkeypatch.setattr(sd, "_RELEASES_DIR", tmp_path)
    return tmp_path


def test_discover_artifacts_finds_all_versions(fake_releases: Path) -> None:
    discovered = sd._discover_artifacts()
    filenames = {d["filename"] for d in discovered}
    assert filenames == {
        "harpocrate-0.3.0-py3-none-any.whl",
        "harpocrate-0.4.0-py3-none-any.whl",
        "harpocrate-sdk-0.3.0.tar.gz",
        "harpocrate-sdk-0.4.0.tar.gz",
        "harpocrate-cli-0.1.0.tar.gz",
    }
    # README.md et evil.tar.gz ne doivent pas être listés
    assert all("evil" not in str(d["filename"]) for d in discovered)
    assert all("README" not in str(d["filename"]) for d in discovered)


def test_discover_extracts_language_kind_version(fake_releases: Path) -> None:
    discovered = sd._discover_artifacts()
    by_fn = {d["filename"]: d for d in discovered}

    wheel = by_fn["harpocrate-0.4.0-py3-none-any.whl"]
    assert wheel["language"] == "python"
    assert wheel["kind"] == "wheel"
    assert wheel["version"] == "0.4.0"

    sdist = by_fn["harpocrate-sdk-0.3.0.tar.gz"]
    assert sdist["language"] == "python"
    assert sdist["kind"] == "sdist"
    assert sdist["version"] == "0.3.0"

    cli = by_fn["harpocrate-cli-0.1.0.tar.gz"]
    assert cli["language"] == "bash"
    assert cli["kind"] == "cli"
    assert cli["version"] == "0.1.0"


def test_legacy_artifacts_returns_latest_per_kind(fake_releases: Path) -> None:
    legacy = sd._legacy_artifacts()
    by_key = {item["key"]: item for item in legacy}

    assert by_key["python-wheel"]["filename"] == "harpocrate-0.4.0-py3-none-any.whl"
    assert by_key["python-wheel"]["available"] == "true"
    assert by_key["python-sdist"]["filename"] == "harpocrate-sdk-0.4.0.tar.gz"
    assert by_key["cli-bash"]["filename"] == "harpocrate-cli-0.1.0.tar.gz"


def test_legacy_artifacts_unavailable_when_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sd, "_RELEASES_DIR", tmp_path)
    legacy = sd._legacy_artifacts()
    assert all(item["available"] == "false" for item in legacy)
    assert {item["key"] for item in legacy} == {"python-wheel", "python-sdist", "cli-bash"}


def test_safe_filename_pattern_accepts_real_artifacts() -> None:
    assert sd._SAFE_FILENAME.match("harpocrate-0.4.0-py3-none-any.whl")
    assert sd._SAFE_FILENAME.match("harpocrate-sdk-0.4.0.tar.gz")
    assert sd._SAFE_FILENAME.match("harpocrate-cli-0.1.0.tar.gz")


def test_safe_filename_pattern_rejects_path_traversal() -> None:
    assert not sd._SAFE_FILENAME.match("../etc/passwd")
    assert not sd._SAFE_FILENAME.match("../../something.whl")
    assert not sd._SAFE_FILENAME.match("/etc/passwd")
    # Pas de prefix `harpocrate-` → refusé
    assert not sd._SAFE_FILENAME.match("evil-1.0.0.tar.gz")


def test_natural_version_key_orders_correctly() -> None:
    # 0.10.0 doit être > 0.9.0 (et non l'inverse comme avec un tri lexicographique)
    assert sd._natural_version_key("0.10.0") > sd._natural_version_key("0.9.0")
    assert sd._natural_version_key("1.0.0") > sd._natural_version_key("0.99.99")
    assert sd._natural_version_key("0.4.0") > sd._natural_version_key("0.3.99")
