"""Masquage des segments d'URL qui ne doivent pas atteindre les journaux.

La référence opaque d'une demande de connexion (`request_uri`, flux « Se connecter avec
Harpocrate ») voyage dans le chemin des routes /v1/connect/requests/… : la journaliser
permettrait à qui lit les journaux de tenter de s'approprier la demande.
"""

from __future__ import annotations

import re

_CONNECT_REQUEST_REF = re.compile(r"^(/v1/connect/requests/)[^/]+")


def loggable_path(path: str) -> str:
    """Chemin à journaliser : identique, sauf la référence d'une demande de connexion."""
    return _CONNECT_REQUEST_REF.sub(r"\1[redacted]", path)
