"""Tests unitaires du codec d'URL d'appairage (LOT 5 — v2)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.services.pairing_url_codec import (
    InvalidPairingUrlError,
    build_pairing_url,
    generate_token,
    parse_pairing_url,
)


def test_generate_token_is_32_hex() -> None:
    for _ in range(50):
        t = generate_token()
        assert len(t) == 32
        assert all(c in "0123456789abcdef" for c in t)


def test_generate_token_returns_distinct_values() -> None:
    tokens = {generate_token() for _ in range(20)}
    assert len(tokens) == 20


def test_build_pairing_url_format() -> None:
    sid = UUID("11111111-1111-1111-1111-111111111111")
    token = "abcdef0123456789abcdef0123456789"
    url = build_pairing_url("https://master.example/", sid, token)
    assert (
        url
        == "https://master.example/pair?sid=11111111-1111-1111-1111-111111111111&t=abcdef0123456789abcdef0123456789"
    )


def test_build_pairing_url_strips_trailing_slash() -> None:
    sid = uuid4()
    token = generate_token()
    url = build_pairing_url("https://master.example///", sid, token)
    assert "///pair" not in url
    assert "/pair?" in url


def test_build_pairing_url_rejects_bad_token() -> None:
    sid = uuid4()
    with pytest.raises(ValueError):
        build_pairing_url("https://master.example/", sid, "not-a-hex-token")


def test_parse_pairing_url_roundtrip() -> None:
    sid = uuid4()
    token = generate_token()
    url = build_pairing_url("https://master.example:8443", sid, token)
    parsed = parse_pairing_url(url)
    assert parsed.master_url == "https://master.example:8443"
    assert parsed.session_id == sid
    assert parsed.token == token


def test_parse_pairing_url_default_port_omitted() -> None:
    sid = uuid4()
    token = generate_token()
    url = build_pairing_url("https://master.example", sid, token)
    parsed = parse_pairing_url(url)
    assert parsed.master_url == "https://master.example"


def test_parse_pairing_url_rejects_wrong_scheme() -> None:
    with pytest.raises(InvalidPairingUrlError):
        parse_pairing_url(
            "ftp://master.example/pair?sid=11111111-1111-1111-1111-111111111111&t=abcdef0123456789abcdef0123456789"
        )


def test_parse_pairing_url_rejects_wrong_path() -> None:
    with pytest.raises(InvalidPairingUrlError):
        parse_pairing_url(
            "https://master.example/notpair?sid=11111111-1111-1111-1111-111111111111&t=abcdef0123456789abcdef0123456789"
        )


def test_parse_pairing_url_rejects_missing_token() -> None:
    with pytest.raises(InvalidPairingUrlError):
        parse_pairing_url(
            "https://master.example/pair?sid=11111111-1111-1111-1111-111111111111"
        )


def test_parse_pairing_url_rejects_invalid_uuid() -> None:
    with pytest.raises(InvalidPairingUrlError):
        parse_pairing_url(
            "https://master.example/pair?sid=not-a-uuid&t=abcdef0123456789abcdef0123456789"
        )


def test_parse_pairing_url_rejects_short_token() -> None:
    with pytest.raises(InvalidPairingUrlError):
        parse_pairing_url(
            "https://master.example/pair?sid=11111111-1111-1111-1111-111111111111&t=tooshort"
        )


def test_parse_pairing_url_trims_whitespace() -> None:
    sid = uuid4()
    token = generate_token()
    url = build_pairing_url("https://master.example", sid, token)
    parsed = parse_pairing_url(f"  {url}\n")
    assert parsed.session_id == sid
