"""Générateur de template — type 'template' — LOT_09 SDK.

Substitue les variables {name} dans un template par des valeurs générées
ou littérales. Récursion limitée à 1 niveau (les variables d'un template
ne peuvent pas elles-mêmes être des templates).

Exemple de descripteur :
    {
        "type": "template",
        "template": "{username}:{password}@{host}:{port}",
        "variables": {
            "username": {"literal": "admin"},
            "password": {"type": "random", "length": 24, "charset": "alphanum"},
            "host":     {"literal": "db.example.com"},
            "port":     {"literal": "5432"}
        }
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harpocrate.exceptions import GeneratorError

if TYPE_CHECKING:
    pass


def generate(descriptor: dict[str, Any]) -> str:
    """Génère la chaîne issue de la substitution du template.

    Paramètres du descripteur :
        template  (str) : template avec placeholders {var_name}
        variables (dict) : mapping name → sub-descripteur ou {'literal': value}

    Retourne :
        str avec toutes les variables substituées

    Lève :
        GeneratorError si un placeholder n'a pas de variable définie ou vice-versa.
    """
    # Import ici pour éviter la circularité (dispatch_generator importe les générateurs)
    from harpocrate.generators import dispatch

    template = str(descriptor["template"])
    variables_raw = descriptor.get("variables")
    if not isinstance(variables_raw, dict):
        raise GeneratorError("template descriptor must have a 'variables' dict")

    variables: dict[str, Any] = variables_raw

    import re

    placeholders = set(re.findall(r"\{(\w+)\}", template))
    missing = placeholders - variables.keys()
    if missing:
        raise GeneratorError(
            f"Template placeholders without variable definitions: {sorted(missing)}"
        )

    resolved: dict[str, str] = {}
    for var_name, var_desc in variables.items():
        if not isinstance(var_desc, dict):
            raise GeneratorError(f"Variable '{var_name}' must be a dict descriptor")
        if "literal" in var_desc:
            resolved[var_name] = str(var_desc["literal"])
        else:
            # Sous-descripteur : génère la valeur (récursion niveau 1)
            if var_desc.get("type") == "template":
                raise GeneratorError(
                    "Recursive TemplateDescriptor is not supported "
                    "(template variables cannot be templates themselves)"
                )
            resolved[var_name] = dispatch(var_desc)

    try:
        return template.format(**resolved)
    except KeyError as exc:
        raise GeneratorError(f"Template substitution failed: {exc}") from exc
