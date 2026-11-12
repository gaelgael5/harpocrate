"""Distribution d'un SDK par le registre officiel de son langage (PyPI, npm…).

`releases/index.json` (schéma ≥ 1.1) peut déclarer, pour un SDK :

    "registry": { "name": "pypi", "package": "harpocrate", "version": "0.8.0" }

Le manifest renvoie alors l'URL de la page du paquet et les commandes d'installation.
Elles sont **dérivées ici** d'une table fermée de registres, jamais lues dans
`index.json` : la page Intégration est publique et affiche un lien et des commandes à
copier-coller ; un texte libre venu du fichier ouvrirait la porte à un lien
`javascript:` ou à une commande piégée au premier `index.json` altéré.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _Registry:
    label: str
    package_url: str
    install_commands: tuple[str, ...]


# `{package}` est le seul paramètre, validé par `_PACKAGE_NAME` avant substitution.
# Ajouter un SDK distribué par un nouveau registre = ajouter sa ligne ici.
_REGISTRIES: dict[str, _Registry] = {
    "pypi": _Registry(
        label="PyPI",
        package_url="https://pypi.org/project/{package}/",
        install_commands=("pip install {package}", "uv add {package}"),
    ),
}

# Sous-ensemble des noms PEP 508 : rien qui puisse s'échapper de l'URL ou de la commande
# (espace, `;`, `&`, `/`, guillemets), ni segment `..` (alphanumérique aux bornes).
# À élargir avec précaution (ex. scope npm `@a/b`).
_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}(?:[A-Za-z0-9.+-]{0,32})$")


def resolve_registry_distribution(sdk_id: str, raw: Any) -> dict[str, Any] | None:
    """Rend la distribution par registre d'un SDK, ou None s'il n'en déclare pas.

    Une déclaration invalide (registre inconnu, nom ou version hors format) n'est pas
    exposée — fail closed — mais journalisée : sans ce warning, le SDK perdrait son
    bloc d'installation sans que personne ne sache pourquoi.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        log.warning("sdk_registry_invalid", sdk_id=sdk_id, reason="not_an_object")
        return None

    name = raw.get("name")
    package = raw.get("package")
    version = raw.get("version")
    registry = _REGISTRIES.get(name) if isinstance(name, str) else None
    if registry is None:
        log.warning("sdk_registry_invalid", sdk_id=sdk_id, reason="unknown_registry")
        return None
    if not isinstance(package, str) or not _PACKAGE_NAME.match(package):
        log.warning("sdk_registry_invalid", sdk_id=sdk_id, reason="invalid_package")
        return None
    if not isinstance(version, str) or not _VERSION.match(version):
        log.warning("sdk_registry_invalid", sdk_id=sdk_id, reason="invalid_version")
        return None

    return {
        "name": name,
        "package": package,
        "version": version,
        **registry_install_info(name, package),
    }


def registry_install_info(name: str, package: str) -> dict[str, Any]:
    """Libellé, page du paquet et commandes d'installation pour un registre CONNU.

    `package` doit déjà avoir été validé (nom constant du code ou `_PACKAGE_NAME`) :
    il est substitué tel quel dans une URL et dans une commande à copier-coller.
    """
    registry = _REGISTRIES[name]
    return {
        "label": registry.label,
        "url": registry.package_url.format(package=package),
        "install_commands": [cmd.format(package=package) for cmd in registry.install_commands],
    }
