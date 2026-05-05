"""Client haut niveau VaultClient — LOT_09/18 SDK.

Interface principale du SDK :
    from harpocrate import VaultClient
    client = VaultClient(token="hrpv_...", base_url="https://vault.yoops.org")
    value = client.secrets.get("ANTHROPIC_API_KEY")

Crypto :
  - La wallet_key est déchiffrée depuis api_keys.encrypted_wallet_key via decryption_key
  - La wallet_key est mise en cache (TTL configurable)
  - Chaque appel à secrets.get() déchiffre encrypted_value avec wallet_key (AES-GCM)
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote
from uuid import UUID

from harpocrate.cache import WalletKeyCache
from harpocrate.crypto.aes_gcm import aes_gcm_decrypt, aes_gcm_encrypt
from harpocrate.exceptions import (
    GeneratorError,
    HarpocrateError,
    PlaceholderNotPopulated,
    SecretRefreshFailed,
    VaultDecryptionError,
)
from harpocrate.generators import dispatch as generate_value
from harpocrate.http import VaultHttpClient
from harpocrate.models.secret import PopulateResult, SecretInfo, SecretListResponse
from harpocrate.models.secret_type import SecretType
from harpocrate.models.wallet import ApiKeyInfo, WalletInfo
from harpocrate.rotation import GlobalCallback, RotationRegistry, SpecificCallback
from harpocrate.token import ParsedToken, parse_token

_NAME_RE = re.compile(r"^[A-Za-z0-9_.\\-]+$")


class SecretsClient:
    """Sous-client pour les opérations sur les secrets d'un wallet."""

    def __init__(
        self,
        http: VaultHttpClient,
        wallet_id: UUID,
        parsed_token: ParsedToken,
        cache: WalletKeyCache,
    ) -> None:
        self._http = http
        self._wallet_id = wallet_id
        self._parsed = parsed_token
        self._cache = cache

    def _wallet_key(self) -> bytes:
        """Retourne la wallet_key déchiffrée (depuis cache ou serveur)."""
        cache_key = str(self._wallet_id)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Récupère encrypted_wallet_key depuis l'endpoint my-api-key-grant
        path = f"/v1/wallets/{self._wallet_id}/my-api-key-grant"
        data = self._http.get(path)
        enc_wk_b64: str = data["encrypted_wallet_key"]
        enc_wk_bytes = base64.b64decode(enc_wk_b64)
        wallet_key = aes_gcm_decrypt(enc_wk_bytes, self._parsed.decryption_key)
        self._cache.set(cache_key, wallet_key)
        return wallet_key

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalise un nom de secret avec path : ajoute '/' initial si absent."""
        if "/" in name and not name.startswith("/"):
            return "/" + name
        return name

    def _path(self, name: str | None = None) -> str:
        base = f"/v1/wallets/{self._wallet_id}/secrets"
        if name:
            normalized = self._normalize_name(name)
            # URL-encode les '/' du nom pour qu'ils ne soient pas interprétés comme séparateurs
            encoded = quote(normalized, safe="")
            return f"{base}/{encoded}"
        return base

    def _resolve_id_if_pathstyle(self, name: str) -> str | None:
        """Résout l'UUID d'un secret si son nom contient un '/' (path-style).

        Pour les noms sans '/', retourne None — l'appelant utilisera la route name-based.
        Pour les noms à '/', liste les secrets au path parent et trouve l'entrée matching.
        Lève SecretNotFound si aucun secret ne correspond.
        """
        from harpocrate.exceptions import SecretNotFound

        if "/" not in name:
            return None

        normalized = self._normalize_name(name)
        # Path parent : tout sauf le dernier segment, avec '/' final garanti
        parent_path = normalized.rsplit("/", 1)[0] + "/"
        # Cas spécial : nom à un seul segment après le '/' initial → parent = '/'
        if parent_path == "/" and not normalized.startswith("//"):
            pass  # parent_path déjà '/'

        data = self._http.get(
            f"/v1/wallets/{self._wallet_id}/secrets",
            path=parent_path,
        )
        for s in data.get("secrets", []):
            if s.get("name") == normalized:
                return str(s["id"])

        raise SecretNotFound(f"Secret '{name}' not found in wallet")

    def _path_for_op(self, name: str) -> str:
        """URL d'opération unitaire — by-id si nom path-style, by-name sinon."""
        sid = self._resolve_id_if_pathstyle(name)
        if sid is not None:
            return f"/v1/wallets/{self._wallet_id}/secrets/by-id/{sid}"
        return self._path(name)

    def list_secrets(
        self,
        tag: str | None = None,
        name_contains: str | None = None,
        path: str | None = None,
        limit: int = 50,
    ) -> SecretListResponse:
        """Liste les secrets du wallet (sans valeurs).

        Retourne un SecretListResponse avec .secrets (list[SecretInfo]) et .next_cursor.
        Avec path=, retourne uniquement les secrets directs du répertoire donné.
        """
        params: dict[str, Any] = {"limit": limit}
        if tag:
            params["tag"] = tag
        if name_contains:
            params["name_contains"] = name_contains
        if path is not None:
            params["path"] = path

        data = self._http.get(self._path(), **params)
        items = [SecretInfo.from_dict(s) for s in data.get("secrets", [])]
        return SecretListResponse(
            secrets=items,
            next_cursor=data.get("next_cursor"),
        )

    def get_tree(self, path: str = "/") -> dict[str, Any]:
        """Retourne l'arborescence du wallet à un path donné.

        Retourne un dict avec : path, secrets_at_this_level_count, folders.
        """
        tree_path = f"/v1/wallets/{self._wallet_id}/tree"
        return self._http.get(tree_path, path=path)  # type: ignore[return-value]

    def create(
        self,
        name: str,
        value: str,
        description: str | None = None,
        tags: list[str] | None = None,
        type_uuid: UUID | None = None,
        schema_version_uuid: UUID | None = None,
    ) -> str:
        """Crée un secret avec une valeur chiffrée côté client.

        Si `type_uuid` n'est pas fourni, le serveur attache automatiquement le type RAW.
        Retourne le secret_id (UUID string). Requiert [add].
        """
        wallet_key = self._wallet_key()
        enc_value = aes_gcm_encrypt(value.encode("utf-8"), wallet_key)
        enc_value_b64 = base64.b64encode(enc_value).decode()
        body: dict[str, Any] = {"name": name, "encrypted_value": enc_value_b64}
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = tags
        if type_uuid is not None:
            body["type_uuid"] = str(type_uuid)
        if schema_version_uuid is not None:
            body["schema_version_uuid"] = str(schema_version_uuid)
        result = self._http.post(self._path(), json=body)
        return str(result["secret_id"])

    def put(self, name: str, value: str) -> int:
        """Remplace la valeur d'un secret existant (incrémente generation_version).

        Retourne la nouvelle generation_version. Requiert [write].
        """
        wallet_key = self._wallet_key()
        enc_value = aes_gcm_encrypt(value.encode("utf-8"), wallet_key)
        enc_value_b64 = base64.b64encode(enc_value).decode()
        result = self._http.put(self._path_for_op(name), json={"encrypted_value": enc_value_b64})
        return int(result["generation_version"])

    def patch(
        self,
        name: str,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Met à jour les métadonnées d'un secret (description et/ou tags).

        Ne modifie pas la valeur chiffrée. Requiert [write].
        """
        body: dict[str, Any] = {}
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = tags
        self._http.patch(self._path_for_op(name), json=body)

    def delete(self, name: str) -> None:
        """Supprime un secret (résout l'ID si le nom est path-style). Requiert [remove]."""
        self._http.delete(self._path_for_op(name))

    def create_placeholder(
        self,
        name: str,
        descriptor: dict[str, Any],
        description: str | None = None,
        tags: list[str] | None = None,
        type_uuid: UUID | None = None,
        schema_version_uuid: UUID | None = None,
    ) -> str:
        """Crée un placeholder avec son descripteur de génération.

        Si `type_uuid` n'est pas fourni, le serveur attache automatiquement le type RAW.
        Retourne le secret_id. Requiert [add].
        """
        body: dict[str, Any] = {"name": name, "generation_descriptor": descriptor}
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = tags
        if type_uuid is not None:
            body["type_uuid"] = str(type_uuid)
        if schema_version_uuid is not None:
            body["schema_version_uuid"] = str(schema_version_uuid)
        result = self._http.post(f"/v1/wallets/{self._wallet_id}/secrets/placeholder", json=body)
        return str(result["secret_id"])

    def get(self, name: str, force_refresh: bool = False) -> str:
        """Lit et déchiffre la valeur d'un secret.

        Retourne la valeur en clair (str UTF-8).
        Lève PlaceholderNotPopulated si le secret n'a pas de valeur.
        Lève VaultDecryptionError si le déchiffrement échoue.

        Avec `force_refresh=True` (LOT_22), invalide le cache wallet_key local
        avant la lecture pour récupérer une éventuelle nouvelle wallet_key
        après une rotation côté serveur.
        """
        if force_refresh:
            self._cache.invalidate(str(self._wallet_id))
        data = self._http.get(self._path_for_op(name))
        wallet_key = self._wallet_key()

        enc_value = base64.b64decode(data["encrypted_value"])
        enc_wk = base64.b64decode(data["encrypted_wallet_key"])

        # Le serveur retourne encrypted_wallet_key du caller.
        # Pour une API key, on utilise la wallet_key du cache.
        # Mais le serveur peut aussi retourner une wk spécifique à ce secret pour les grants.
        # On essaie d'abord avec la wallet_key du cache, puis avec celle du serveur.
        try:
            plaintext = aes_gcm_decrypt(enc_value, wallet_key)
        except VaultDecryptionError:
            # Essai avec la wallet_key chiffrée par la grant (pour JWT callers)
            try:
                wk_from_grant = aes_gcm_decrypt(enc_wk, self._parsed.decryption_key)
                plaintext = aes_gcm_decrypt(enc_value, wk_from_grant)
                # Met à jour le cache avec la clé correcte
                self._cache.set(str(self._wallet_id), wk_from_grant)
            except VaultDecryptionError as exc:
                raise VaultDecryptionError(
                    f"Failed to decrypt secret '{name}': invalid key or corrupted data"
                ) from exc

        return plaintext.decode("utf-8")

    def get_bytes(self, name: str) -> bytes:
        """Lit et déchiffre la valeur d'un secret en bytes bruts.

        Utile pour les certificats TLS et autres données binaires.
        """
        return self.get(name).encode("utf-8")

    def get_descriptor(self, name: str) -> dict[str, Any]:
        """Récupère le descripteur de génération d'un placeholder."""
        data = self._http.get(f"{self._path_for_op(name)}/descriptor")
        return dict(data.get("generation_descriptor") or {})

    def populate(
        self,
        name: str,
        auto_generate: bool = True,
        value: str | None = None,
    ) -> PopulateResult:
        """Peuple un placeholder avec une valeur générée ou fournie.

        Si auto_generate=True : récupère le descripteur et génère la valeur localement.
        Si value est fourni : utilise cette valeur directement.

        Retourne PopulateResult.
        """
        if not auto_generate and value is None:
            raise HarpocrateError("Either auto_generate=True or value must be provided")

        if auto_generate:
            descriptor = self.get_descriptor(name)
            try:
                plain = generate_value(descriptor)
            except GeneratorError as exc:
                return PopulateResult.failed(name, str(exc))
        else:
            assert value is not None
            plain = value

        wallet_key = self._wallet_key()
        enc_value = aes_gcm_encrypt(plain.encode("utf-8"), wallet_key)
        enc_value_b64 = base64.b64encode(enc_value).decode()

        result = self._http.post(
            f"{self._path_for_op(name)}/populate",
            json={"encrypted_value": enc_value_b64},
        )
        version: int = result.get("generation_version", 0)
        return PopulateResult.ok(name, version)

    def populate_all(self) -> list[PopulateResult]:
        """Peuple tous les placeholders du wallet.

        Retourne la liste des résultats (success ou failure par secret).
        """
        listing = self.list_secrets(limit=200)
        results: list[PopulateResult] = []

        for secret_info in listing.secrets:
            if not secret_info.is_placeholder:
                continue
            try:
                result = self.populate(secret_info.name, auto_generate=True)
                results.append(result)
            except Exception as exc:
                results.append(PopulateResult.failed(secret_info.name, str(exc)))

        return results

    def get_or_populate(self, name: str) -> str:
        """Lit la valeur d'un secret, ou génère et populate si c'est un placeholder.

        Retourne la valeur en clair.
        """
        try:
            return self.get(name)
        except PlaceholderNotPopulated:
            self.populate(name, auto_generate=True)
            return self.get(name)


class TypesClient:
    """Sous-client pour le catalogue de types de secrets (lecture seule).

    Utilise les endpoints publics /v1/secret-types accessibles via API key
    depuis P1.5 (ou via JWT user).
    """

    def __init__(self, http: VaultHttpClient) -> None:
        self._http = http

    def list(self, q: str | None = None, include_deprecated: bool = False) -> list[SecretType]:
        """Liste les types de secrets disponibles.

        Paramètres :
            q : filtre fulltext (type, sous_type, label)
            include_deprecated : inclure les types dépréciés

        Retourne : list[SecretType]
        """
        params: dict[str, Any] = {}
        if q is not None:
            params["q"] = q
        if include_deprecated:
            params["include_deprecated"] = include_deprecated

        data = self._http.get("/v1/secret-types", **params)
        return [SecretType.from_dict(t) for t in data.get("types", [])]

    def get(self, type_uuid: UUID) -> SecretType:
        """Retourne le détail d'un type avec son schéma complet (data + UI) et toutes les versions."""
        data = self._http.get(f"/v1/secret-types/{type_uuid}")
        return SecretType.from_dict(data)


class VaultClient:
    """Client haut niveau pour l'API Harpocrate.

    Usage :
        from harpocrate import VaultClient

        client = VaultClient(
            token="hrpv_1_xxx...",
            base_url="https://vault.yoops.org",
        )

        value = client.secrets.get("ANTHROPIC_API_KEY")
        results = client.secrets.populate_all()
    """

    def __init__(
        self,
        token: str,
        base_url: str,
        wallet_key_cache_ttl: int = 600,
        timeout: float = 30.0,
    ) -> None:
        """Initialise le client Vault.

        Paramètres :
            token              : token hrpv_* d'API key
            base_url           : URL de base du serveur (HTTPS requis en prod)
            wallet_key_cache_ttl : TTL du cache wallet_key en secondes (défaut 600)
            timeout            : timeout HTTP en secondes (défaut 30)
        """
        self._parsed = parse_token(token)
        self._http = VaultHttpClient(base_url=base_url, token=token, timeout=timeout)
        self._cache = WalletKeyCache(ttl_seconds=wallet_key_cache_ttl)
        self._wallet_id: UUID | None = None
        self._rotation = RotationRegistry()

        self.secrets = SecretsClient(
            http=self._http,
            wallet_id=self._resolve_wallet_id(),
            parsed_token=self._parsed,
            cache=self._cache,
        )
        self.types = TypesClient(http=self._http)

    def _resolve_wallet_id(self) -> UUID:
        """Résout le wallet_id depuis l'endpoint my-api-key-grant."""
        if self._wallet_id is not None:
            return self._wallet_id

        # Utilise l'API key whoami-style endpoint
        data = self._http.get(f"/v1/api-keys/{self._parsed.api_key_id}/wallet-id")
        self._wallet_id = UUID(data["wallet_id"])
        return self._wallet_id

    def whoami(self) -> ApiKeyInfo:
        """Retourne les informations sur l'API key courante."""
        data = self._http.get(f"/v1/api-keys/{self._parsed.api_key_id}")
        return ApiKeyInfo(
            api_key_id=self._parsed.api_key_id,
            wallet_id=UUID(data.get("wallet_id", str(self.secrets._wallet_id))),
            permissions=self._parsed.permissions,
            expires_at=self._parsed.exp,
        )

    def info(self) -> WalletInfo:
        """Retourne les informations sur le wallet associé à l'API key."""
        wallet_id = self.secrets._wallet_id
        data = self._http.get(f"/v1/wallets/{wallet_id}")
        return WalletInfo.from_dict(data)

    # ─── LOT_22 — détection rotation par auth_error ──────────────────────────

    def on_auth_error(
        self, secret_name: str
    ) -> Callable[[SpecificCallback], SpecificCallback]:
        """Décorateur : enregistre un callback déclenché sur rotation détectée.

        Usage :
            @client.on_auth_error("anthropic_api_key")
            async def handle_rotation(new_value: str) -> None:
                anthropic.api_key = new_value

        Plusieurs callbacks peuvent être enregistrés pour le même secret —
        ils sont appelés dans l'ordre d'enregistrement, puis les callbacks
        globaux. Une exception dans un callback est loggée et n'interrompt pas
        l'enchaînement.
        """
        def _decorator(callback: SpecificCallback) -> SpecificCallback:
            return self._rotation.register_specific(secret_name, callback)
        return _decorator

    def on_any_auth_error(self, callback: GlobalCallback) -> GlobalCallback:
        """Enregistre un callback global appelé pour TOUS les secrets en rotation.

        Signature : ``async (secret_name: str, new_value: str) -> None``
        ou la version sync. Appelé APRÈS les callbacks spécifiques.
        """
        return self._rotation.register_global(callback)

    async def notify_auth_error(self, secret_name: str) -> str:
        """Notifie le SDK qu'un secret a probablement été rotaté côté serveur.

        Le SDK :
        1. Force un refetch (`get(force_refresh=True)`) — wallet_key invalidée
        2. Appelle les callbacks `on_auth_error(secret_name)` puis `on_any_auth_error`
        3. Retourne la nouvelle valeur en clair

        Lève `SecretRefreshFailed` si le refresh échoue (secret supprimé,
        API key révoquée, etc.).
        """
        try:
            new_value = self.secrets.get(secret_name, force_refresh=True)
        except Exception as exc:
            raise SecretRefreshFailed(secret_name, str(exc)) from exc
        await self._rotation.fire(secret_name, new_value)
        return new_value

    def using_secret(self, secret_name: str) -> _UsingSecret:
        """Context manager : auto-retry sur exception d'auth.

        Usage :
            async with client.using_secret("anthropic_api_key") as get_value:
                key = get_value()
                try:
                    return await call_api(key)
                except AuthError:
                    key = await get_value(retry=True)  # force_refresh + callbacks
                    return await call_api(key)

        Sucre syntaxique optionnel — équivalent à appeler manuellement
        `notify_auth_error()`.
        """
        return _UsingSecret(self, secret_name)


class _UsingSecret:
    """Helper retourné par `client.using_secret(...)`."""

    def __init__(self, client: VaultClient, secret_name: str) -> None:
        self._client = client
        self._secret_name = secret_name

    async def __aenter__(self) -> Callable[..., Any]:
        async def _get(retry: bool = False) -> str:
            if retry:
                return await self._client.notify_auth_error(self._secret_name)
            return self._client.secrets.get(self._secret_name)
        return _get

    async def __aexit__(self, *_args: object) -> None:
        return None
