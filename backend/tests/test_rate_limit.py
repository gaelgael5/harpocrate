"""Rate limiting applicatif — S-5 du rapport d'audit.

Tests :
- `_key_by_ip` privilégie `X-Forwarded-For` quand présent, fallback `request.client.host`.
- `_parse_limits` accepte le format `"5/minute;100/hour"` (cumul).
- La dépendance `rate_limit_dep` est no-op quand `rate_limit_enabled=False`.
- Quand le storage est vide et le limiter activé, un appel passe ; au-delà
  de N appels (avec une limite N/period), un appel lève `HTTPException(429)`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request


def test_key_by_ip_uses_x_forwarded_for_first_ip() -> None:
    from app.core.rate_limit import _key_by_ip

    request = MagicMock(spec=Request)
    request.headers = {"X-Forwarded-For": "203.0.113.42, 10.0.0.1, 127.0.0.1"}
    request.client = MagicMock(host="127.0.0.1")

    assert _key_by_ip(request) == "203.0.113.42"


def test_key_by_ip_falls_back_to_remote_addr_without_xff() -> None:
    from app.core.rate_limit import _key_by_ip

    request = MagicMock(spec=Request)
    request.headers = {}
    request.client = MagicMock(host="198.51.100.7")

    assert _key_by_ip(request) == "198.51.100.7"


def test_key_by_ip_handles_empty_x_forwarded_for() -> None:
    from app.core.rate_limit import _key_by_ip

    request = MagicMock(spec=Request)
    request.headers = {"X-Forwarded-For": "  "}
    request.client = MagicMock(host="192.0.2.100")

    assert _key_by_ip(request) == "192.0.2.100"


def test_key_by_ip_returns_unknown_when_no_client() -> None:
    from app.core.rate_limit import _key_by_ip

    request = MagicMock(spec=Request)
    request.headers = {}
    request.client = None

    assert _key_by_ip(request) == "unknown"


def test_parse_limits_single_window() -> None:
    from app.core.rate_limit import _parse_limits

    items = _parse_limits("5/minute")
    assert len(items) == 1
    assert items[0].amount == 5


def test_parse_limits_cumulated_windows() -> None:
    """Format `"10/minute;100/hour"` retourne deux items."""
    from app.core.rate_limit import _parse_limits

    items = _parse_limits("10/minute;100/hour")
    assert len(items) == 2
    assert items[0].amount == 10
    assert items[1].amount == 100


def test_rate_limit_dep_no_op_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avec `rate_limit_enabled=False`, la dépendance ne lève jamais."""
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", False)
    dep = rate_limit.rate_limit_dep("1/second")

    request = MagicMock(spec=Request)
    request.headers = {}
    request.client = MagicMock(host="10.0.0.1")
    request.url = MagicMock(path="/v1/test")

    # Appels successifs : aucun ne lève
    for _ in range(20):
        dep(request)


def test_rate_limit_dep_blocks_when_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avec limiter activé, N+1 appels sur la même IP → 429 sur le (N+1)e."""
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    # Reset le storage pour partir d'un état propre
    rate_limit.reset_in_memory_storage()

    dep = rate_limit.rate_limit_dep("3/minute")

    request = MagicMock(spec=Request)
    request.headers = {"X-Forwarded-For": "10.10.10.10"}
    request.client = MagicMock(host="127.0.0.1")
    request.url = MagicMock(path="/v1/test-rate-limit-1")

    # 3 premiers passent
    for _ in range(3):
        dep(request)

    # 4e lève
    with pytest.raises(HTTPException) as exc_info:
        dep(request)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "rate_limit_exceeded"
    assert exc_info.value.headers.get("Retry-After") == "60"


def test_rate_limit_dep_buckets_by_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deux IPs différentes ne partagent pas le même compteur."""
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    rate_limit.reset_in_memory_storage()

    dep = rate_limit.rate_limit_dep("2/minute")

    req_a = MagicMock(spec=Request)
    req_a.headers = {"X-Forwarded-For": "1.1.1.1"}
    req_a.client = MagicMock(host="127.0.0.1")
    req_a.url = MagicMock(path="/v1/test-bucket")

    req_b = MagicMock(spec=Request)
    req_b.headers = {"X-Forwarded-For": "2.2.2.2"}
    req_b.client = MagicMock(host="127.0.0.1")
    req_b.url = MagicMock(path="/v1/test-bucket")

    # IP A : 2 appels = OK
    dep(req_a)
    dep(req_a)
    # IP B : 2 appels = OK (bucket distinct)
    dep(req_b)
    dep(req_b)

    # IP A : 3e appel = 429
    with pytest.raises(HTTPException):
        dep(req_a)
    # IP B : 3e appel aussi = 429 (le bucket de B a aussi 2 hits)
    with pytest.raises(HTTPException):
        dep(req_b)


def test_rate_limit_dep_buckets_by_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deux routes différentes ne partagent pas le même compteur."""
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    rate_limit.reset_in_memory_storage()

    dep = rate_limit.rate_limit_dep("2/minute")

    req_a = MagicMock(spec=Request)
    req_a.headers = {"X-Forwarded-For": "5.5.5.5"}
    req_a.client = MagicMock(host="127.0.0.1")
    req_a.url = MagicMock(path="/v1/path-a")

    req_b = MagicMock(spec=Request)
    req_b.headers = {"X-Forwarded-For": "5.5.5.5"}  # même IP !
    req_b.client = MagicMock(host="127.0.0.1")
    req_b.url = MagicMock(path="/v1/path-b")

    # Même IP, paths différents : 2 hits par path = OK
    dep(req_a)
    dep(req_a)
    dep(req_b)
    dep(req_b)

    # Cap atteint sur path-a
    with pytest.raises(HTTPException):
        dep(req_a)
    # path-b indépendant : cap aussi atteint
    with pytest.raises(HTTPException):
        dep(req_b)
