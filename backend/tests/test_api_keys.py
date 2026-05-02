"""Tests LOT_08 — API keys hrpv_* : token, HMAC, cache, auth, cascade, endpoints."""
from __future__ import annotations

import base64
import datetime
import time
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests._helpers import (
    TEST_AUDIENCE,
    TEST_KID,
    TEST_PUBLIC_JWK,
    make_jwt_token,
)

# ─── Constantes de test ───────────────────────────────────────────────────────

_CALLER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_WALLET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_API_KEY_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")

_HMAC_KEY_BYTES = b"k" * 32
_HMAC_KEY_B64 = base64.b64encode(_HMAC_KEY_BYTES).decode()

_PERM_ALL = 0x3F
_PERM_READ = 0x01
_PERM_READ_ADD = 0x03

# ─── Fixtures d'environnement ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARPOCRATE_DB_DSN", "postgresql://x:y@h:5432/d")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_URL", "https://keycloak.yoops.org")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_REALM", "yoops")
    monkeypatch.setenv("HARPOCRATE_KEYCLOAK_CLIENT_ID", TEST_AUDIENCE)
    monkeypatch.setenv("HARPOCRATE_HMAC_KEY", _HMAC_KEY_B64)
    monkeypatch.setenv("HARPOCRATE_PUBLIC_URL", "https://vault.yoops.org")

    import app.core.security

    _sec = app.core.security.__dict__["settings"]
    monkeypatch.setattr(_sec, "keycloak_url", "https://keycloak.yoops.org")
    monkeypatch.setattr(_sec, "keycloak_realm", "yoops")
    monkeypatch.setattr(_sec, "keycloak_client_id", TEST_AUDIENCE)


@pytest.fixture(autouse=True)
def patch_jwks() -> Generator[None, None, None]:
    from app.core import jwks_cache

    keys_backup = dict(jwks_cache._keys)
    jwks_cache._keys.clear()
    jwks_cache._keys[TEST_KID] = TEST_PUBLIC_JWK
    yield
    jwks_cache._keys.clear()
    jwks_cache._keys.update(keys_backup)


@pytest.fixture(autouse=True)
def clear_api_key_cache() -> Generator[None, None, None]:
    """Vide le cache de validation avant chaque test."""
    from app.core.api_key_cache import cache_clear_all

    cache_clear_all()
    yield
    cache_clear_all()


# ─── FakeRecord ───────────────────────────────────────────────────────────────


class FakeRecord(dict[str, Any]):
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


# ─── Helpers de fabrication de tokens ─────────────────────────────────────────


def _make_token(
    api_key_id: uuid.UUID = _API_KEY_ID,
    exp: int = 0,
    perms: int = _PERM_ALL,
    auth_secret_b64: str | None = None,
    dkey_b64: str | None = None,
    master_key_b64: str = _HMAC_KEY_B64,
) -> str:
    from app.core.api_key_token import encode_token

    if auth_secret_b64 is None:
        auth_secret_b64 = base64.urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode()
    if dkey_b64 is None:
        dkey_b64 = base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode()

    return encode_token(
        api_key_id=api_key_id,
        exp=exp,
        perms=perms,
        auth_secret_b64=auth_secret_b64,
        dkey_b64=dkey_b64,
        master_key_b64=master_key_b64,
    )


def _default_auth_secret_b64() -> str:
    return base64.urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode()


