"""Table de dispatch des 9 générateurs — LOT_09 SDK.

Usage :
    from harpocrate.generators import dispatch
    value: str = dispatch({"type": "random", "length": 32, "charset": "alphanum"})

Tous les générateurs reçoivent un dict ``descriptor`` et retournent str.
"""

from __future__ import annotations

from typing import Any

from harpocrate.exceptions import GeneratorError
from harpocrate.generators import (
    bcrypt_password_gen,
    bytes_gen,
    passphrase_gen,
    random_gen,
    rsa_keypair_gen,
    ssh_keypair_gen,
    template_gen,
    tls_certificate_gen,
    uuid_gen,
)

# Mapping type → fonction generate(descriptor) -> str
_GENERATORS: dict[str, Any] = {
    "random": random_gen.generate,
    "uuid": uuid_gen.generate,
    "bytes": bytes_gen.generate,
    "passphrase": passphrase_gen.generate,
    "template": template_gen.generate,
    "rsa_keypair": rsa_keypair_gen.generate,
    "ssh_keypair": ssh_keypair_gen.generate,
    "tls_certificate": tls_certificate_gen.generate,
    "bcrypt_password": bcrypt_password_gen.generate,
}


def dispatch(descriptor: dict[str, Any]) -> str:
    """Dispatch vers le bon générateur selon ``descriptor['type']``.

    Paramètre :
        descriptor (dict) : descripteur de génération (doit avoir une clé 'type')

    Retourne :
        str : valeur générée

    Lève :
        GeneratorError si le type est inconnu ou si la génération échoue.
    """
    gen_type = descriptor.get("type")
    if not isinstance(gen_type, str):
        raise GeneratorError(
            f"Descriptor must have a string 'type' field, got: {type(gen_type).__name__!r}"
        )

    fn = _GENERATORS.get(gen_type)
    if fn is None:
        raise GeneratorError(
            f"Unknown generator type: {gen_type!r}. "
            f"Supported: {', '.join(sorted(_GENERATORS.keys()))}"
        )

    try:
        from collections.abc import Callable

        generate_fn: Callable[[dict[str, Any]], str] = fn
        return generate_fn(descriptor)
    except GeneratorError:
        raise
    except Exception as exc:
        raise GeneratorError(f"Generator '{gen_type}' failed: {exc}") from exc


__all__ = ["dispatch"]
