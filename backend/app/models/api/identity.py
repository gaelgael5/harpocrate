"""Schemas Pydantic pour les endpoints /me/identities/*, /me/anomalies/*,
/me/reverify/*, /me/quarantine/* (LOT_02 governance)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ─── Identites externes ──────────────────────────────────────────────────────


class ExternalIdentityResponse(BaseModel):
    id: UUID
    provider: str
    external_subject: str
    is_primary: bool
    linked_at: datetime
    last_login_at: datetime | None = None
    linked_email: str | None = None
    linked_display_name: str | None = None


class IdentitiesListResponse(BaseModel):
    identities: list[ExternalIdentityResponse]


class LinkIdentityRequest(BaseModel):
    """Le client fournit un JWT issu d'un autre provider OIDC. Le serveur
    valide ce JWT (audience/issuer/signature), extrait sub/email/name,
    et cree la liaison."""

    provider_token: str = Field(..., description="JWT du provider externe (RS256)")


class SetPrimaryRequest(BaseModel):
    """Designation d'une identite comme primary. L'email du user est mis a
    jour avec celui de la nouvelle primary."""

    identity_id: UUID


# ─── Anomalies ───────────────────────────────────────────────────────────────


class AnomalyResponse(BaseModel):
    id: int
    detected_at: datetime
    severity: Literal["info", "warning", "critical"]
    anomaly_type: str
    metadata: dict[str, Any] | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by_user_id: UUID | None = None


class AnomaliesListResponse(BaseModel):
    anomalies: list[AnomalyResponse]


# ─── Reverify token ──────────────────────────────────────────────────────────


class ReverifyChallengeResponse(BaseModel):
    """Le serveur emet un token one-shot que le client doit re-presenter dans
    les 5 minutes suivant un re-prompt de la passphrase. Le token est juste
    une chaine opaque ; le client le mettra dans le header X-Reverify-Token
    pour la prochaine action sensible."""

    reverify_token: str
    expires_at: datetime
    ttl_seconds: int


class ReverifyChallengeRequest(BaseModel):
    """Le client demande un challenge en re-vérifiant qu'il connait la
    passphrase. Le client doit avoir deverrouille avec passphrase recente
    (< 60s) — verification cote client."""

    # Pas de payload pour le moment ; le serveur fait confiance au JWT du
    # caller. La verification de la passphrase se fait cote client (le client
    # ne demande un challenge que s'il vient d'unlock). C'est volontairement
    # leger — la securite vient du fait que le token est one-shot 5 min.


# ─── Quarantine ──────────────────────────────────────────────────────────────


class QuarantineStatusResponse(BaseModel):
    in_quarantine: bool
    quarantine_until: datetime | None = None
    quarantine_reason: str | None = None
    force_reverify_next_login: bool


class QuarantineExitRequest(BaseModel):
    """Sortie de quarantaine : le user fournit un X-Reverify-Token valide
    (preuve qu'il connait la passphrase). Le serveur consomme le token et
    leve la quarantaine."""

    # Pas de payload : le token est dans le header X-Reverify-Token.
