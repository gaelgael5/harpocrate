"""CLI Python harpocrate-gen — helper pour le bash CLI — LOT_09 SDK.

Ce module expose un CLI Click réutilisé par le script bash harpocrate-cli.
Toutes les opérations crypto (AES-GCM, RSA, etc.) passent par ce CLI.

Usage depuis bash :
    harpocrate-gen get --token "$TOKEN" --url "$URL" --name SECRET_NAME
    harpocrate-gen populate --token "$TOKEN" --url "$URL" --name SECRET_NAME
    harpocrate-gen populate-all --token "$TOKEN" --url "$URL"
    harpocrate-gen list --token "$TOKEN" --url "$URL"
    harpocrate-gen whoami --token "$TOKEN" --url "$URL"
    harpocrate-gen wallet-id-from-token "$TOKEN"

Sécurité :
  - Le token n'est JAMAIS loggé ou écrit dans stdout (sauf la commande wallet-id-from-token).
  - La sortie normale va sur stdout, les erreurs sur stderr.
  - Les valeurs de secrets vont sur stdout RAW (sans newline supplémentaire).
"""

from __future__ import annotations

import json
import os
import sys

import click

from harpocrate.client import VaultClient
from harpocrate.exceptions import HarpocrateError
from harpocrate.token import parse_token


def _get_client(token: str | None, url: str | None) -> VaultClient:
    """Construit un VaultClient depuis le token et l'URL."""
    tok = token or os.environ.get("HARPOCRATE_TOKEN") or ""
    base = url or os.environ.get("HARPOCRATE_URL") or ""

    if not tok:
        click.echo("ERROR: token required (--token or HARPOCRATE_TOKEN)", err=True)
        sys.exit(1)
    if not base:
        click.echo("ERROR: url required (--url or HARPOCRATE_URL)", err=True)
        sys.exit(1)

    try:
        return VaultClient(token=tok, base_url=base)
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


@click.group()
def main() -> None:
    """Harpocrate helper — opérations crypto pour le CLI bash."""


@main.command("get")
@click.option("--token", envvar="HARPOCRATE_TOKEN", help="Token hrpv_*")
@click.option("--url", envvar="HARPOCRATE_URL", help="URL du serveur Vault")
@click.option("--name", required=True, help="Nom du secret")
def cmd_get(token: str | None, url: str | None, name: str) -> None:
    """Affiche la valeur d'un secret sur stdout (sans newline terminal)."""
    client = _get_client(token, url)
    try:
        value = client.secrets.get(name)
        click.echo(value, nl=False)
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


@main.command("populate")
@click.option("--token", envvar="HARPOCRATE_TOKEN", help="Token hrpv_*")
@click.option("--url", envvar="HARPOCRATE_URL", help="URL du serveur Vault")
@click.option("--name", required=True, help="Nom du secret")
def cmd_populate(token: str | None, url: str | None, name: str) -> None:
    """Peuple un placeholder avec une valeur générée localement."""
    client = _get_client(token, url)
    try:
        result = client.secrets.populate(name, auto_generate=True)
        if result.success:
            click.echo(f"{name}: populated (v{result.generation_version})")
        else:
            click.echo(f"ERROR: {result.error}", err=True)
            sys.exit(1)
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


@main.command("populate-all")
@click.option("--token", envvar="HARPOCRATE_TOKEN", help="Token hrpv_*")
@click.option("--url", envvar="HARPOCRATE_URL", help="URL du serveur Vault")
def cmd_populate_all(token: str | None, url: str | None) -> None:
    """Peuple tous les placeholders du wallet."""
    client = _get_client(token, url)
    try:
        results = client.secrets.populate_all()
        has_error = False
        for r in results:
            if r.success:
                click.echo(f"{r.name}: populated (v{r.generation_version})")
            else:
                click.echo(f"{r.name}: ERROR — {r.error}", err=True)
                has_error = True
        if not results:
            click.echo("No placeholders to populate.")
        if has_error:
            sys.exit(1)
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


@main.command("list")
@click.option("--token", envvar="HARPOCRATE_TOKEN", help="Token hrpv_*")
@click.option("--url", envvar="HARPOCRATE_URL", help="URL du serveur Vault")
@click.option("--json", "as_json", is_flag=True, help="Sortie JSON")
@click.option("--placeholder", "filter_ph", is_flag=True, help="Placeholders seulement")
@click.option("--valued", "filter_valued", is_flag=True, help="Secrets remplis seulement")
def cmd_list(
    token: str | None,
    url: str | None,
    as_json: bool,
    filter_ph: bool,
    filter_valued: bool,
) -> None:
    """Liste les secrets du wallet."""
    client = _get_client(token, url)
    try:
        resp = client.secrets.list_secrets(limit=200)
        items = resp.secrets
        if filter_ph:
            items = [s for s in items if s.is_placeholder]
        elif filter_valued:
            items = [s for s in items if not s.is_placeholder]

        if as_json:
            click.echo(
                json.dumps(
                    [
                        {
                            "id": str(s.id),
                            "name": s.name,
                            "is_placeholder": s.is_placeholder,
                            "tags": s.tags,
                        }
                        for s in items
                    ]
                )
            )
        else:
            for s in items:
                status = "placeholder" if s.is_placeholder else "valued"
                click.echo(f"{s.name} ({status})")
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


@main.command("whoami")
@click.option("--token", envvar="HARPOCRATE_TOKEN", help="Token hrpv_*")
@click.option("--url", envvar="HARPOCRATE_URL", help="URL du serveur Vault")
def cmd_whoami(token: str | None, url: str | None) -> None:
    """Affiche les informations de l'API key courante."""
    tok = token or os.environ.get("HARPOCRATE_TOKEN") or ""
    if not tok:
        click.echo("ERROR: token required (--token or HARPOCRATE_TOKEN)", err=True)
        sys.exit(1)
    try:
        parsed = parse_token(tok)
        click.echo(f"API key ID : {parsed.api_key_id}")
        click.echo(f"Permissions: {parsed.permissions:#04x}")
        click.echo(f"Expires at : {'never' if parsed.exp == 0 else parsed.exp}")
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


@main.command("wallet-id-from-token")
@click.argument("token_arg", metavar="TOKEN")
def cmd_wallet_id_from_token(token_arg: str) -> None:
    """Extrait l'api_key_id depuis un token hrpv_* (usage interne bash CLI)."""
    try:
        parsed = parse_token(token_arg)
        click.echo(str(parsed.api_key_id), nl=False)
    except HarpocrateError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
