"""Tests de parsing du token hrpv_* côté client — LOT_09."""

from __future__ import annotations

import base64
import uuid

import pytest

from harpocrate.exceptions import InvalidTokenError, TokenExpiredError
from harpocrate.token import ParsedToken, parse_token

# Fixtures locales pour les tests de token
_TEST_DKEY_BYTES = bytes(range(32))
_TEST_DKEY_B64 = base64.urlsafe_b64encode(_TEST_DKEY_BYTES).rstrip(b"=").decode()
_TEST_API_KEY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_AUTH_SECRET = "A" * 43
_TEST_HMAC = "B" * 22


def _uuid_to_b32(uid: uuid.UUID) -> str:
    encoded = base64.b32encode(uid.bytes).decode().lower()
    return encoded.rstrip("=")


_TEST_ID_B32 = _uuid_to_b32(_TEST_API_KEY_ID)
_TEST_TOKEN = f"hrpv_1_{_TEST_ID_B32}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"


class TestTokenParse:
    """Tests de parsing de tokens hrpv_*."""

    def test_parse_valid_token(self) -> None:
        """Un token bien formé est parsé correctement."""
        parsed = parse_token(_TEST_TOKEN)

        assert isinstance(parsed, ParsedToken)
        assert parsed.version == "1"
        assert parsed.api_key_id == _TEST_API_KEY_ID
        assert parsed.exp == 0  # pas d'expiration
        assert parsed.permissions == 0x3F  # toutes les permissions
        assert parsed.decryption_key == _TEST_DKEY_BYTES

    def test_parse_extracts_decryption_key(self) -> None:
        """La decryption_key extraite correspond au dkey_b64 du token."""
        parsed = parse_token(_TEST_TOKEN)
        # Ré-encoder pour vérifier
        recovered_b64 = base64.urlsafe_b64encode(parsed.decryption_key).rstrip(b"=").decode()
        assert recovered_b64 == _TEST_DKEY_B64

    def test_parse_roundtrip_api_key_id(self) -> None:
        """L'UUID de l'API key est roundtrip correct."""
        parsed = parse_token(_TEST_TOKEN)
        assert parsed.api_key_id == _TEST_API_KEY_ID

    def test_parse_permissions_decoded(self) -> None:
        """Les permissions hex sont correctement décodées."""
        # perms 0x01 = read
        token = f"hrpv_1_{_TEST_ID_B32}_0_01_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
        parsed = parse_token(token)
        assert parsed.permissions == 0x01

    def test_parse_expiration_nonzero(self) -> None:
        """Une expiration non-zéro est correctement décodée."""
        import time

        future = int(time.time()) + 3600  # dans 1 heure
        # Encode en base36
        exp_b36 = ""
        n = future
        while n:
            exp_b36 = "0123456789abcdefghijklmnopqrstuvwxyz"[n % 36] + exp_b36
            n //= 36
        token = (
            f"hrpv_1_{_TEST_ID_B32}_{exp_b36}_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
        )
        parsed = parse_token(token)
        assert abs(parsed.exp - future) < 2  # tolérance 2s

    def test_parse_hmac_stored_not_verified(self) -> None:
        """Le HMAC est stocké mais non vérifié côté client."""
        parsed = parse_token(_TEST_TOKEN)
        assert parsed.hmac_b64 == _TEST_HMAC

    def test_parse_auth_secret_stored(self) -> None:
        """L'auth_secret est stocké (pour usage futur)."""
        parsed = parse_token(_TEST_TOKEN)
        assert parsed.auth_secret_b64 == _TEST_AUTH_SECRET


class TestTokenInvalidFormat:
    """Tests des erreurs de format de token."""

    def test_reject_wrong_prefix(self) -> None:
        """Un token sans préfixe hrpv_ est rejeté."""
        with pytest.raises(InvalidTokenError) as exc_info:
            parse_token("wrongprefix_1_xxx")
        assert exc_info.value.error_code == "invalid_prefix"

    def test_reject_empty_string(self) -> None:
        """Une chaîne vide est rejetée."""
        with pytest.raises(InvalidTokenError):
            parse_token("")

    def test_reject_too_short(self) -> None:
        """Un token trop court est rejeté."""
        with pytest.raises(InvalidTokenError) as exc_info:
            parse_token("hrpv_1_xxx")
        assert exc_info.value.error_code in ("invalid_format",)

    def test_reject_wrong_segment_count(self) -> None:
        """Un token avec le mauvais nombre de segments est rejeté."""
        with pytest.raises(InvalidTokenError) as exc_info:
            parse_token("hrpv_1_xxx_0_3f_yyy")
        assert exc_info.value.error_code == "invalid_format"

    def test_reject_unsupported_version(self) -> None:
        """Un token de version inconnue est rejeté."""
        token_v2 = f"hrpv_2_{_TEST_ID_B32}_0_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
        with pytest.raises(InvalidTokenError) as exc_info:
            parse_token(token_v2)
        assert exc_info.value.error_code == "unsupported_version"

    def test_reject_non_string(self) -> None:
        """Un objet non-str est rejeté."""
        with pytest.raises(InvalidTokenError):
            parse_token(12345)  # type: ignore[arg-type]

    def test_reject_invalid_permissions(self) -> None:
        """Des permissions hors de la plage [0, 0x3F] sont rejetées."""
        # 0x7F = 127 > 63
        token = f"hrpv_1_{_TEST_ID_B32}_0_7f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
        with pytest.raises(InvalidTokenError) as exc_info:
            parse_token(token)
        assert exc_info.value.error_code == "invalid_perms_value"