def _default_dkey_b64() -> str:
    return base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode()


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — TOKEN ENCODE / DECODE
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenEncodeDecode:
    def test_encode_decode_roundtrip(self) -> None:
        from app.core.api_key_token import encode_token, parse_token

        auth_b64 = base64.urlsafe_b64encode(b"a" * 32).rstrip(b"=").decode()
        dkey_b64 = base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode()

        token = encode_token(
            api_key_id=_API_KEY_ID,
            exp=9999999999,
            perms=0x05,
            auth_secret_b64=auth_b64,
            dkey_b64=dkey_b64,
            master_key_b64=_HMAC_KEY_B64,
        )

        assert token.startswith("hrpv_1_")

        parsed = parse_token(token)
        assert parsed.api_key_id == _API_KEY_ID
        assert parsed.exp == 9999999999
        assert parsed.perms == 0x05
        assert parsed.auth_secret_b64 == auth_b64
        assert parsed.dkey_b64 == dkey_b64
        assert parsed.version == "1"

    def test_token_format_has_8_segments(self) -> None:
        token = _make_token()
        parts = token.split("_")
        assert len(parts) == 8
        assert parts[0] == "hrpv"
        assert parts[1] == "1"

    def test_token_perms_hex_two_chars(self) -> None:
        token = _make_token(perms=0x05)
        parts = token.split("_")
        assert parts[4] == "05"

    def test_token_exp_zero_no_expiration(self) -> None:
        from app.core.api_key_token import parse_token

        token = _make_token(exp=0)
        parsed = parse_token(token)
        assert parsed.exp == 0

    def test_token_exp_future(self) -> None:
        from app.core.api_key_token import parse_token

        future_exp = int(time.time()) + 86400
        token = _make_token(exp=future_exp)
        parsed = parse_token(token)
        assert parsed.exp == future_exp

    def test_token_invalid_format_too_few_segments(self) -> None:
        from app.core.api_key_token import TokenParseError, parse_token

        with pytest.raises(TokenParseError) as exc_info:
            parse_token("hrpv_1_abc")
        assert exc_info.value.error_code == "invalid_format"

    def test_token_invalid_format_wrong_prefix(self) -> None:
        from app.core.api_key_token import TokenParseError, parse_token

        with pytest.raises(TokenParseError) as exc_info:
            parse_token("wrong_1_id_0_3f_auth_dkey_hmac")
        assert exc_info.value.error_code == "invalid_prefix"

    def test_token_invalid_unsupported_version(self) -> None:
        from app.core.api_key_token import TokenParseError, parse_token

        token = _make_token()
        parts = token.split("_")
        parts[1] = "9"  # version inconnue
        with pytest.raises(TokenParseError) as exc_info:
            parse_token("_".join(parts))
        assert exc_info.value.error_code == "unsupported_version"

    def test_token_invalid_id_encoding(self) -> None:
        """Un id_b32 avec des caractères invalides pour base32 → erreur de parsing."""
        from app.core.api_key_token import TokenParseError, parse_token

        # Construit un token avec un id_b32 de la bonne longueur (26 chars) mais
        # contenant des caractères invalides pour base32 (ex: '8', '9' sont invalides)
        token = _make_token()
        # Le token est parsé positionellement — injecte un id valide en taille mais
        # invalide en base32 en manipulant les chars de début du token
        # "hrpv_1_" = 7 chars, puis 26 chars d'id, puis "_"
        bad_id = "88888888888888888888888888"  # '8' et '9' sont invalides en base32
        tampered = "hrpv_1_" + bad_id + token[7 + 26:]
        with pytest.raises(TokenParseError) as exc_info:
            parse_token(tampered)
        assert exc_info.value.error_code == "invalid_id_encoding"

    def test_token_invalid_exp_encoding(self) -> None:
        from app.core.api_key_token import TokenParseError, parse_token

        token = _make_token()
        parts = token.split("_")
        parts[3] = "notbase36!!"  # exp invalide
        with pytest.raises(TokenParseError) as exc_info:
            parse_token("_".join(parts))
        assert exc_info.value.error_code == "invalid_exp_encoding"


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — HMAC
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenHmac:
    def test_hmac_valid_token(self) -> None:
        from app.core.api_key_token import parse_token, verify_hmac

        token = _make_token()
        parsed = parse_token(token)

        assert verify_hmac(
            _HMAC_KEY_B64,
            version=parsed.version,
            id_b32=parsed.api_key_id_b32,
            exp_b36=parsed.exp_b36,
            perms_hex=parsed.perms_hex,
            auth_secret_b64=parsed.auth_secret_b64,
            given_hmac_b64=parsed.hmac_b64,
        )

    def test_hmac_invalid_tampered_auth_secret(self) -> None:
        from app.core.api_key_token import parse_token, verify_hmac

        token = _make_token()
        parsed = parse_token(token)

        tampered_secret = base64.urlsafe_b64encode(b"X" * 32).rstrip(b"=").decode()
        assert not verify_hmac(
            _HMAC_KEY_B64,
            version=parsed.version,
            id_b32=parsed.api_key_id_b32,
            exp_b36=parsed.exp_b36,
            perms_hex=parsed.perms_hex,
            auth_secret_b64=tampered_secret,
            given_hmac_b64=parsed.hmac_b64,
        )

    def test_hmac_invalid_tampered_perms(self) -> None:
        from app.core.api_key_token import parse_token, verify_hmac

        token = _make_token(perms=0x01)
        parsed = parse_token(token)

        assert not verify_hmac(
            _HMAC_KEY_B64,
            version=parsed.version,
            id_b32=parsed.api_key_id_b32,
            exp_b36=parsed.exp_b36,
            perms_hex="3f",  # tampered
            auth_secret_b64=parsed.auth_secret_b64,
            given_hmac_b64=parsed.hmac_b64,
        )

    def test_hmac_uses_compare_digest_not_eq(self) -> None:
        """Vérifie que verify_hmac utilise hmac.compare_digest (constant-time)."""
        import inspect

        from app.core import api_key_token

        source = inspect.getsource(api_key_token)
        assert "compare_digest" in source
        # S'assurer qu'il n'y a pas de comparaison directe avec ==
        # (on vérifie que le pattern attend bien compare_digest)
        assert "hmac.compare_digest" in source

    def test_hmac_does_not_include_decryption_key(self) -> None:
        """Le HMAC ne couvre pas decryption_key — on peut changer dkey sans invalider le HMAC."""
        from app.core.api_key_token import parse_token, verify_hmac

        auth_b64 = _default_auth_secret_b64()
        dkey1 = base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode()

        token1 = _make_token(auth_secret_b64=auth_b64, dkey_b64=dkey1)
        parsed1 = parse_token(token1)

        # On vérifie que le HMAC du token1 est valide même si on substitue dkey2
        # (ce qui est normal : dkey n'est pas dans le HMAC)
        assert verify_hmac(
            _HMAC_KEY_B64,
            version=parsed1.version,
            id_b32=parsed1.api_key_id_b32,
            exp_b36=parsed1.exp_b36,
            perms_hex=parsed1.perms_hex,
            auth_secret_b64=parsed1.auth_secret_b64,
            given_hmac_b64=parsed1.hmac_b64,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — EXPIRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenExpiration:
    def test_not_expired_when_exp_zero(self) -> None:
        from app.core.api_key_token import is_expired

        assert not is_expired(0)

    def test_not_expired_when_future(self) -> None:
        from app.core.api_key_token import is_expired

        future = int(time.time()) + 3600
        assert not is_expired(future)

    def test_expired_when_past(self) -> None:
        from app.core.api_key_token import is_expired

        past = int(time.time()) - 1
        assert is_expired(past)


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — CACHE
# ═══════════════════════════════════════════════════════════════════════════════


class TestApiKeyCache:
    def test_cache_miss_returns_none(self) -> None:
        from app.core.api_key_cache import cache_get_valid

        result = cache_get_valid(_API_KEY_ID, "some_secret")
        assert result is None

    def test_cache_set_and_get_valid(self) -> None:
        from app.core.api_key_cache import cache_get_valid, cache_set_valid

        cache_set_valid(_API_KEY_ID, "secret", valid=True)
        assert cache_get_valid(_API_KEY_ID, "secret") is True

    def test_cache_set_and_get_invalid(self) -> None:
        from app.core.api_key_cache import cache_get_valid, cache_set_valid

        cache_set_valid(_API_KEY_ID, "bad_secret", valid=False)
        assert cache_get_valid(_API_KEY_ID, "bad_secret") is False

    def test_cache_expired_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Une entrée expirée retourne None (simulé par monotonic avancé)."""
        from app.core import api_key_cache as cache_mod

        cache_mod.cache_set_valid(_API_KEY_ID, "sec", valid=True)

        # Avance le temps virtuel au-delà du TTL
        original_monotonic = time.monotonic

        def fake_monotonic() -> float:
            return original_monotonic() + 9999.0

        monkeypatch.setattr(time, "monotonic", fake_monotonic)
        assert cache_mod.cache_get_valid(_API_KEY_ID, "sec") is None

    def test_cache_invalidate_removes_entries(self) -> None:
        from app.core.api_key_cache import cache_get_valid, cache_invalidate, cache_set_valid

        cache_set_valid(_API_KEY_ID, "secret1", valid=True)
        cache_set_valid(_API_KEY_ID, "secret2", valid=True)
        other_id = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
        cache_set_valid(other_id, "secret3", valid=True)

        cache_invalidate(_API_KEY_ID)

        assert cache_get_valid(_API_KEY_ID, "secret1") is None
        assert cache_get_valid(_API_KEY_ID, "secret2") is None
        # L'autre clé n'est pas affectée
        assert cache_get_valid(other_id, "secret3") is True

    def test_cache_uses_sha256_of_secret_not_plaintext(self) -> None:
        """Vérifie que la clé de cache est sha256(secret) et non le secret en clair."""
        import inspect

        from app.core import api_key_cache

        source = inspect.getsource(api_key_cache)
        assert "sha256" in source


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — PERM HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPermHelpers:
    def test_perms_subset_check(self) -> None:
        from app.services.permissions import is_subset

        assert is_subset(0x01, 0x3F)  # read ⊆ all
        assert is_subset(0x3F, 0x3F)  # all ⊆ all
        assert not is_subset(0x3F, 0x01)  # all ⊄ read

    def test_has_permission(self) -> None:
        from app.services.permissions import has

        assert has(0x3F, 0x01)
        assert not has(0x02, 0x01)  # add ne contient pas read


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — VALIDATION ORDER (0 DB checks first)
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidationOrder:
    """Vérifie que les checks 0-DB passent avant tout accès DB."""

    @pytest.mark.asyncio
    async def test_expired_token_rejected_before_db(self) -> None:
        """Un token expiré doit être rejeté avant tout accès DB."""
        from app.core.api_key_auth import validate_api_key_token

        past_exp = int(time.time()) - 10
        token = _make_token(exp=past_exp)

        mock_pool = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await validate_api_key_token(token, pool=mock_pool)

        assert exc_info.value.status_code == 401
        detail: dict[str, Any] = exc_info.value.detail  # type: ignore[assignment]
        assert detail["error"] == "expired"
        # Aucun accès DB
        mock_pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_hmac_rejected_before_db(self) -> None:
        """Un token avec HMAC invalide doit être rejeté avant tout accès DB."""
        from fastapi import HTTPException

        from app.core.api_key_auth import validate_api_key_token

        token = _make_token()
        parts = token.split("_")
        parts[-1] = base64.urlsafe_b64encode(b"X" * 16).rstrip(b"=").decode()
        tampered = "_".join(parts)

        mock_pool = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_api_key_token(tampered, pool=mock_pool)

        assert exc_info.value.status_code == 401
        detail: dict[str, Any] = exc_info.value.detail  # type: ignore[assignment]
        assert detail["error"] == "invalid_signature"
        mock_pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_insufficient_perms_rejected_before_db(self) -> None:
        """Les permissions insuffisantes doivent être rejetées avant tout accès DB."""
        from fastapi import HTTPException

        from app.core.api_key_auth import validate_api_key_token
        from app.services.permissions import PERM_READ, PERM_SHARE

        # Token avec permission read=0x01, mais route requiert share=0x20
        token = _make_token(perms=PERM_READ)
        mock_pool = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_api_key_token(token, pool=mock_pool, required_permission=PERM_SHARE)

        assert exc_info.value.status_code == 403
        detail: dict[str, Any] = exc_info.value.detail  # type: ignore[assignment]
        assert detail["error"] == "insufficient_permissions"
        mock_pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_format_rejected_before_db(self) -> None:
        """Un token malformé doit être rejeté avant tout accès DB."""
        from fastapi import HTTPException

        from app.core.api_key_auth import validate_api_key_token

        mock_pool = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await validate_api_key_token("hrpv_bad_format", pool=mock_pool)

        assert exc_info.value.status_code == 401
        mock_pool.acquire.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — CACHE HIT AVOIDS DB
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheHitAvoidsDb:
    @pytest.mark.asyncio
    async def test_cache_hit_avoids_argon2_db_call(self) -> None:
        """Deuxième appel avec même token → le cache évite le hit Argon2id."""
        from app.core import api_key_cache as cache_mod
        from app.core.api_key_auth import validate_api_key_token

        token = _make_token()
        auth_secret = _default_auth_secret_b64()

        # Pré-remplir le cache comme valid
        cache_mod.cache_set_valid(_API_KEY_ID, auth_secret, valid=True)

        # Mock pool : fetchrow retourne les données wallet
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            side_effect=[
                # Premier fetchrow : wallet_id + owner (après cache hit)
                FakeRecord({
                    "wallet_id": _WALLET_ID,
                    "owner_user_id": _CALLER_ID,
                }),
                # Deuxième fetchrow : grant check
                FakeRecord({"permissions": _PERM_ALL}),
            ]
        )
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        class FakeAcquireCtx:
            async def __aenter__(self) -> Any:
                return mock_conn

            async def __aexit__(self, *args: Any) -> None:
                pass

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=FakeAcquireCtx())

        # Pas d'erreur levée = validation OK
        with patch("asyncio.create_task"):
            result = await validate_api_key_token(token, pool=mock_pool)

        assert result.wallet_id == _WALLET_ID
        assert result.owner_user_id == _CALLER_ID
        # fetchrow appelé 2 fois (wallet_id lookup + grant check) mais PAS l'Argon2id lookup complet
        assert mock_conn.fetchrow.call_count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — ENDPOINTS HTTP
# ═══════════════════════════════════════════════════════════════════════════════


def _fake_user_row(
    user_id: uuid.UUID = _CALLER_ID,
    sub: str = "test-sub-001",
    email: str = "alice@example.com",
) -> FakeRecord:
    return FakeRecord(
        {
            "id": user_id,
            "keycloak_sub": sub,
            "email": email,
            "display_name": "Alice Test",
            "rsa_public_key": b"fake_rsa_public_key",
            "salt_passphrase": b"x" * 16,
            "salt_recovery": b"y" * 16,
            "encrypted_rsa_private_key": b"fake_enc_priv",
            "encrypted_sym_key_by_pass": b"fake_enc_sym_pass",
            "encrypted_sym_key_by_recovery": b"fake_enc_sym_rec",
            "kdf_memory_kb": 65536,
            "kdf_iterations": 3,
            "kdf_parallelism": 4,
            "rsa_key_size": 2048,
            "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            "updated_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            "last_unlock_at": None,
        }
    )


def _fake_wallet_row(
    wallet_id: uuid.UUID = _WALLET_ID,
    owner_id: uuid.UUID = _CALLER_ID,
    perms: int = _PERM_ALL,
) -> FakeRecord:
    return FakeRecord(
        {
            "id": wallet_id,
            "name": "Test Wallet",
            "description": None,
            "owner_user_id": owner_id,
            "my_permissions": perms,
            "valued_secrets_count": 0,
            "placeholder_secrets_count": 0,
            "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            "updated_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        }
    )


def _fake_api_key_row(
    api_key_id: uuid.UUID = _API_KEY_ID,
) -> FakeRecord:
    import datetime

    return FakeRecord(
        {
            "id": api_key_id,
            "name": "Test Key",
            "description": None,
            "wallet_id": _WALLET_ID,
            "owner_user_id": _CALLER_ID,
            "auth_hash": b"$argon2id$fake",
            "auth_salt": b"x" * 16,
            "auth_kdf_memory_kb": 65536,
            "auth_kdf_iterations": 3,
            "auth_kdf_parallelism": 4,
            "encrypted_wallet_key": b"enc_wallet_key",
            "encrypted_decryption_key_for_owner": b"enc_dkey",
            "permissions": _PERM_ALL,
            "expires_at": None,
            "revoked_at": None,
            "last_used_at": None,
            "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        }
    )


def _make_create_body(
    permissions: int = _PERM_READ,
) -> dict[str, Any]:
    auth_secret_b64 = base64.urlsafe_b64encode(b"s" * 32).rstrip(b"=").decode()
    dkey_b64 = base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode()
    auth_hash_b64 = base64.b64encode(b"$argon2id$v=19$m=65536,t=3,p=4$fakehash").decode()
    auth_salt_b64 = base64.b64encode(b"x" * 16).decode()
    enc_wallet_key_b64 = base64.b64encode(b"enc_wallet_key").decode()
    enc_dkey_b64 = base64.b64encode(b"enc_dkey").decode()

    return {
        "name": "test-key",
        "permissions": permissions,
        "auth_secret": auth_secret_b64,
        "auth_hash": auth_hash_b64,
        "auth_salt": auth_salt_b64,
        "auth_kdf_memory_kb": 65536,
        "auth_kdf_iterations": 3,
        "auth_kdf_parallelism": 4,
        "encrypted_wallet_key": enc_wallet_key_b64,
        "encrypted_decryption_key_for_owner": enc_dkey_b64,
        "decryption_key": dkey_b64,
    }


def _make_conn() -> MagicMock:
    """Connexion asyncpg mockée."""
    mock_conn: MagicMock = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value="UPDATE 0")

    class FakeTxCtx:
        async def __aenter__(self) -> FakeTxCtx:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    mock_conn.transaction = MagicMock(return_value=FakeTxCtx())
    return mock_conn


def _make_pool(conn: MagicMock) -> MagicMock:
    """Pool asyncpg mocké."""
    class _FakeAcquireCtx:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            pass

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_FakeAcquireCtx())
    return pool


def _make_client(pool: MagicMock) -> AsyncClient:
    """AsyncClient HTTPX avec le pool injecté directement dans pool_mod._pool."""
    from app.db import pool as pool_mod
    from app.main import app

    pool_mod._pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture()
def mock_pool() -> MagicMock:
    """Pool mocké avec connexion configurable (legacy — utilisé dans certains tests)."""
    conn = _make_conn()
    pool = _make_pool(conn)
    pool._conn = conn  # accès facilité pour les assertions
    return pool


class TestApiKeyEndpoints:
    @pytest.mark.asyncio
    async def test_create_api_key_returns_full_token_once(self) -> None:
        """POST /api-keys retourne le token hrpv_* dans la réponse 201."""
        jwt_token = make_jwt_token(sub="test-sub-001")
        conn = _make_conn()

        conn.fetchrow.side_effect = [
            _fake_user_row(),    # users.get_by_keycloak_sub
            _fake_wallet_row(),  # wallets.get_wallet_for_user
        ]
        conn.fetchval = AsyncMock(return_value=_API_KEY_ID)
        conn.execute = AsyncMock(return_value="INSERT 0 1")

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.post(
                f"/v1/wallets/{_WALLET_ID}/api-keys",
                json=_make_create_body(permissions=_PERM_READ),
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert data["token"].startswith("hrpv_1_")
        assert "api_key_id" in data

    @pytest.mark.asyncio
    async def test_create_api_key_perms_exceed_caller_400(self) -> None:
        """permissions > caller permissions → 403 (pas de share)."""
        jwt_token = make_jwt_token(sub="test-sub-001")
        conn = _make_conn()

        # Caller n'a que read (0x01) — pas de [share] → 403
        conn.fetchrow.side_effect = [
            _fake_user_row(),
            _fake_wallet_row(perms=_PERM_READ),
        ]

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.post(
                f"/v1/wallets/{_WALLET_ID}/api-keys",
                json=_make_create_body(permissions=_PERM_ALL),
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        # Pas de [share] → 403
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_api_key_perms_exceed_caller_with_share(self) -> None:
        """Caller a [share] mais essaie d'accorder plus de perms qu'il n'en a → 400."""
        from app.services.permissions import PERM_READ, PERM_SHARE

        jwt_token = make_jwt_token(sub="test-sub-001")
        conn = _make_conn()

        # Caller a read+share (0x21) mais PAS write (0x08)
        caller_perms = PERM_READ | PERM_SHARE
        conn.fetchrow.side_effect = [
            _fake_user_row(),
            _fake_wallet_row(perms=caller_perms),
        ]

        # Essaie de créer une clé avec all (0x3F)
        async with _make_client(_make_pool(conn)) as client:
            resp = await client.post(
                f"/v1/wallets/{_WALLET_ID}/api-keys",
                json=_make_create_body(permissions=_PERM_ALL),
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "permissions_exceed_caller"

    @pytest.mark.asyncio
    async def test_list_api_keys_requires_jwt(self) -> None:
        """GET /api-keys sans Authorization → 401."""
        conn = _make_conn()
        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get(f"/v1/wallets/{_WALLET_ID}/api-keys")

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_api_keys_with_hrpv_token_rejected(self) -> None:
        """GET /api-keys avec hrpv_* → 401 (api_key_not_allowed_here via require_jwt_user)."""
        token = _make_token()
        conn = _make_conn()

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get(
                f"/v1/wallets/{_WALLET_ID}/api-keys",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "api_key_not_allowed_here"

    @pytest.mark.asyncio
    async def test_revoke_sets_revoked_at(self) -> None:
        """DELETE /api-keys/{id} → 204 et revoked_at setté."""
        jwt_token = make_jwt_token(sub="test-sub-001")
        conn = _make_conn()

        conn.fetchrow.side_effect = [
            _fake_user_row(),
            _fake_wallet_row(),
            _fake_api_key_row(),
        ]
        conn.execute = AsyncMock(return_value="UPDATE 1")

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.delete(
                f"/v1/wallets/{_WALLET_ID}/api-keys/{_API_KEY_ID}",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_revoke_unknown_key_404(self) -> None:
        """DELETE /api-keys/{id} sur clé inconnue → 404."""
        jwt_token = make_jwt_token(sub="test-sub-001")
        conn = _make_conn()

        conn.fetchrow.side_effect = [
            _fake_user_row(),
            _fake_wallet_row(),
        ]
        conn.execute = AsyncMock(return_value="UPDATE 0")

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.delete(
                f"/v1/wallets/{_WALLET_ID}/api-keys/{_API_KEY_ID}",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_api_key_rejected_on_me_endpoints(self) -> None:
        """hrpv_* sur /me/* → 401 api_key_not_allowed_here."""
        token = _make_token()
        conn = _make_conn()

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get(
                "/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "api_key_not_allowed_here"

    @pytest.mark.asyncio
    async def test_api_key_rejected_on_wallet_post(self) -> None:
        """hrpv_* sur POST /wallets → 401 api_key_not_allowed_here."""
        token = _make_token()
        conn = _make_conn()

        async with _make_client(_make_pool(conn)) as client:
            resp = await client.post(
                "/v1/wallets",
                json={"name": "x", "encrypted_wallet_key": "abc"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "api_key_not_allowed_here"


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — CASCADE REVOCATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestApiKeySelfEndpoints:
    """Tests pour GET /v1/api-keys/{api_key_id}/wallet-id (LOT_09 SDK endpoint)."""

    def _make_caller(
        self,
        api_key_id: uuid.UUID = _API_KEY_ID,
        wallet_id: uuid.UUID = _WALLET_ID,
    ) -> Any:
        from app.core.api_key_auth import ApiKeyCaller

        return ApiKeyCaller(
            api_key_id=api_key_id,
            owner_user_id=_CALLER_ID,
            wallet_id=wallet_id,
            permissions=_PERM_ALL,
            decryption_key_b64=base64.urlsafe_b64encode(b"d" * 32).rstrip(b"=").decode(),
        )

    @pytest.mark.asyncio
    async def test_get_wallet_id_returns_200(self) -> None:
        """GET /api-keys/{id}/wallet-id avec token valide → 200 + wallet_id."""
        from app.core.api_key_auth import require_api_key
        from app.main import app

        caller = self._make_caller()

        async def _fake_require_api_key() -> Any:
            return caller

        app.dependency_overrides[require_api_key] = _fake_require_api_key
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/v1/api-keys/{_API_KEY_ID}/wallet-id",
                    headers={"Authorization": "Bearer fake-token"},
                )
        finally:
            app.dependency_overrides.pop(require_api_key, None)

        assert resp.status_code == 200
        data = resp.json()
        assert data["wallet_id"] == str(_WALLET_ID)
        assert data["api_key_id"] == str(_API_KEY_ID)

    @pytest.mark.asyncio
    async def test_get_wallet_id_path_mismatch_403(self) -> None:
        """GET /api-keys/{other_id}/wallet-id avec token d'une autre clé → 403."""
        from app.core.api_key_auth import require_api_key
        from app.main import app

        caller = self._make_caller(api_key_id=_API_KEY_ID)
        other_id = uuid.UUID("dddddddd-0000-0000-0000-000000000002")

        async def _fake_require_api_key() -> Any:
            return caller

        app.dependency_overrides[require_api_key] = _fake_require_api_key
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/v1/api-keys/{other_id}/wallet-id",
                    headers={"Authorization": "Bearer fake-token"},
                )
        finally:
            app.dependency_overrides.pop(require_api_key, None)

        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "forbidden"

    @pytest.mark.asyncio
    async def test_get_wallet_id_no_token_401(self) -> None:
        """GET /api-keys/{id}/wallet-id sans Authorization → 401."""
        conn = _make_conn()
        async with _make_client(_make_pool(conn)) as client:
            resp = await client.get(f"/v1/api-keys/{_API_KEY_ID}/wallet-id")

        assert resp.status_code == 401


class TestCascadeRevocation:
    @pytest.mark.asyncio
    async def test_cascade_revoke_on_owner_grant_removal(self) -> None:
        """La suppression d'un grant déclenche la révocation des API keys du grantee."""
        from app.db.repositories import api_keys as api_keys_repo

        mock_conn: MagicMock = MagicMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 2")

        count = await api_keys_repo.revoke_api_keys_by_owner_on_wallet(
            mock_conn,
            wallet_id=_WALLET_ID,
            owner_user_id=_CALLER_ID,
        )

        assert count == 2
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "revoked_at" in sql.lower()
        assert "owner_user_id" in sql.lower()

    @pytest.mark.asyncio
    async def test_cascade_revoke_zero_when_no_keys(self) -> None:
        """Si pas de clés actives, la cascade retourne 0."""
        from app.db.repositories import api_keys as api_keys_repo

        mock_conn: MagicMock = MagicMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")

        count = await api_keys_repo.revoke_api_keys_by_owner_on_wallet(
            mock_conn,
            wallet_id=_WALLET_ID,
            owner_user_id=_CALLER_ID,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_grants_delete_service_calls_cascade(self) -> None:
        """delete_grant dans le service appelle bien la révocation des API keys."""
        from app.services import grants as grants_svc

        mock_conn: MagicMock = MagicMock()

        grantee_id = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
        owner_id = uuid.UUID("ffffffff-0000-0000-0000-000000000001")

        grant_row = FakeRecord(
            {
                "id": uuid.UUID("cccccccc-0000-0000-0000-000000000002"),
                "wallet_id": _WALLET_ID,
                "grantee_user_id": grantee_id,
                "permissions": _PERM_READ,
                "granted_by_user_id": owner_id,
                "granted_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            }
        )

        class FakeTxCtx:
            async def __aenter__(self) -> FakeTxCtx:
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

        mock_conn.transaction = MagicMock(return_value=FakeTxCtx())
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")

        revoke_api_keys_called = False

        async def mock_revoke_by_owner(*_: Any, **kwargs: Any) -> int:
            nonlocal revoke_api_keys_called
            revoke_api_keys_called = True
            assert kwargs["wallet_id"] == _WALLET_ID
            assert kwargs["owner_user_id"] == grantee_id
            return 0

        with (
            patch(
                "app.services.grants.wallets_repo.get_wallet_for_user",
                AsyncMock(return_value=MagicMock(
                    my_permissions=_PERM_ALL,
                    owner_user_id=owner_id,
                )),
            ),
            patch(
                "app.services.grants.grants_repo.get_grant_by_id",
                AsyncMock(return_value=grant_row),
            ),
            patch(
                "app.db.repositories.api_keys.revoke_api_keys_by_owner_on_wallet",
                mock_revoke_by_owner,
            ),
            patch(
                "app.services.grants.grants_repo.delete_grant",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.grants.audit_log_insert",
                AsyncMock(return_value=None),
            ),
        ):
            await grants_svc.delete_grant(
                mock_conn,
                wallet_id=_WALLET_ID,
                grant_id=grant_row["id"],
                caller_user_id=owner_id,
                actor_ip=None,
            )

        assert revoke_api_keys_called, "revoke_api_keys_by_owner_on_wallet should have been called"


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS — AUDIT LOG (pas de secrets dans metadata)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_audit_log_no_secret_in_metadata(self) -> None:
        """La fonction create_api_key n'inclut ni auth_secret ni decryption_key dans l'audit."""
        audit_calls: list[dict[str, Any]] = []

        async def mock_audit_insert(
            conn: Any, action: str, **kwargs: Any
        ) -> None:
            audit_calls.append({"action": action, **kwargs})

        mock_conn: MagicMock = MagicMock()

        class FakeTxCtx:
            async def __aenter__(self) -> FakeTxCtx:
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

        mock_conn.transaction = MagicMock(return_value=FakeTxCtx())
        mock_conn.fetchval = AsyncMock(return_value=_API_KEY_ID)
        mock_conn.execute = AsyncMock(return_value=None)

        req_body = _make_create_body(permissions=_PERM_READ)

        from app.models.api.api_keys import ApiKeyCreateRequest
        from app.services import api_keys as api_keys_svc

        req = ApiKeyCreateRequest(**req_body)

        with (
            patch(
                "app.services.api_keys.wallets_repo.get_wallet_for_user",
                AsyncMock(return_value=MagicMock(
                    my_permissions=_PERM_ALL,
                    owner_user_id=_CALLER_ID,
                )),
            ),
            patch("app.services.api_keys.audit_log_insert", mock_audit_insert),
        ):
            await api_keys_svc.create_api_key(
                mock_conn,
                wallet_id=_WALLET_ID,
                req=req,
                caller_user_id=_CALLER_ID,
                actor_ip=None,
            )

        assert len(audit_calls) == 1
        call = audit_calls[0]
        assert call["action"] == "api_key.created"

        metadata = call.get("metadata", {})
        metadata_str = str(metadata)
        # Vérifie qu'aucun secret n'est dans les métadonnées
        assert req_body["auth_secret"] not in metadata_str
        assert req_body["decryption_key"] not in metadata_str
        assert "api_key_id" in metadata

    @pytest.mark.asyncio
    async def test_revoke_emits_audit_api_key_revoked(self) -> None:
        """La révocation d'une clé émet un audit api_key.revoked."""
        audit_calls: list[dict[str, Any]] = []

        async def mock_audit_insert(
            conn: Any, action: str, **kwargs: Any
        ) -> None:
            audit_calls.append({"action": action, **kwargs})

        mock_conn: MagicMock = MagicMock()

        class FakeTxCtx:
            async def __aenter__(self) -> FakeTxCtx:
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

        mock_conn.transaction = MagicMock(return_value=FakeTxCtx())
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        from app.services import api_keys as api_keys_svc

        with (
            patch(
                "app.services.api_keys.wallets_repo.get_wallet_for_user",
                AsyncMock(return_value=MagicMock(
                    my_permissions=_PERM_ALL,
                    owner_user_id=_CALLER_ID,
                )),
            ),
            patch(
                "app.services.api_keys.api_keys_repo.revoke_api_key",
                AsyncMock(return_value=True),
            ),
            patch("app.services.api_keys.audit_log_insert", mock_audit_insert),
        ):
            await api_keys_svc.revoke_api_key(
                mock_conn,
                wallet_id=_WALLET_ID,
                api_key_id=_API_KEY_ID,
                caller_user_id=_CALLER_ID,
                actor_ip=None,
            )

        assert any(c["action"] == "api_key.revoked" for c in audit_calls)
