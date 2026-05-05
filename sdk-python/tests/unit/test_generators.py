"""Tests des 9 générateurs — LOT_09 SDK."""

from __future__ import annotations

import json
import re
import string
import uuid

import pytest

from harpocrate.exceptions import GeneratorError
from harpocrate.generators import dispatch


class TestRandomGenerator:
    """Tests du générateur 'random'."""

    def test_alphanum_length(self) -> None:
        """Génère exactement la longueur demandée en alphanum."""
        result = dispatch({"type": "random", "length": 32, "charset": "alphanum"})
        assert len(result) == 32

    def test_alphanum_chars(self) -> None:
        """Tous les chars sont alphanumériques."""
        result = dispatch({"type": "random", "length": 100, "charset": "alphanum"})
        assert all(c in string.ascii_letters + string.digits for c in result)

    def test_hex_charset(self) -> None:
        """Le charset 'hex' produit des chars hexadécimaux."""
        result = dispatch({"type": "random", "length": 32, "charset": "hex"})
        assert all(c in string.hexdigits[:16] for c in result)
        assert len(result) == 32

    def test_numeric_charset(self) -> None:
        """Le charset 'numeric' produit des chiffres."""
        result = dispatch({"type": "random", "length": 20, "charset": "numeric"})
        assert result.isdigit()

    def test_base64url_charset(self) -> None:
        """Le charset 'base64url' produit des chars base64url."""
        valid = set(string.ascii_letters + string.digits + "-_")
        result = dispatch({"type": "random", "length": 32, "charset": "base64url"})
        assert all(c in valid for c in result)

    def test_custom_charset(self) -> None:
        """Un charset custom est respecté."""
        result = dispatch({"type": "random", "length": 20, "charset": "abcd"})
        assert all(c in "abcd" for c in result)
        assert len(result) == 20

    def test_custom_charset_too_short(self) -> None:
        """Un charset custom trop court (<4 chars) lève GeneratorError."""
        with pytest.raises(GeneratorError):
            dispatch({"type": "random", "length": 10, "charset": "ab"})

    def test_different_calls_differ(self) -> None:
        """Deux appels successifs produisent des résultats différents (avec haute probabilité)."""
        r1 = dispatch({"type": "random", "length": 32})
        r2 = dispatch({"type": "random", "length": 32})
        # P(collision) = (62^32)^{-1} ≈ 0 — si égal, le test est faux-positif
        assert r1 != r2


class TestUuidGenerator:
    """Tests du générateur 'uuid'."""

    def test_uuid4_format(self) -> None:
        """Un UUID v4 a le format standard 36 chars."""
        result = dispatch({"type": "uuid", "version": 4})
        assert len(result) == 36
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            result,
        ), f"Not a valid UUID4: {result}"

    def test_uuid4_parseable(self) -> None:
        """Le résultat peut être parsé par uuid.UUID."""
        result = dispatch({"type": "uuid", "version": 4})
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_uuid4_default_version(self) -> None:
        """La version 4 est la valeur par défaut."""
        result = dispatch({"type": "uuid"})
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_uuid7_format(self) -> None:
        """Un UUID v7 a 36 chars."""
        result = dispatch({"type": "uuid", "version": 7})
        assert len(result) == 36

    def test_uuid7_version_bit(self) -> None:
        """Le bit de version d'un UUID v7 est 7."""
        result = dispatch({"type": "uuid", "version": 7})
        parsed = uuid.UUID(result)
        # Le nibble de version est dans les bits 76-79 (high word, byte 6 nibble haut)
        version_nibble = (parsed.int >> 76) & 0xF
        assert version_nibble == 7

    def test_uuid7_monotone(self) -> None:
        """Deux UUID v7 consécutifs sont ordonnés (timestamps croissants)."""
        import time

        r1 = dispatch({"type": "uuid", "version": 7})
        time.sleep(0.001)
        r2 = dispatch({"type": "uuid", "version": 7})
        # Le timestamp est dans les 48 premiers bits
        ts1 = uuid.UUID(r1).int >> 80
        ts2 = uuid.UUID(r2).int >> 80
        assert ts2 >= ts1

    def test_unsupported_version(self) -> None:
        """Une version non supportée lève ValueError."""
        with pytest.raises((ValueError, GeneratorError)):
            dispatch({"type": "uuid", "version": 1})