class TestTokenExpiry:
    """Tests de vérification d'expiration."""

    def test_expired_token_raises(self) -> None:
        """Un token expiré lève TokenExpiredError."""
        import time

        past = int(time.time()) - 100
        exp_b36 = ""
        n = past
        while n:
            exp_b36 = "0123456789abcdefghijklmnopqrstuvwxyz"[n % 36] + exp_b36
            n //= 36
        token = (
            f"hrpv_1_{_TEST_ID_B32}_{exp_b36}_3f_{_TEST_AUTH_SECRET}_{_TEST_DKEY_B64}_{_TEST_HMAC}"
        )
        with pytest.raises(TokenExpiredError):
            parse_token(token)

    def test_no_expiry_zero_accepted(self) -> None:
        """Un token avec exp=0 (pas d'expiration) est accepté."""
        parsed = parse_token(_TEST_TOKEN)
        assert parsed.exp == 0


class TestTruncateTokenForTransport:
    """Tests de la troncature du token avant envoi HTTP — SDK ≥0.7 split-token.

    La promesse E2E sur les API keys exige que la `dkey` ne transite jamais
    sur le canal HTTP. Le SDK doit donc remplacer le segment dkey du token
    par un placeholder de longueur identique avant de l'envoyer au serveur.
    Le HMAC reste valide (il ne couvre pas la dkey).
    """

    def test_truncation_removes_dkey_segment(self) -> None:
        """La dkey originale n'est plus présente dans le token tronqué."""
        from harpocrate.token import truncate_token_for_transport

        truncated = truncate_token_for_transport(_TEST_TOKEN)
        assert _TEST_DKEY_B64 not in truncated, (
            f"La dkey {_TEST_DKEY_B64!r} a fuité dans le token tronqué"
        )

    def test_truncation_preserves_format_length(self) -> None:
        """Le token tronqué a la même longueur que l'original (placeholder 43 chars)."""
        from harpocrate.token import truncate_token_for_transport

        truncated = truncate_token_for_transport(_TEST_TOKEN)
        assert len(truncated) == len(_TEST_TOKEN)

    def test_truncated_token_is_still_parsable(self) -> None:
        """Le serveur doit pouvoir parser le token tronqué (même structure 8 segments)."""
        from harpocrate.token import truncate_token_for_transport

        truncated = truncate_token_for_transport(_TEST_TOKEN)
        # Le format reste valide pour le parseur (la dkey décodée n'est plus
        # la vraie clé, mais le parsing ne planterait pas côté serveur).
        # Note : `parse_token` côté SDK décode aussi la dkey ; il ne lèvera
        # pas car le placeholder est un base64url valide.
        reparsed = parse_token(truncated)
        assert reparsed.api_key_id == _TEST_API_KEY_ID
        assert reparsed.permissions == 0x3F
        assert reparsed.exp == 0

    def test_truncated_token_preserves_auth_secret(self) -> None:
        """Le segment auth_secret (signé par HMAC) est intact dans le token tronqué."""
        from harpocrate.token import truncate_token_for_transport

        truncated = truncate_token_for_transport(_TEST_TOKEN)
        reparsed = parse_token(truncated)
        # auth_secret_b64 doit être identique à l'original (sinon le HMAC casse)
        assert reparsed.auth_secret_b64 == _TEST_AUTH_SECRET

    def test_truncated_token_preserves_hmac(self) -> None:
        """Le segment HMAC est intact dans le token tronqué (vérification serveur OK)."""
        from harpocrate.token import truncate_token_for_transport

        truncated = truncate_token_for_transport(_TEST_TOKEN)
        reparsed = parse_token(truncated)
        assert reparsed.hmac_b64 == _TEST_HMAC

    def test_truncated_token_dkey_segment_is_constant(self) -> None:
        """Deux tokens différents tronqués partagent le même placeholder dkey
        (constant déterministe, pas d'info-leak via du random)."""
        from harpocrate.token import truncate_token_for_transport

        other_dkey_bytes = bytes([0xFF] * 32)
        other_dkey_b64 = base64.urlsafe_b64encode(other_dkey_bytes).rstrip(b"=").decode()
        other_token = (
            f"hrpv_1_{_TEST_ID_B32}_0_3f_{_TEST_AUTH_SECRET}_{other_dkey_b64}_{_TEST_HMAC}"
        )

        t1 = truncate_token_for_transport(_TEST_TOKEN)
        t2 = truncate_token_for_transport(other_token)

        # Les deux tokens tronqués diffèrent uniquement par leur auth_secret/hmac,
        # pas par le segment dkey (qui doit être le même placeholder).
        d1 = parse_token(t1).dkey_b64
        d2 = parse_token(t2).dkey_b64
        assert d1 == d2, "Le placeholder dkey doit être constant entre tokens"

    def test_invalid_token_raises(self) -> None:
        """Un token malformé lève InvalidTokenError, pas de fallback silencieux."""
        from harpocrate.token import truncate_token_for_transport

        with pytest.raises(InvalidTokenError):
            truncate_token_for_transport("hrpv_garbage")

    def test_truncation_is_idempotent(self) -> None:
        """Tronquer un token déjà tronqué redonne le même résultat."""
        from harpocrate.token import truncate_token_for_transport

        once = truncate_token_for_transport(_TEST_TOKEN)
        twice = truncate_token_for_transport(once)
        assert once == twice
