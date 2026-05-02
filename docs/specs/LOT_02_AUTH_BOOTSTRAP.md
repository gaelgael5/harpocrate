# Lot 02 — Auth + identités externes + governance

> **Prérequis** : Lots 00 et 01.

## Objectif

Permettre à un utilisateur authentifié via Keycloak (broker OIDC vers Google) de **bootstrapper son compte**, **gérer plusieurs identités externes**, **récupérer son matériel crypto** pour unlock, et activer les mécanismes de gouvernance d'identité (détection d'anomalies, quarantaine, re-vérification).

## Dépendances

- Lots 00 et 01

## Périmètre

### Inclus

- Middleware FastAPI de validation des JWT Keycloak (signature, audience, expiration, JWKS rotation)
- Cache JWKS
- Dependency `require_jwt_user` qui :
  - Refuse les tokens `hrp_*` (API keys)
  - Lookup user via `(provider, external_subject)` du claim
  - Détection d'anomalies au login
  - Application de la quarantaine si applicable
  - Application de `force_reverify_next_login` si applicable
- Endpoints `/v1/me/*` : `GET`, `bootstrap`, `crypto`, `crypto/recovery`, `passphrase`, `recovery`
- Endpoints `/v1/me/identities/*` : list, link (OAuth flow), unlink, set-primary
- Endpoint `/v1/me/reverify` : preuve de possession passphrase pour 5 min
- Endpoint `/v1/me/quarantine` : sortie via recovery phrase
- Endpoints `/v1/me/anomalies` : list, acknowledge
- Validation stricte KDF/RSA contre les floors
- Audit log complet pour tous les événements d'identité

### Exclus

- Aucune logique de wallet ni de secret
- Pas d'API key (lot 08)
- Pas d'admin endpoints (lot 12c)

## Spécifications fonctionnelles

### Récupération de l'identité depuis le JWT

Le serveur extrait l'identité dans cet ordre :

```python
def extract_external_identity(jwt_payload: dict) -> tuple[str, str]:
    """Retourne (provider, external_subject)."""

    # Cas idéal : claims explicites injectés par Keycloak via mapper
    external_sub = jwt_payload.get("external_sub")
    external_provider = jwt_payload.get("external_provider")
    if external_sub and external_provider:
        return (external_provider, external_sub)

    # Cas fédéré : extraction depuis federated_identity claim si présent
    federated = jwt_payload.get("federated_identity", [])
    if federated:
        # Prendre la première identité fédérée
        first = federated[0]
        provider = first.get("identityProvider", "google")
        sub = first.get("userId") or first.get("sub")
        if sub:
            return (provider, sub)

    # Fallback : sub Keycloak interne (cas où Keycloak a un user local)
    return ("keycloak_internal", jwt_payload["sub"])
```

### `GET /v1/me`

