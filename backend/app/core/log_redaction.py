"""Masquage des segments d'URL qui ne doivent pas atteindre les journaux.

La référence opaque d'une demande de connexion (`request_uri`, flux « Se connecter avec
Harpocrate ») voyage dans le chemin des routes /v1/connect/requests/… : la journaliser
permettrait à qui lit les journaux de tenter de s'approprier la demande.
"""

from __future__ import annotations

import logging
import re

# Le chemin peut arriver encodé (`urn%3A…`) et suivi de sa requête : tout ce qui suit le
# préfixe jusqu'au prochain `/` est masqué, requête comprise.
_CONNECT_REQUEST_REF = re.compile(r"^(/v1/connect/requests/)[^/]+")


def loggable_path(path: str) -> str:
    """Chemin à journaliser : identique, sauf la référence d'une demande de connexion."""
    return _CONNECT_REQUEST_REF.sub(r"\1[redacted]", path)


class AccessLogRedactionFilter(logging.Filter):
    """Masque la référence dans le journal d'accès d'uvicorn (`uvicorn.access`).

    Ce journal écrit le chemin brut, requête comprise, à côté de celui de l'application :
    sans ce filtre, la référence y apparaîtrait en clair. Arguments d'uvicorn :
    (client, méthode, chemin complet, version HTTP, statut).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], loggable_path(args[2]), *args[3:])
        return True


def install_access_log_redaction() -> None:
    logging.getLogger("uvicorn.access").addFilter(AccessLogRedactionFilter())