class TestBytesGenerator:
    """Tests du générateur 'bytes'."""

    def test_base64url_encoding(self) -> None:
        """L'encodage base64url ne contient pas de '+', '/', ni de padding '='."""
        result = dispatch({"type": "bytes", "length": 32, "encoding": "base64url"})
        assert "+" not in result
        assert "/" not in result
        assert "=" not in result

    def test_hex_encoding(self) -> None:
        """L'encodage hex produit uniquement 0-9a-f."""
        result = dispatch({"type": "bytes", "length": 16, "encoding": "hex"})
        assert re.match(r"^[0-9a-f]+$", result)
        assert len(result) == 32  # 16 bytes → 32 chars hex

    def test_default_encoding_is_base64url(self) -> None:
        """L'encodage par défaut est base64url."""
        result = dispatch({"type": "bytes", "length": 8})
        assert "+" not in result
        assert "/" not in result

    def test_different_calls_differ(self) -> None:
        """Deux appels successifs produisent des données différentes."""
        r1 = dispatch({"type": "bytes", "length": 32})
        r2 = dispatch({"type": "bytes", "length": 32})
        assert r1 != r2

    def test_unsupported_encoding(self) -> None:
        """Un encodage non supporté lève ValueError."""
        with pytest.raises((ValueError, GeneratorError)):
            dispatch({"type": "bytes", "length": 8, "encoding": "base58"})


class TestPassphraseGenerator:
    """Tests du générateur 'passphrase'."""

    def test_word_count(self) -> None:
        """Le nombre de mots correspond au descripteur."""
        result = dispatch({"type": "passphrase", "words": 4, "separator": "-"})
        assert len(result.split("-")) == 4

    def test_default_separator(self) -> None:
        """Le séparateur par défaut est '-'."""
        result = dispatch({"type": "passphrase", "words": 5})
        assert "-" in result
        assert len(result.split("-")) == 5

    def test_custom_separator(self) -> None:
        """Un séparateur custom est respecté."""
        result = dispatch({"type": "passphrase", "words": 3, "separator": "."})
        parts = result.split(".")
        assert len(parts) == 3

    def test_words_are_lowercase(self) -> None:
        """Les mots sont en minuscules (wordlist EFF standard)."""
        result = dispatch({"type": "passphrase", "words": 6, "language": "en"})
        for word in result.split("-"):
            assert word == word.lower(), f"Word not lowercase: {word!r}"

    def test_french_language(self) -> None:
        """La langue française fonctionne."""
        result = dispatch({"type": "passphrase", "words": 4, "language": "fr"})
        assert len(result.split("-")) == 4

    def test_different_calls_differ(self) -> None:
        """Deux passphrases consécutives sont différentes."""
        r1 = dispatch({"type": "passphrase", "words": 6})
        r2 = dispatch({"type": "passphrase", "words": 6})
        assert r1 != r2


class TestTemplateGenerator:
    """Tests du générateur 'template'."""

    def test_literal_substitution(self) -> None:
        """Les valeurs littérales sont substituées correctement."""
        result = dispatch(
            {
                "type": "template",
                "template": "{user}:{pass}@{host}",
                "variables": {
                    "user": {"literal": "admin"},
                    "pass": {"literal": "secret"},
                    "host": {"literal": "db.example.com"},
                },
            }
        )
        assert result == "admin:secret@db.example.com"

    def test_generated_variable_substituted(self) -> None:
        """Une variable générée est substituée correctement."""
        result = dispatch(
            {
                "type": "template",
                "template": "prefix-{suffix}",
                "variables": {
                    "suffix": {"type": "random", "length": 8, "charset": "hex"},
                },
            }
        )
        assert result.startswith("prefix-")
        suffix = result[7:]
        assert len(suffix) == 8
        assert re.match(r"^[0-9a-f]+$", suffix)

    def test_recursive_template_rejected(self) -> None:
        """Un template récursif (variable de type template) est rejeté."""
        with pytest.raises(GeneratorError):
            dispatch(
                {
                    "type": "template",
                    "template": "{inner}",
                    "variables": {
                        "inner": {
                            "type": "template",
                            "template": "nested",
                            "variables": {},
                        },
                    },
                }
            )

    def test_missing_variable_raises(self) -> None:
        """Un placeholder sans variable définie lève GeneratorError."""
        with pytest.raises(GeneratorError):
            dispatch(
                {
                    "type": "template",
                    "template": "{defined}-{undefined}",
                    "variables": {"defined": {"literal": "ok"}},
                }
            )