- **Auth** : JWT
- **Réponses** :
  - `200` (utilisateur bootstrappé, déchiffrement implicite à l'unlock côté client) :
  ```json
  {
    "id": "uuid",
    "email": "alice@example.com",
    "display_name": "Alice",
    "has_bootstrap": true,
    "kdf_params": { "memory_kb": 65536, "iterations": 3, "parallelism": 4 },
    "rsa_key_size": 2048,
    "created_at": "...",
    "last_unlock_at": "...",
    "quarantine": null,
    "force_reverify_next_login": false,
    "unacknowledged_anomalies_count": 0,
    "primary_identity": {
      "provider": "google",
      "linked_email": "alice@example.com"
    }
  }
  ```
  - `404` (non-bootstrappé) :
  ```json
  {
    "error": "first_login",
    "message": "User must complete bootstrap before using Harpocrate",
    "details": {
      "external_provider": "google",
      "external_subject": "1234567890",
      "email": "alice@example.com"
    }
  }
  ```
  - `403 user_in_quarantine` (si quarantine_until > now et endpoint mutatif) :
  ```json
  {
    "error": "user_in_quarantine",
    "quarantine_until": "...",
    "quarantine_reason": "long_inactivity_login",
    "exit_options": ["recovery_phrase", "admin_lift", "wait_natural_expiry"]
  }
  ```

### `POST /v1/me/bootstrap`

- **Auth** : JWT
- **Body** :
```json
{
  "rsa_public_key": "<base64>",
  "salt_passphrase": "<base64 16 bytes>",
  "salt_recovery": "<base64 16 bytes>",
  "encrypted_rsa_private_key": "<base64>",
  "encrypted_sym_key_by_pass": "<base64>",
  "encrypted_sym_key_by_recovery": "<base64>",
  "kdf_memory_kb": 65536,
  "kdf_iterations": 3,
  "kdf_parallelism": 4,
  "rsa_key_size": 2048
}
```
- **Effets** :
  - INSERT users avec ces blobs
  - INSERT user_external_identities avec (provider, external_subject) du JWT, `is_primary=TRUE`, snapshot de email/display_name
  - Audit log `user.bootstrapped`
- **Validations** : floors, salt = 16 bytes, RSA pub valide
- **Réponses** :
  - `201 { "user_id": "..." }`
  - `409 already_bootstrapped`
  - `409 external_identity_already_linked` (le sub est déjà lié à un autre user → suspect)

### `GET /v1/me/identities`

- **Auth** : JWT
- **Réponses** :
```json
{
  "identities": [
    {
      "id": "uuid",
      "provider": "google",
      "external_subject_truncated": "1234567...",
      "is_primary": true,
      "linked_email": "alice@example.com",
      "linked_at": "...",
      "last_login_at": "..."
    },
    {
      "id": "uuid",
      "provider": "google",
      "external_subject_truncated": "9876543...",
      "is_primary": false,
      "linked_email": "alice.pro@harpocrate.io",
      "linked_at": "...",
      "last_login_at": "..."
    }
  ]
}
```
- **Notes** : on ne retourne JAMAIS le `external_subject` complet (privacy). Tronqué à 7 chars + "...".

### `POST /v1/me/identities/link`

- **Auth** : JWT (la session courante = identité 1)
- **Body** : `{ "provider": "google" }`
- **Réponse** : `200 { "redirect_url": "https://keycloak.../auth?..." }` qui redirige vers le flow OAuth
- **Notes** : la session passe par un état "linking in progress", stocké en DB ou en cache, avec un `state` random pour éviter le CSRF

### `GET /v1/me/identities/link/callback`

- **Auth** : aucune (callback OAuth)
- **Query** : `?state=...&code=...` (standard OAuth)
- **Effets** :
  - Échange du code contre un nouveau JWT
  - Vérification que le `state` matche une demande de linking en cours
  - Extraction de la nouvelle identité (provider, external_sub)
  - Vérification : si déjà liée à un autre user → 409 (suspect)
  - INSERT user_external_identities avec `is_primary=FALSE` par défaut
  - Audit log `user.identity_linked`
- **Réponses** : `302` vers `/account/identities` avec succès, ou `/account/identities?error=...`

### `DELETE /v1/me/identities/{identity_id}`

- **Auth** : JWT + reverify token (action destructive)
- **Validations** :
  - L'identity appartient au caller
  - Au moins une identity restera après DELETE (refus si dernière)
  - Si `is_primary=TRUE`, refus avec message "promote another identity to primary first"
- **Réponses** :
  - `204`
  - `400 cannot_remove_last_identity`
  - `400 cannot_remove_primary_identity`

### `PUT /v1/me/identities/{identity_id}/primary`

- **Auth** : JWT
- **Effets** :
  - UPDATE user_external_identities : ancienne primary → false, nouvelle → true (transaction)
  - UPDATE users.email avec `linked_email` de la nouvelle primary
- **Réponse** : `200`

### `GET /v1/me/crypto`

- **Auth** : JWT
- **Réponses** :
  - `200` :
  ```json
  {
    "salt_passphrase": "<base64>",
    "encrypted_rsa_private_key": "<base64>",
    "encrypted_sym_key_by_pass": "<base64>",
    "kdf_params": { "memory_kb": ..., "iterations": ..., "parallelism": ... },
    "rsa_public_key": "<base64>"
  }
  ```
  - `404` non-bootstrappé
- **Side-effect** :
  - UPDATE users.last_unlock_at
  - UPDATE user_external_identities.last_login_at de l'identity utilisée
  - Audit log `user.crypto_accessed`

### `GET /v1/me/crypto/recovery`

- **Auth** : JWT
- **Réponses** : `200 { "salt_recovery": "...", "encrypted_sym_key_by_recovery": "..." }`
- **Audit** : `user.recovery_accessed` (sensible, à monitorer)

### `PUT /v1/me/passphrase`

- **Auth** : JWT + reverify token (preuve de l'ancienne passphrase)
- **Body** :
```json
{
  "new_salt_passphrase": "<base64>",
  "new_encrypted_rsa_private_key": "<base64>",
  "new_encrypted_sym_key_by_pass": "<base64>",
  "kdf_memory_kb": 65536,
  "kdf_iterations": 3,
  "kdf_parallelism": 4
}
```
- **Audit** : `user.passphrase_changed`

### `PUT /v1/me/recovery`

- **Auth** : JWT + reverify token
- **Body** : `{ "new_salt_recovery": "...", "new_encrypted_sym_key_by_recovery": "..." }`
- **Audit** : `user.recovery_renewed`

### `POST /v1/me/reverify`

- **Auth** : JWT
- **Workflow en deux temps** :

  1. **Demande de challenge** :
     - `POST /v1/me/reverify/challenge`
     - Réponse : `{ "challenge": "<base64 32 bytes>", "expires_at": "..." }`
     - Le serveur stocke (user_id, challenge, expires_at_30s) en RAM ou cache

  2. **Soumission de la preuve** :
     - `POST /v1/me/reverify`
     - Body : `{ "challenge": "...", "proof": "<base64 HMAC-SHA256(pass_key, challenge)>" }`
     - Le serveur ne peut pas vérifier directement la preuve (il n'a pas pass_key). À la place :
       - Le serveur trust la preuve si **le client a pu la calculer**, ce qui implique qu'il a déchiffré récemment et donc connaît pass_key
     - **Décision MVP** : on simplifie en faisant juste vérifier que le client a accédé à `/v1/me/crypto` dans les 5 dernières minutes (cookie de session ou token interne)
     - **Décision propre (post-MVP)** : crypto challenge-response ; le serveur garde un blob chiffré par pass_key qu'il fait déchiffrer par le client à chaque reverify
- **Réponse** : `{ "reverify_token": "<UUID>", "expires_at": "..." }` (validity = 5 min)
- **Notes** : le client stocke le `reverify_token` et l'envoie dans le header `X-Reverify-Token` pour les actions destructives

### `POST /v1/me/quarantine/exit`

- **Auth** : JWT
- **Body** :
```json
{
  "encrypted_sym_key_decrypted_with_recovery": "<base64>"
}
```
  - Le client a déchiffré sa `sym_key` avec sa recovery phrase, et la renvoie au serveur **chiffrée à nouveau avec sa pass_key actuelle** (preuve qu'il a les deux)
  - Le serveur compare avec `encrypted_sym_key_by_pass` actuel : doivent correspondre une fois déchiffrés (mais le serveur ne peut pas le vérifier)
  - **Approche MVP plus simple** : le client soumet juste un signal "j'ai validé ma recovery phrase localement", le serveur lève la quarantaine en faisant confiance. Le vrai contrôle est que **personne d'autre que le user légitime ne connaît la recovery phrase**.
- **Effets** : UPDATE users SET quarantine_until = NULL, quarantine_reason = NULL
- **Audit** : `user.quarantine_exited`
- **Réponse** : `200`

### `GET /v1/me/anomalies`

- **Auth** : JWT
- **Query** : `?include_acknowledged=false`
- **Réponse** :
```json
{
  "anomalies": [
    {
      "id": 42,
      "detected_at": "...",
      "severity": "warning",
      "type": "display_name_changed_significantly",
      "metadata": { "old": "Alice L.", "new": "Bob" },
      "acknowledged_at": null
    }
  ]
}
```

### `POST /v1/me/anomalies/{id}/acknowledge`

- **Auth** : JWT
- **Effet** : UPDATE acknowledged_at, acknowledged_by_user_id
- **Audit** : `user.anomaly_acknowledged`

### `GET /v1/config/keycloak`

(Déjà au lot 00, rappel)

## Spécifications techniques

### Détection d'anomalies au login

```python
async def detect_login_anomalies(
    conn: asyncpg.Connection,
    user: UserRow,
    jwt_payload: dict,
    settings: Settings,
) -> list[Anomaly]:
    anomalies = []

    new_email = jwt_payload.get("email", "")
    new_name = jwt_payload.get("name", "")

    # 1. Email changed
    if new_email and new_email != user.email:
        anomalies.append(Anomaly(
            severity="info",
            type="email_changed",
            metadata={"old": user.email, "new": new_email},
        ))

    # 2. Display name changed significantly
    if user.display_name and new_name:
        if not _names_similar(user.display_name, new_name):
            anomalies.append(Anomaly(
                severity="warning",
                type="display_name_changed_significantly",
                metadata={"old": user.display_name, "new": new_name},
            ))

    # 3. Long inactivity
    if user.last_unlock_at:
        days_inactive = (now() - user.last_unlock_at).days
        if days_inactive > settings.quarantine_inactivity_days:
            anomalies.append(Anomaly(
                severity="warning",
                type="long_inactivity",
                metadata={"days": days_inactive},
            ))

    # 4. email_verified flipped to false
    if not jwt_payload.get("email_verified", True):
        anomalies.append(Anomaly(
            severity="critical",
            type="email_no_longer_verified",
        ))

    # Persist anomalies
    for a in anomalies:
        await conn.execute(
            """INSERT INTO identity_anomaly_events
               (user_id, severity, anomaly_type, metadata)
               VALUES ($1, $2, $3, $4::jsonb)""",
            user.id, a.severity, a.type, json.dumps(a.metadata or {}),
        )

    return anomalies


def _names_similar(old: str, new: str) -> bool:
    """Naive similarity : Levenshtein distance < 3 ou substring."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, old.lower(), new.lower()).ratio() > 0.7
```

### Application de la quarantaine

```python
async def apply_quarantine_if_needed(
    conn: asyncpg.Connection,
    user: UserRow,
    anomalies: list[Anomaly],
    settings: Settings,
) -> None:
    # Cas 1 : déjà en quarantaine (vérifier expiration)
    if user.quarantine_until:
        if user.quarantine_until > now():
            return  # quarantaine encore active
        else:
            # Quarantaine expirée, lever
            await conn.execute(
                "UPDATE users SET quarantine_until=NULL, quarantine_reason=NULL "
                "WHERE id=$1", user.id,
            )
            return

    # Cas 2 : nouvelle quarantaine déclenchée par inactivité longue
    long_inactive = any(a.type == "long_inactivity" for a in anomalies)
    if long_inactive:
        await conn.execute(
            """UPDATE users
               SET quarantine_until = NOW() + INTERVAL '%s days',
                   quarantine_reason = 'long_inactivity_login'
               WHERE id = $1""" % settings.quarantine_duration_days,
            user.id,
        )
        # Audit log
        await audit.log(conn, "user.quarantine_started",
                        actor_user_id=user.id,
                        metadata={"reason": "long_inactivity_login"})

    # Cas 3 : critical anomaly → quarantaine immédiate
    has_critical = any(a.severity == "critical" for a in anomalies)
    if has_critical:
        await conn.execute(
            """UPDATE users
               SET quarantine_until = NOW() + INTERVAL '%s days',
                   quarantine_reason = 'critical_anomaly_detected'
               WHERE id = $1""" % settings.quarantine_duration_days,
            user.id,
        )
```

### Middleware bloquant les actions mutatives en quarantaine

À ajouter dans une dependency commune utilisée par tous les endpoints mutatifs (lots 03+) :

```python
async def require_no_quarantine_for_mutation(
    user: CurrentUser = Depends(require_jwt_user),
    request: Request,
) -> CurrentUser:
    if user.quarantine_until and user.quarantine_until > now():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            raise HTTPException(
                403,
                detail={
                    "error": "user_in_quarantine",
                    "quarantine_until": user.quarantine_until.isoformat(),
                    "quarantine_reason": user.quarantine_reason,
                },
            )
    return user
```

### Reverify token middleware

Pour les actions destructives, dependency :

```python
async def require_reverify(
    x_reverify_token: Annotated[str | None, Header()] = None,
    user: CurrentUser = Depends(require_jwt_user),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.destructive_actions_require_reverify:
        return  # désactivé par config

    if not x_reverify_token:
        raise HTTPException(401, "reverify_required")

    async with pool.acquire() as conn:
        valid = await conn.fetchval(
            """SELECT 1 FROM reverify_tokens
               WHERE user_id = $1
                 AND token_hash = $2
                 AND consumed_at IS NULL
                 AND expires_at > NOW()""",
            user.id, sha256(x_reverify_token).digest(),
        )
        if not valid:
            raise HTTPException(401, "reverify_token_invalid_or_expired")

        # One-shot : on consomme le token
        await conn.execute(
            "UPDATE reverify_tokens SET consumed_at = NOW() WHERE token_hash = $1",
            sha256(x_reverify_token).digest(),
        )
```

### Server session epoch

```python
# app/services/session_epoch.py
async def get_current_epoch(conn) -> int:
    return await conn.fetchval("SELECT epoch FROM server_session_epoch WHERE id = 1")

async def rotate_epoch(conn, reason: str) -> int:
    return await conn.fetchval(
        """UPDATE server_session_epoch
           SET epoch = epoch + 1, rotated_at = NOW(), rotated_reason = $1
           WHERE id = 1
           RETURNING epoch""",
        reason,
    )
```

L'UI lit `/v1/config/public` (qui inclut l'epoch courante) au démarrage, et toutes les requêtes subséquentes envoient le header `X-Session-Epoch: N`. Si serveur a une nouvelle epoch (par ex. après restore), il renvoie `409 session_invalidated_by_restore`.

## Critères de succès

1. ✅ Login Google via Keycloak → JWT contient `external_sub` (avec mapper configuré)
2. ✅ `GET /me` 404 first_login pour user nouveau, créé par bootstrap
3. ✅ Bootstrap crée user + identity primary
4. ✅ Re-login après bootstrap → 200 sur /me
5. ✅ Email changé dans Google → anomaly `info`, mise à jour silencieuse
6. ✅ Display name changé radicalement → anomaly `warning`, bandeau UI
7. ✅ Inactivité > 90j → quarantaine au login, mutations bloquées
8. ✅ Sortie de quarantaine via `/me/quarantine/exit`
9. ✅ Lier 2e identité Google → 2 identities, primary inchangée
10. ✅ Lier identity déjà liée à un autre user → 409
11. ✅ Unlink dernière identity → 400
12. ✅ Set primary → email mis à jour, ancienne primary devient false
13. ✅ Reverify token nécessaire pour PUT /me/passphrase
14. ✅ Reverify token expire après 5 min
15. ✅ Reverify token one-shot (consommé)
16. ✅ Anomalies listées et acknowledgables
17. ✅ Tous les endpoints créent un audit log

## Pièges connus

- **Mapper Keycloak `external_sub`** : à configurer manuellement dans Keycloak (User Attribute mapper). Sans ce mapper, le fallback `keycloak_internal` est utilisé, ce qui crée le couplage qu'on essaie d'éviter.
- **OAuth state à la link** : générer avec `secrets.token_urlsafe(32)`, stocker en DB ou cache 10 min, valider au callback. Sans ça, CSRF.
- **One primary at a time** : la transition primary nécessite une transaction (l'ancienne false avant la nouvelle true), sinon l'index UNIQUE casse.
- **Quarantaine et endpoints publics** : le middleware s'applique seulement aux endpoints requérant JWT. `/v1/config/*` reste accessible.
- **Reverify token transmis en header** : NE PAS le mettre dans l'URL (pourrait être loggé).
- **Reverify token hash en DB** : on stocke `sha256(token)`, pas le token. Évite leak via dump.
- **Anomaly detection est best-effort** : ne pas bloquer le login pour une anomaly `info` ou `warning`. `critical` peut bloquer.
- **`linked_email` snapshot** : capturé à la création de l'identity, peut diverger de l'email actuel. Utile pour audit "tu as lié cette identity quand l'email était X".
- **Tronquer `external_subject` en sortie API** : ne JAMAIS exposer le sub complet en clair via API. Limite le risque d'énumération.

## Tests à écrire

- `test_jwt_extracts_external_sub_from_mapper`
- `test_jwt_falls_back_to_keycloak_sub`
- `test_jwt_api_key_token_rejected`
- `test_me_first_login_when_no_identity`
- `test_bootstrap_creates_user_and_primary_identity`
- `test_bootstrap_already_done_409`
- `test_external_subject_already_linked_to_other_user_409`
- `test_link_identity_oauth_flow`
- `test_unlink_last_identity_400`
- `test_unlink_primary_400`
- `test_set_primary_updates_email`
- `test_email_change_creates_info_anomaly`
- `test_display_name_change_creates_warning_anomaly`
- `test_long_inactivity_triggers_quarantine`
- `test_quarantine_blocks_mutations`
- `test_quarantine_allows_reads`
- `test_quarantine_exit_via_recovery`
- `test_quarantine_natural_expiry`
- `test_reverify_required_for_passphrase_change`
- `test_reverify_token_one_shot`
- `test_reverify_token_expires`
- `test_anomaly_acknowledge`
- `test_session_epoch_rotation_invalidates_clients`

## Ce qui suit

Le **lot 03** introduit les wallets CRUD + lookup d'utilisateurs.
