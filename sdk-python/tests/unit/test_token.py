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