class TestRsaKeypairGenerator:
    """Tests du générateur 'rsa_keypair'."""

    def test_pem_format_returns_json(self) -> None:
        """Le format PEM retourne un JSON avec 'private' et 'public'."""
        result = dispatch({"type": "rsa_keypair", "key_size": 2048, "format": "pem"})
        data = json.loads(result)
        assert "private" in data
        assert "public" in data

    def test_pem_private_key_header(self) -> None:
        """La clé privée PEM commence par le header correct."""
        result = dispatch({"type": "rsa_keypair", "key_size": 2048, "format": "pem"})
        data = json.loads(result)
        assert data["private"].startswith("-----BEGIN PRIVATE KEY-----")

    def test_pem_public_key_header(self) -> None:
        """La clé publique PEM commence par le header correct."""
        result = dispatch({"type": "rsa_keypair", "key_size": 2048, "format": "pem"})
        data = json.loads(result)
        assert data["public"].startswith("-----BEGIN PUBLIC KEY-----")

    def test_openssh_format(self) -> None:
        """Le format OpenSSH retourne un JSON avec clés OpenSSH."""
        result = dispatch({"type": "rsa_keypair", "key_size": 2048, "format": "openssh"})
        data = json.loads(result)
        assert data["public"].startswith("ssh-rsa ")

    def test_default_key_size_4096(self) -> None:
        """La taille de clé par défaut est 4096."""
        result = dispatch({"type": "rsa_keypair"})
        data = json.loads(result)
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        key = load_pem_private_key(data["private"].encode(), password=None)
        assert isinstance(key, RSAPrivateKey)
        assert key.key_size == 4096

    def test_roundtrip_key_match(self) -> None:
        """La clé publique correspond à la clé privée."""
        result = dispatch({"type": "rsa_keypair", "key_size": 2048, "format": "pem"})
        data = json.loads(result)
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            load_pem_private_key,
        )

        priv = load_pem_private_key(data["private"].encode(), password=None)
        assert isinstance(priv, RSAPrivateKey)
        pub_from_priv = (
            priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
        )
        assert pub_from_priv == data["public"]


class TestSshKeypairGenerator:
    """Tests du générateur 'ssh_keypair'."""

    def test_ed25519_returns_json(self) -> None:
        """ED25519 retourne un JSON avec 'private' et 'public'."""
        result = dispatch({"type": "ssh_keypair", "algorithm": "ed25519"})
        data = json.loads(result)
        assert "private" in data
        assert "public" in data

    def test_ed25519_public_key_format(self) -> None:
        """La clé publique ED25519 commence par 'ssh-ed25519'."""
        result = dispatch({"type": "ssh_keypair", "algorithm": "ed25519"})
        data = json.loads(result)
        assert data["public"].startswith("ssh-ed25519 ")

    def test_ed25519_private_key_format(self) -> None:
        """La clé privée ED25519 est en format OpenSSH PEM."""
        result = dispatch({"type": "ssh_keypair", "algorithm": "ed25519"})
        data = json.loads(result)
        assert "OPENSSH PRIVATE KEY" in data["private"]

    def test_rsa_algorithm(self) -> None:
        """L'algorithme RSA génère une clé RSA OpenSSH."""
        result = dispatch({"type": "ssh_keypair", "algorithm": "rsa"})
        data = json.loads(result)
        assert data["public"].startswith("ssh-rsa ")

    def test_default_algorithm_ed25519(self) -> None:
        """L'algorithme par défaut est ed25519."""
        result = dispatch({"type": "ssh_keypair"})
        data = json.loads(result)
        assert data["public"].startswith("ssh-ed25519 ")

    def test_ed25519_key_loadable(self) -> None:
        """La clé ED25519 peut être rechargée par cryptography (format OpenSSH)."""
        result = dispatch({"type": "ssh_keypair", "algorithm": "ed25519"})
        data = json.loads(result)
        from cryptography.hazmat.primitives.serialization import load_ssh_private_key

        key = load_ssh_private_key(data["private"].encode(), password=None)
        assert key is not None


