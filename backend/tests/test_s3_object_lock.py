"""Object Lock S3 applicatif — S-6 du rapport d'audit.

Avant cette livraison, le paramètre `object_lock` dans la config S3 était
documenté `# info uniquement` — aucun appel `PutObjectRetention` n'était
fait, aucun `ObjectLockMode` n'était passé à boto3. Le wiki annonçait
néanmoins l'Object Lock anti-ransomware comme une fonctionnalité.

Maintenant :
- `object_lock_days: int` (≥ 1) → ajoute `ObjectLockMode=GOVERNANCE` +
  `ObjectLockRetainUntilDate = now + N days` dans `ExtraArgs` de
  `upload_fileobj`.
- `object_lock_days = 0` ou absent → pas d'override (comportement legacy).
- `object_lock: bool = True` legacy → équivalent à `object_lock_days=30`
  pour la rétrocompatibilité.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.remote_backup_providers.s3_compatible import S3CompatibleProvider


def _make_provider(config_extra: dict | None = None) -> S3CompatibleProvider:
    base_config = {
        "bucket": "harpocrate-test",
        "region": "us-east-1",
        "endpoint_url": None,
        "path_style": False,
    }
    if config_extra:
        base_config.update(config_extra)
    return S3CompatibleProvider(
        config=base_config,
        credentials={"access_key_id": "AKIA_TEST", "secret_access_key": "secret"},
    )


def test_object_lock_disabled_by_default() -> None:
    """Sans `object_lock_days`, `_build_extra_args` retourne un dict vide."""
    provider = _make_provider()
    assert provider._object_lock_days == 0
    assert provider._build_extra_args() == {}


def test_object_lock_explicit_days() -> None:
    """`object_lock_days=14` → 14 jours de rétention GOVERNANCE."""
    provider = _make_provider({"object_lock_days": 14})
    assert provider._object_lock_days == 14

    extra = provider._build_extra_args()
    assert extra["ObjectLockMode"] == "GOVERNANCE"
    retain = extra["ObjectLockRetainUntilDate"]
    assert isinstance(retain, datetime)
    expected = datetime.now(UTC) + timedelta(days=14)
    # Tolérance 5s sur le calcul de la date
    assert abs((retain - expected).total_seconds()) < 5


def test_object_lock_legacy_bool_true_defaults_to_30_days() -> None:
    """Ancien format `object_lock: true` → traite comme 30 jours par défaut."""
    provider = _make_provider({"object_lock": True})
    assert provider._object_lock_days == 30
    extra = provider._build_extra_args()
    assert extra["ObjectLockMode"] == "GOVERNANCE"


def test_object_lock_legacy_bool_false_is_disabled() -> None:
    """`object_lock: false` → comme absent : pas d'Object Lock."""
    provider = _make_provider({"object_lock": False})
    assert provider._object_lock_days == 0
    assert provider._build_extra_args() == {}


def test_object_lock_days_zero_is_disabled() -> None:
    """`object_lock_days: 0` désactive explicitement."""
    provider = _make_provider({"object_lock_days": 0})
    assert provider._object_lock_days == 0
    assert provider._build_extra_args() == {}


def test_object_lock_invalid_value_falls_back_to_zero() -> None:
    """Valeur non numérique = 0 (pas de crash, fail-safe)."""
    provider = _make_provider({"object_lock_days": "abc"})
    assert provider._object_lock_days == 0


def test_object_lock_negative_value_clamped_to_zero() -> None:
    """Valeur négative = 0."""
    provider = _make_provider({"object_lock_days": -5})
    assert provider._object_lock_days == 0


def test_object_lock_days_priority_over_legacy_bool() -> None:
    """`object_lock_days` explicite prend le dessus sur `object_lock` legacy."""
    provider = _make_provider({"object_lock_days": 7, "object_lock": True})
    assert provider._object_lock_days == 7


@pytest.mark.asyncio
async def test_upload_passes_object_lock_extra_args() -> None:
    """L'upload avec `object_lock_days > 0` passe `ExtraArgs` à boto3."""

    async def _source():
        yield b"chunk1"
        yield b"chunk2"

    captured = {}

    def _fake_client():
        client = MagicMock()

        def upload_fileobj(fileobj, bucket, key, **kwargs):
            captured["bucket"] = bucket
            captured["key"] = key
            captured["extra_args"] = kwargs.get("ExtraArgs")

        client.upload_fileobj = upload_fileobj
        return client

    provider = _make_provider({"object_lock_days": 60})

    with patch.object(provider, "_make_client", side_effect=_fake_client):
        await provider.upload_stream(
            path="snapshots/",
            remote_filename="harpocrate-2026-05-17.tar.age",
            source=_source(),
        )

    assert captured["key"] == "snapshots/harpocrate-2026-05-17.tar.age"
    extra = captured["extra_args"]
    assert extra is not None, "ExtraArgs doit être présent quand object_lock_days > 0"
    assert extra["ObjectLockMode"] == "GOVERNANCE"
    assert isinstance(extra["ObjectLockRetainUntilDate"], datetime)


@pytest.mark.asyncio
async def test_upload_omits_extra_args_when_object_lock_disabled() -> None:
    """Sans Object Lock, `upload_fileobj` est appelé sans `ExtraArgs`."""

    async def _source():
        yield b"data"

    captured = {}

    def _fake_client():
        client = MagicMock()

        def upload_fileobj(fileobj, bucket, key, **kwargs):
            captured["extra_args"] = kwargs.get("ExtraArgs")

        client.upload_fileobj = upload_fileobj
        return client

    provider = _make_provider()  # sans object_lock_days

    with patch.object(provider, "_make_client", side_effect=_fake_client):
        await provider.upload_stream(
            path="",
            remote_filename="harpocrate.tar.age",
            source=_source(),
        )

    assert captured["extra_args"] is None
