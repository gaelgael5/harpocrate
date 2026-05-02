"""Helpers de vérification des permissions (bitmap) — LOT_04."""
from __future__ import annotations

PERM_READ = 0x01
PERM_ADD = 0x02
PERM_INIT = 0x04
PERM_WRITE = 0x08
PERM_REMOVE = 0x10
PERM_SHARE = 0x20
PERM_ALL = 0x3F

_BIT_BY_NAME: dict[str, int] = {
    "read": PERM_READ,
    "add": PERM_ADD,
    "init": PERM_INIT,
    "write": PERM_WRITE,
    "remove": PERM_REMOVE,
    "share": PERM_SHARE,
}


def has(permissions: int, required: int) -> bool:
    """Vérifie qu'une permission requise est dans le bitmap."""
    return (permissions & required) == required


def is_subset(subset: int, superset: int) -> bool:
    """Vérifie que subset ⊆ superset (bitwise)."""
    return (subset & superset) == subset


def name_to_bit(name: str) -> int:
    """Convertit un nom de permission en bit. KeyError si inconnu."""
    return _BIT_BY_NAME[name]


def to_names(permissions: int) -> list[str]:
    """Retourne les noms des permissions actives dans le bitmap."""
    return [n for n, b in _BIT_BY_NAME.items() if has(permissions, b)]