class TestTlsCertificateGenerator:
    """Tests du générateur 'tls_certificate'."""

    def test_returns_json(self) -> None:
        """Retourne un JSON avec 'certificate' et 'private_key'."""
        result = dispatch(
            {
                "type": "tls_certificate",
                "common_name": "test.example.com",
            }
        )
        data = json.loads(result)
        assert "certificate" in data
        assert "private_key" in data

    def test_certificate_pem_format(self) -> None:
        """Le certificat est en format PEM."""
        result = dispatch(
            {
                "type": "tls_certificate",
                "common_name": "test.example.com",
            }
        )
        data = json.loads(result)
        assert data["certificate"].startswith("-----BEGIN CERTIFICATE-----")

    def test_private_key_pem_format(self) -> None:
        """La clé privée est en format PEM."""
        result = dispatch(
            {
                "type": "tls_certificate",
                "common_name": "test.example.com",
            }
        )
        data = json.loads(result)
        assert data["private_key"].startswith("-----BEGIN PRIVATE KEY-----")

    def test_self_signed_validity(self) -> None:
        """Le certificat est valide (auto-signé)."""
        result = dispatch(
            {
                "type": "tls_certificate",
                "common_name": "test.example.com",
                "validity_days": 365,
            }
        )
        data = json.loads(result)
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(data["certificate"].encode())
        assert cert.subject == cert.issuer  # auto-signé

    def test_common_name_set(self) -> None:
        """Le Common Name est correctement défini."""
        result = dispatch(
            {
                "type": "tls_certificate",
                "common_name": "vault.example.org",
            }
        )
        data = json.loads(result)
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(data["certificate"].encode())
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        assert cn == "vault.example.org"

    def test_subject_alt_names(self) -> None:
        """Les SANs sont correctement inclus dans le certificat."""
        result = dispatch(
            {
                "type": "tls_certificate",
                "common_name": "example.com",
                "subject_alt_names": ["www.example.com", "api.example.com"],
            }
        )
        data = json.loads(result)
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(data["certificate"].encode())
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san_ext.value.get_values_for_type(x509.DNSName)
        assert "www.example.com" in dns_names
        assert "api.example.com" in dns_names


class TestBcryptPasswordGenerator:
    """Tests du générateur 'bcrypt_password'."""

    def test_returns_json(self) -> None:
        """Retourne un JSON avec 'plain' et 'hash'."""
        result = dispatch({"type": "bcrypt_password", "length": 16, "rounds": 4})
        data = json.loads(result)
        assert "plain" in data
        assert "hash" in data

    def test_hash_is_bcrypt(self) -> None:
        """Le hash commence par le préfixe bcrypt '$2b$'."""
        result = dispatch({"type": "bcrypt_password", "rounds": 4})
        data = json.loads(result)
        assert data["hash"].startswith("$2b$")

    def test_hash_verifiable(self) -> None:
        """Le hash peut être vérifié avec bcrypt.checkpw()."""
        import bcrypt

        result = dispatch({"type": "bcrypt_password", "length": 20, "rounds": 4})
        data = json.loads(result)
        assert bcrypt.checkpw(data["plain"].encode(), data["hash"].encode())

    def test_plain_length(self) -> None:
        """La longueur du mot de passe en clair correspond au descripteur."""
        result = dispatch({"type": "bcrypt_password", "length": 24, "rounds": 4})
        data = json.loads(result)
        assert len(data["plain"]) == 24

    def test_different_calls_differ(self) -> None:
        """Deux appels successifs produisent des mots de passe différents."""
        r1 = json.loads(dispatch({"type": "bcrypt_password", "rounds": 4}))
        r2 = json.loads(dispatch({"type": "bcrypt_password", "rounds": 4}))
        assert r1["plain"] != r2["plain"]
        assert r1["hash"] != r2["hash"]


class TestDispatch:
    """Tests de la table de dispatch."""

    def test_unknown_type_raises(self) -> None:
        """Un type inconnu lève GeneratorError."""
        with pytest.raises(GeneratorError, match="Unknown generator type"):
            dispatch({"type": "unknown_type_xyz"})

    def test_missing_type_raises(self) -> None:
        """Un descripteur sans 'type' lève GeneratorError."""
        with pytest.raises(GeneratorError):
            dispatch({})

    def test_all_9_types_registered(self) -> None:
        """Les 9 types de générateurs sont enregistrés."""
        from harpocrate.generators import _GENERATORS

        expected = {
            "random",
            "uuid",
            "bytes",
            "passphrase",
            "template",
            "rsa_keypair",
            "ssh_keypair",
            "tls_certificate",
            "bcrypt_password",
        }
        assert set(_GENERATORS.keys()) == expected
