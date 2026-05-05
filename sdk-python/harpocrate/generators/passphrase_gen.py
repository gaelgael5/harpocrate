"""Générateur de passphrase — type 'passphrase' — LOT_09 SDK.

Utilise secrets.choice() sur une liste de mots EFF-style.
Langues : 'en' (défaut) et 'fr'.

La wordlist embarquée contient environ 300 mots EFF-style.
Pour une sécurité maximale (~77 bits d'entropie pour 6 mots sur 7776),
remplacer la wordlist par la liste EFF complète (7776 mots).

Entropie approx. avec la wordlist MVP :
  n mots sur W mots : n × log2(W) bits
  6 mots sur 300 : 6 × 8.2 ≈ 49 bits — suffisant pour un token d'accès

Note : la wordlist complète EFF est disponible sur https://www.eff.org/dice
"""

from __future__ import annotations

import pathlib
import secrets
from typing import Any

_WORDLIST_DIR = pathlib.Path(__file__).parent / "wordlists"
_CACHE: dict[str, list[str]] = {}


def _load_wordlist(language: str) -> list[str]:
    """Charge la wordlist depuis le fichier texte embarqué.

    Résultat mis en cache en RAM.
    Lève FileNotFoundError si la langue n'est pas supportée.
    """
    if language in _CACHE:
        return _CACHE[language]

    path = _WORDLIST_DIR / f"{language}.txt"
    if not path.exists():
        raise ValueError(f"Wordlist for language '{language}' not found. Supported: en, fr")

    words = [w.strip() for w in path.read_text(encoding="utf-8").splitlines() if w.strip()]
    if len(words) < 10:
        raise ValueError(f"Wordlist '{language}' is too small ({len(words)} words)")

    _CACHE[language] = words
    return words


def generate(descriptor: dict[str, Any]) -> str:
    """Génère une passphrase composée de mots aléatoires.

    Paramètres du descripteur :
        words    (int, 4-16, défaut 6) : nombre de mots
        separator (str, défaut '-')   : séparateur entre les mots
        language (str, 'en'|'fr')     : langue de la wordlist

    Retourne :
        str passphrase (ex: "tiger-castle-river-moon-brave-limit")
    """
    n_words = int(descriptor.get("words", 6))
    separator = str(descriptor.get("separator", "-"))
    language = str(descriptor.get("language", "en"))

    if n_words < 1:
        raise ValueError(f"words must be >= 1, got {n_words}")

    wordlist = _load_wordlist(language)
    chosen = [secrets.choice(wordlist) for _ in range(n_words)]
    return separator.join(chosen)
