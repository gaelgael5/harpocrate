"""Logging structlog JSON. Aucune valeur sensible loggée — règle de l'OVERVIEW §14."""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings
from app.core.log_redaction import install_access_log_redaction


def configure_logging() -> None:
    """Configure structlog with JSON output to stdout."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        cache_logger_on_first_use=True,
    )
    # La référence d'une demande de connexion ne doit pas sortir par le journal d'accès
    # d'uvicorn, qui écrit le chemin brut (cf. app/core/log_redaction.py).
    install_access_log_redaction()
    # LOT_21A — chaque log de ce process porte l'instance_id du nœud.
    structlog.contextvars.bind_contextvars(instance=settings.instance_id)


logger = structlog.get_logger()
