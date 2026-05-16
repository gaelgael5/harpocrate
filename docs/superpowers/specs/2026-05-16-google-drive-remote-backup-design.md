# Spec — Connexion distante Google Drive (kind=`gdrive`) pour les backups

**Date** : 2026-05-16
**Branche** : `feat/local-admin-auth` (ou nouvelle branche dédiée)
**Statut** : Design validé par l'architecte, prêt pour planification d'implémentation.

---

## 1. Contexte et objectif

Harpocrate dispose déjà de connexions distantes pour les backups (`remote_backup_connection`) avec trois `kind` : `sftp`, `s3`, `ftps`. Cette spec ajoute un **quatrième** : `gdrive` (Google Drive), accessible depuis la page admin "Connexions distantes" via le bouton "Ajouter une connexion".

L'objectif est de permettre à un admin de pousser ses backups (snapshots automatiques + fulls manuels) vers un compte Google Drive personnel ou Workspace, **sans aucune dépendance à une infrastructure OAuth centrale Yoops** — chaque admin crée sa propre application OAuth dans Google Cloud Console.

### Choix structurants (validés en brainstorming)

1. **Authentification** : OAuth 2.0 user-delegated (My Drive), pas Service Account.
2. **Client OAuth** : Client ID + Client Secret saisis par l'admin dans le formulaire (chaque instance Harpocrate, chaque admin, son propre client OAuth).
3. **Scope** : `https://www.googleapis.com/auth/drive.file` uniquement — Harpocrate n'a accès qu'aux fichiers qu'il a créés. Pas de review Google requise (scope non-sensitive).
4. **Emplacement des backups** : dossier créé et géré par Harpocrate en racine du Drive de l'admin (nom configurable, défaut `Harpocrate Backups`).
5. **Librairie backend** : libs officielles Google (`google-auth`, `google-auth-oauthlib`, `google-api-python-client`), sync, wrappées via `asyncio.to_thread` — cohérent avec le pattern `boto3` déjà adopté.
6. **UX d'autorisation** : wizard 2-step intra-modal avec popup OAuth + `postMessage`. Bouton "Re-autoriser" sur les connexions Drive existantes pour gérer les refresh tokens révoqués.

---

## 2. Architecture & flux OAuth

Google Drive devient le 4ème `kind` de `remote_backup_connection`. Il réutilise l'interface `RemoteBackupProvider` (`test_connection` + `upload_stream`) et la table existante. La différence fondamentale est qu'**aucune connexion Drive ne peut être créée sans un aller-retour OAuth préalable** — on a besoin du `refresh_token` avant l'INSERT. On introduit donc une table éphémère `oauth_pending_session` qui retient les paramètres OAuth entre le clic "Autoriser" et le retour du callback (TTL strict 10 min).

### Séquence complète de création

```
Admin UI                  Backend                    Google
   |                         |                          |
   | 1. Saisit name + ClientID + Secret + folder_name   |
   | 2. Click "Autoriser avec Google"                   |
   |------ POST /admin/backup-remotes/oauth/gdrive/start (body)
   |                         |--> INSERT oauth_pending_session(state=<random>, payload={creds + folder})
   |<----- { auth_url, state } returned                 |
   |                         |                          |
   | 3. window.open(auth_url, popup)                    |
   |---------------------------------------- consent screen (drive.file scope)
   |                                                    |
   | 4. Admin valide -> Google redirige vers callback   |
   |                         |<--- GET /callback?code=&state=
   |                         |--> SELECT pending_session WHERE state=$1 (CSRF + TTL)
   |                         |--> POST token endpoint -> refresh_token + user_email
   |                         |--> renvoie HTML auto-fermant qui fait window.opener.postMessage({state, ok:true})
   |<----- popup se ferme via postMessage              |
   |                         |                          |
   | 5. Modal reçoit postMessage, affiche "Autorisé en tant que user@gmail.com"
   |------ GET /oauth/gdrive/session/{state} -> récupère user_email pour affichage
   | 6. Admin clique "Sauvegarder"                      |
   |------ POST /admin/backup-remotes (kind=gdrive, oauth_state)
   |                         |--> SELECT pending_session, hydrate credentials
   |                         |--> INSERT remote_backup_connection (chiffrement AES-GCM)
   |                         |--> DELETE pending_session
   |<----- 201 { id }                                   |
```

### Points clefs

- **`state` cryptographiquement aléatoire** : `secrets.token_urlsafe(32)`, unique par session, vérifié au callback → protection CSRF.
- **`client_secret` ne transite jamais par le frontend après le POST start** — il vit dans `oauth_pending_session.payload` côté DB jusqu'à l'INSERT final, puis dans `credentials_encrypted`.
- **Le callback retourne du HTML auto-fermant** ; pas de redirection vers le SPA (évite les problèmes de routing nginx).
- **Job cron de purge** des `oauth_pending_session` expirées (greffé sur le scheduler existant `snapshot_scheduler.py`).

---

## 3. Modèle de données

### Migration 030 — élargir `kind` à `gdrive`

```sql
-- 030_remote_backup_kinds_gdrive.sql
-- LOT remote-backups-gdrive — ajoute 'gdrive' (Google Drive OAuth user-delegated)
-- aux kinds reconnus par remote_backup_connection.

ALTER TABLE remote_backup_connection
    DROP CONSTRAINT IF EXISTS remote_backup_connection_kind_check;

ALTER TABLE remote_backup_connection
    ADD CONSTRAINT remote_backup_connection_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps', 'gdrive'));
```

Pas de nouvelle colonne — les champs spécifiques à Drive vivent dans `config` JSONB et `credentials_encrypted`.

#### Format des blobs pour `kind='gdrive'`

```python
config = {
    "client_id":     "....apps.googleusercontent.com",    # OAuth Web App client ID (public)
    "redirect_uri":  "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback",
    "folder_name":   "Harpocrate Backups",                # nom du dossier racine côté Drive
    "folder_id":     "1abcDEF..." | None,                 # rempli au premier test_connection / upload
    "user_email":    "admin@gmail.com" | None             # email du compte autorisateur (affichage UI)
}

credentials = {
    "client_secret": "GOCSPX-...",                        # secret de l'app OAuth Google
    "refresh_token": "1//0g...",                          # offline access — long-lived
    "scope":         "https://www.googleapis.com/auth/drive.file",
    "token_uri":     "https://oauth2.googleapis.com/token"
}
```

### Migration 031 — table `oauth_pending_session`

```sql
-- 031_oauth_pending_session.sql
-- LOT remote-backups-gdrive — état éphémère d'un flux OAuth en cours.
-- Stocke les paramètres OAuth (client_id, client_secret, scope, payload UI)
-- entre le clic "Autoriser avec Google" côté frontend et le retour du callback
-- Google. TTL strict 10 min, purgé par job cron.
-- Une fois la connexion finalisée, la ligne est supprimée immédiatement.

CREATE TABLE oauth_pending_session (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    state               TEXT         NOT NULL UNIQUE,
    provider            TEXT         NOT NULL CHECK (provider IN ('gdrive')),
    payload             JSONB        NOT NULL,
    result              JSONB,
    status              TEXT         NOT NULL DEFAULT 'pending'
                                     CHECK (status IN ('pending', 'authorized', 'failed')),
    target_connection_id UUID         REFERENCES remote_backup_connection(id) ON DELETE CASCADE,
    created_by_user_id  UUID         REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ  NOT NULL
);

CREATE INDEX idx_oauth_pending_session_state   ON oauth_pending_session(state);
CREATE INDEX idx_oauth_pending_session_expires ON oauth_pending_session(expires_at);
```

#### Sémantique des colonnes

- **`provider`** : extensible mais contraint ; aujourd'hui `gdrive` uniquement, futur `dropbox`, `onedrive`, etc.
- **`payload`** : saisi par l'admin au start (`{client_id, client_secret, redirect_uri, scope, folder_name, name}`).
- **`result`** : rempli par le backend au callback (`{refresh_token, user_email, expires_at}`).
- **`status`** lifecycle : `pending` → (callback OK) `authorized` → (POST save / re-auth) **DELETE de la ligne**. En cas d'erreur callback : `failed` (gardée pour debug jusqu'à `expires_at`). Il n'y a volontairement pas de statut `consumed` — l'invariant "DELETE après usage" + `state UNIQUE` empêche tout replay (cf. section 8 invariant #4).
- **`target_connection_id`** : NULL pour création, rempli pour re-autorisation d'une connexion existante.

### Purge des sessions expirées

Greffé sur `snapshot_scheduler.py` (déjà actif toutes les minutes) :

```python
async def purge_expired_oauth_sessions(conn: asyncpg.Connection) -> int:
    return await conn.fetchval(
        "DELETE FROM oauth_pending_session WHERE expires_at < NOW() RETURNING id"
    )
```

---

## 4. Provider Python `GoogleDriveProvider`

### Localisation

`backend/src/app/services/remote_backup_providers/gdrive.py`

### Conception

Sync wrappé via `asyncio.to_thread` (cohérence avec `S3CompatibleProvider`). Pas de connexion persistante — chaque opération obtient un access_token frais via `Credentials.refresh()`. Le `googleapiclient.discovery.build()` est appelé par opération (cache local du discovery doc côté lib).

Le `path` côté interface `RemoteBackupProvider` **n'a pas de sémantique Drive** (Drive est plat avec des `folder_id`, pas des chemins POSIX). On le **ignore** pour gdrive : l'arborescence est `<folder_name>/<remote_filename>` où `folder_name` vient du config. Le `path` reste accepté pour conformité de l'interface mais log un debug si non vide.

### Évolution rétro-compatible de l'interface

```python
class RemoteBackupProvider(Protocol):
    async def test_connection(self, path: str) -> dict[str, Any] | None:
        """Returns an optional dict to merge into the connection's config
        (e.g. discovered folder_id for gdrive). Other providers return None."""
        ...
```

Les 3 providers existants gagnent un `return None` explicite — changement minimal.

### `test_connection`

```
1. Construit Credentials, refresh access_token (asyncio.to_thread)
2. Si folder_id absent du config :
     - files.list query "name = $folder_name AND trashed=false AND 'root' in parents"
     - 0 résultat -> create_folder({name, mimeType: 'application/vnd.google-apps.folder', parents:['root']})
     - 1+ résultats -> prend le premier
     - Retourne {folder_id: <discovered_or_created>}
3. files.list(folder=folder_id, pageSize=1) pour valider l'accès
4. Lève RemoteBackupProviderError sur RefreshError / HttpError 403 / 5xx
```

### `upload_stream`

```
1. Buffer source AsyncIterator[bytes] vers fichier temp (resumable upload sync requiert seekable)
2. asyncio.to_thread(files.create,
     body={name: remote_filename, parents: [folder_id]},
     media_body=MediaFileUpload(tmp, chunksize=8MB, resumable=True))
3. Retourne bytes_written total
4. supprime le tmp en finally (même en cas d'exception)
```

**Pourquoi un fichier temporaire** : le client officiel impose un objet seekable pour `resumable=True`. Même pattern que `S3CompatibleProvider`. Le temp est nettoyé en `finally`.

### Couche d'abstraction pour les tests

Une fine couche `gdrive_client.py` wrappe `build('drive', 'v3')`, `Flow.from_client_config()`, etc. Les tests mockent cette couche (pas `googleapiclient` directement) — plus propre et résilient.

### Factory `__init__.py`

```python
SUPPORTED_KINDS: frozenset[str] = frozenset({"sftp", "s3", "ftps", "gdrive"})

def get_provider(kind, config, credentials):
    ...
    if kind == "gdrive":
        return GoogleDriveProvider(config=config, credentials=credentials)
    ...
```

### Dépendances Python ajoutées (`backend/pyproject.toml`)

```toml
google-auth         = ">=2.30"
google-auth-oauthlib = ">=1.2"
google-api-python-client = ">=2.130"
```

Trois libs officielles maintenues par Google. ~3 MB d'install total.

---

## 5. Endpoints backend

Tous protégés par `AdminJwt`. Préfixe `/v1/admin/backup-remotes/oauth/gdrive/`.

### `GET .../redirect-uri`

Retourne le `redirect_uri` canonique (`HARPOCRATE_PUBLIC_URL + "/v1/admin/backup-remotes/oauth/gdrive/callback"`) que l'admin doit copier dans Google Cloud Console → Authorized redirect URIs. Le frontend l'affiche en read-only dans le formulaire (champ copiable).

**Response** : `{ redirect_uri: "https://harpo.example.com/v1/admin/backup-remotes/oauth/gdrive/callback" }`

Centraliser cette valeur côté backend garantit l'identité stricte entre les trois endroits où elle doit matcher (Google Cloud Console, auth_url, fetch_token au callback) — sinon Google rejette.

### `POST .../start`

**Body** :
```json
{
  "name": "Backups perso",
  "client_id": "....apps.googleusercontent.com",
  "client_secret": "GOCSPX-...",
  "folder_name": "Harpocrate Backups"
}
```

**Note** : `redirect_uri` n'est PAS dans le body — le backend l'injecte à partir de `HARPOCRATE_PUBLIC_URL`. `target_connection_id` reste toujours NULL pour cet endpoint (création) ; la re-autorisation passe par `POST .../{id}/reauthorize` qui crée sa propre pending_session avec `target_connection_id` rempli.

**Effet** : génère `state` (32 bytes URL-safe), INSERT `oauth_pending_session(provider='gdrive', payload={client_id, client_secret, redirect_uri, scope, folder_name, name}, expires_at=NOW+10min, target_connection_id=NULL)`.

**Response** : `{ auth_url, state }` où `auth_url` =

```
https://accounts.google.com/o/oauth2/v2/auth?
  response_type=code&
  access_type=offline&
  prompt=consent&
  scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file&
  client_id=...&
  redirect_uri=...&
  state=...
```

`access_type=offline` + `prompt=consent` garantit qu'on récupère un refresh_token (Google n'en renvoie pas si l'utilisateur a déjà consenti antérieurement et qu'on ne force pas le consent).

### `GET .../callback?code=&state=&error=`

**Effet** :
1. SELECT pending_session WHERE state=$1 AND status='pending' AND expires_at > NOW.
2. Si `error` présent (`access_denied`, etc.) : UPDATE status='failed', result={error}.
3. Sinon : échange `code` contre tokens via `Flow.fetch_token()`. Récupère `user_email` via décodage de l'`id_token` Google ou via `oauth2.googleapis.com/tokeninfo`.
4. UPDATE pending_session SET status='authorized', result={refresh_token, user_email, token_uri}.

**Response** : HTML statique auto-fermant (template inline, pas Jinja2 requis) :

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Google Drive Authorization</title></head>
<body>
  <p>Authorization complete. This window will close automatically.</p>
  <script>
    (function () {
      var msg = { type: 'gdrive_oauth_done', state: %STATE%, ok: %OK%, error: %ERROR_OR_NULL% };
      if (window.opener) {
        window.opener.postMessage(msg, window.location.origin);
      }
      window.close();
    })();
  </script>
</body></html>
```

**Note délibérée** : `targetOrigin = window.location.origin` (pas `'*'`). HTML servi par Harpocrate, parent SPA servi par Harpocrate → même origin.

### `GET .../session/{state}`

Permet au frontend de lire le `result` **non-secret** après réception du `postMessage`.

**Response** : `{ status, result: { user_email } | null }` — ne contient **jamais** `refresh_token`, `client_secret`, ou autre clé sensible.

### `POST /admin/backup-remotes` (existant, étendu)

Quand `kind='gdrive'` :
- `body.credentials` peut être absent / null.
- `body.oauth_state` requis.
- SELECT pending_session par `oauth_state`, vérifie `status='authorized'` ET `provider='gdrive'`.
- Hydrate `config` depuis `payload + result` (folder_name, redirect_uri, client_id, user_email).
- Hydrate `credentials` depuis `payload + result` (client_secret, refresh_token, scope, token_uri).
- INSERT remote_backup_connection (chiffrement AES-GCM existant).
- DELETE pending_session.

### `POST .../{id}/reauthorize`

Pour une connexion `gdrive` existante dont le refresh_token est révoqué.

**Effet** :
- Récupère `client_id`, `client_secret`, `redirect_uri`, `folder_name` de la connexion existante.
- Crée une nouvelle `oauth_pending_session` (provider=`gdrive`, payload=mêmes valeurs, `target_connection_id={id}`).
- Retourne `{ auth_url, state }`.

**Au callback** réussi, le backend détecte `target_connection_id` non-null et UPDATE la connexion existante avec le nouveau `refresh_token` (au lieu d'INSERT).

### Service `gdrive_oauth_session.py`

Nouveau service dédié au cycle OAuth (création de session, échange de code, finalisation) — distinct du service `remote_backup_connections` qui ne s'occupe que de la table principale. Évite que `remote_backup_connections.py` ne gonfle avec de la logique OAuth.

---

## 6. Frontend

### Architecture du modal

Le modal existant (`ConnectionFormModal`) reste UN seul composant qui gère tous les kinds. On y ajoute `GDriveFields` comme les autres `*Fields`, MAIS ce composant interne porte sa propre machine à états (3 steps logiques) au lieu d'être un formulaire plat. Le wizard ne déborde pas hors du modal — on garde la même boîte, on swap le contenu.

#### Step 1 — Application OAuth Google

```
Nom : [Backups perso         ]
Type : [Google Drive            ▼]

┌─ Application OAuth Google ──────────────────────┐
│ Pour créer cette connexion, tu dois d'abord     │
│ créer une application OAuth dans Google Cloud   │
│ Console. [Voir le guide ↗]                      │
│                                                 │
│ Client ID        : [................        ]   │
│ Client Secret    : [••••••••••••••           ]   │
│ Redirect URI     : [https://harpo.../callback]   │
│   ↑ à coller dans "Authorized redirect URIs"    │
│     [📋 Copier]                                  │
│ Nom du dossier   : [Harpocrate Backups        ]  │
│                                                 │
│              [Autoriser avec Google →]          │
└─────────────────────────────────────────────────┘
```

#### Step 2 — Pendant l'autorisation

```
┌─ Autorisation Google ────────────────────────────┐
│ ⏳ Fenêtre Google ouverte — autorise puis        │
│    reviens ici. (Bloqué par popup ? clique       │
│    [Ouvrir dans un onglet] pour le fallback.)    │
└──────────────────────────────────────────────────┘
```

#### Step 3 — Confirmation

```
┌─ Confirmation ──────────────────────────────────┐
│ ✓ Autorisé en tant que admin@gmail.com          │
│   Dossier cible : Harpocrate Backups (sera créé │
│   au premier upload)                            │
│                                                 │
│   [Recommencer]            [Sauvegarder ✓]      │
└─────────────────────────────────────────────────┘
```

### Mécanique technique du popup OAuth

`frontend/src/lib/gdriveOAuth.ts` :

```typescript
interface GDrivePostMessage {
  type: 'gdrive_oauth_done';
  state: string;
  ok: boolean;
  error?: string;
}

export async function runGDriveOAuthFlow(params: {
  client_id: string;
  client_secret: string;
  folder_name: string;
  name: string;
}): Promise<{ state: string; user_email: string }> {
  // (le redirect_uri n'est PAS un param — le backend l'injecte à partir de HARPOCRATE_PUBLIC_URL ;
  //  l'UI le récupère via GET .../redirect-uri pour affichage read-only seulement)
  // (pas de target_connection_id ici — la re-autorisation passe par une fonction dédiée
  //  reauthorizeGDriveConnection(id) qui appelle directement POST /{id}/reauthorize)
  // 1. POST /oauth/gdrive/start -> { auth_url, state }
  // 2. window.open(auth_url, 'gdrive_oauth', POPUP_FEATURES)
  //    - si null: throw PopupBlockedError -> UI offre fallback "ouvrir dans un onglet"
  // 3. await message via Promise + window.addEventListener('message', ...)
  //    - filtre strict: event.origin === window.location.origin
  //                  && event.data?.type === 'gdrive_oauth_done'
  //                  && event.data.state === state
  //    - fallback: interval qui vérifie popup.closed -> reject "oauth_aborted"
  // 4. GET /oauth/gdrive/session/{state} pour récupérer user_email (non-secret)
}
```

### Sécurité côté frontend

- **Filtre strict** sur `event.origin` (même origin que l'app).
- **Vérifie `event.data.state`** correspond au state attendu → double protection CSRF.
- Le `client_secret` ne reste dans le state React du form que le temps de l'envoi POST `/start` — après ça, il vit côté DB et n'est jamais ré-affiché.

### Bouton "Re-autoriser" sur les connexions existantes

Dans la table de `AdminRemoteBackupsPage`, pour les lignes `kind='gdrive'` uniquement, on ajoute `[Re-autoriser]` à côté de Edit/Delete. Comportement :
- POST `/admin/backup-remotes/{id}/reauthorize` → `{ auth_url, state }`.
- Réutilise exactement le même flow popup + postMessage.
- Le `state` porte `target_connection_id` → le backend UPDATE au lieu d'INSERT.

**Edit pour les Drive** : limité à `name` et `folder_name` (renommage). L'admin ne peut pas re-saisir un client_secret sans relancer l'OAuth complet — incohérent avec le refresh_token. Pour changer de client OAuth, supprimer et recréer.

### Affichage dans la table de la page principale

La cellule `host` (qui sert pour SFTP/FTPS/S3) devient `Connecté en tant que <user_email>` pour les Drive. La cellule `paths` montre le `folder_name`. Adaptation minimale du composant existant.

### `adminApi.ts` — nouvelles fonctions

```typescript
export async function startGDriveOAuth(body: {...}): Promise<{ auth_url: string; state: string }>;
export async function fetchGDriveOAuthSession(state: string):
  Promise<{ status: 'pending'|'authorized'|'failed'; result?: { user_email: string } }>;
export async function reauthorizeGDriveConnection(id: string):
  Promise<{ auth_url: string; state: string }>;
// createRemoteBackupConnection accepte un oauth_state optionnel, requis quand kind === 'gdrive'.
```

### i18n — clés ajoutées (FR + EN)

```
admin.remoteBackups.kind.gdrive                  = "Google Drive"
admin.remoteBackups.gdrive.step1Title            = "Application OAuth Google"
admin.remoteBackups.gdrive.step1Desc             = "Crée une app OAuth dans Google Cloud Console…"
admin.remoteBackups.gdrive.fieldClientId         = "Client ID"
admin.remoteBackups.gdrive.fieldClientSecret     = "Client Secret"
admin.remoteBackups.gdrive.fieldRedirectUri      = "Redirect URI"
admin.remoteBackups.gdrive.fieldRedirectUriHint  = "À copier-coller dans les Authorized redirect URIs de ton app Google Cloud."
admin.remoteBackups.gdrive.fieldFolderName       = "Nom du dossier sur Drive"
admin.remoteBackups.gdrive.btnAuthorize          = "Autoriser avec Google"
admin.remoteBackups.gdrive.popupBlocked          = "Popup bloquée par le navigateur."
admin.remoteBackups.gdrive.openInTab             = "Ouvrir dans un onglet"
admin.remoteBackups.gdrive.waitingAuth           = "Fenêtre Google ouverte — autorise puis reviens ici."
admin.remoteBackups.gdrive.authorizedAs          = "Autorisé en tant que {{email}}"
admin.remoteBackups.gdrive.aborted               = "Autorisation annulée."
admin.remoteBackups.gdrive.btnRestart            = "Recommencer"
admin.remoteBackups.gdrive.btnReauthorize        = "Re-autoriser"
admin.remoteBackups.gdrive.credentialsRevoked    = "Re-autorisation requise — le token a été révoqué côté Google."
admin.remoteBackups.gdrive.guideLink             = "Voir le guide"
```

---

## 7. Gestion d'erreurs

### Catalogue complet

| Cas | Détection | Comportement |
|---|---|---|
| **`access_denied`** (refus consent screen) | `?error=access_denied` au callback | `status='failed'`, postMessage `{ok:false, error:'access_denied'}` → modal affiche "Autorisation refusée. Tu peux recommencer." |
| **`invalid_grant`** (refresh token révoqué) | `Credentials.refresh()` lève `RefreshError` | Provider lève `RemoteBackupProviderError("credentials_revoked")`. L'UI affiche un badge rouge sur la connexion + bouton "Re-autoriser" proéminent. |
| **`invalid_client`** (client_secret faux) | `Flow.fetch_token()` lève `OAuth2Error` au callback | `status='failed'`, message clair "Client Secret invalide". |
| **Popup bloquée** | `window.open` retourne `null` | Fallback `window.open(auth_url, '_blank')` + polling `GET /session/{state}` toutes les 2s pendant 5 min. |
| **Popup fermée sans valider** | Interval `popup.closed === true` | Resolve avec `{ok:false, error:'aborted'}` → step revient à 1. |
| **`state` invalide/expiré au callback** | SELECT renvoie 0 lignes ou `expires_at < NOW` | Page HTML d'erreur (pas de postMessage — l'opener pourrait être malveillant). Frontend détecte timeout via `popup.closed` sans message. |
| **`state` déjà consommé (replay)** | Pending session déjà DELETE par save précédent | Page HTML d'erreur 400. Même si attaquant rejoue le `code`, Google le rejette aussi (single-use). |
| **Quota Drive dépassé** | `HttpError 403 userRateLimitExceeded` ou 429 | `RemoteBackupProviderError("drive_quota_exceeded")`. Pas de retry auto. |
| **Storage Drive plein** | `HttpError 403 storageQuotaExceeded` | `RemoteBackupProviderError("drive_storage_full")`. Message clair UI. |
| **Network timeout** | `socket.timeout` / `httpx.TimeoutException` | `RemoteBackupProviderError("network_timeout")`. Push scheduler retentera au prochain cycle (comportement existant). |

**Principe directeur** : aucune erreur silencieuse. Chaque chemin a un mapping vers un message d'admin lisible. Pattern existant des providers respecté (`RemoteBackupProviderError` avec message technique, traduit en `ok:false` + message côté route admin).

---

## 8. Sécurité — invariants à garantir

1. **`client_secret` et `refresh_token` ne quittent jamais le backend après création.** Aucune réponse HTTP ne les expose. Test dédié : `GET /admin/backup-remotes/{id}` ne retourne aucune clé contenant `secret` ou `refresh`.
2. **`state` OAuth = 32 bytes URL-safe via `secrets.token_urlsafe(32)`** — pas de timestamp prédictible.
3. **TTL strict 10 min sur `oauth_pending_session`** — purgé au prochain cycle scheduler ET vérifié à chaque SELECT (deux barrières).
4. **DELETE au lieu de UPDATE status='consumed'** — plus simple, et `state UNIQUE` garantit qu'un re-call retourne 0 lignes.
5. **`event.origin === window.location.origin`** côté front + `targetOrigin === window.location.origin` côté HTML callback.
6. **`access_type=offline` + `prompt=consent`** dans l'URL OAuth → garantit un refresh_token à chaque flow.
7. **Scope verrouillé à `drive.file`** dans le code backend — l'admin ne peut pas l'élargir via le form.
8. **`redirect_uri` validé strictement** côté backend : doit être identique à `HARPOCRATE_PUBLIC_URL + /v1/admin/backup-remotes/oauth/gdrive/callback`.
9. **Audit log** : entries pour `remote_backup.gdrive.oauth_started`, `.oauth_completed`, `.oauth_failed`, `.reauthorized`, avec `actor_user_id` + `connection_name` (jamais le secret).

---

## 9. Tests

### Backend (pytest + pytest-asyncio)

| Test | Vérifie |
|---|---|
| `test_oauth_session_migration` | Table `oauth_pending_session` existe avec bonnes colonnes/contraintes |
| `test_remote_backup_kinds_gdrive_migration` | CHECK accepte `gdrive` après application |
| `test_gdrive_provider_test_connection_creates_folder` | Mock gdrive_client : si folder absent, create + retourne `{folder_id}` |
| `test_gdrive_provider_test_connection_finds_existing_folder` | Si folder présent, retourne son id sans create |
| `test_gdrive_provider_test_connection_refresh_error` | `Credentials.refresh` lève `RefreshError` → `RemoteBackupProviderError("credentials_revoked")` |
| `test_gdrive_provider_upload_stream_chunked` | Mock `MediaIoBaseUpload` resumable, vérifie bytes_written |
| `test_gdrive_provider_upload_quota_exceeded` | HttpError 403 storageQuotaExceeded → message clair |
| `test_oauth_start_creates_pending_session` | POST `/start` insère ligne avec TTL 10 min + retourne auth_url avec bons params |
| `test_oauth_start_invalid_redirect_uri` | redirect_uri ≠ attendu → 400 |
| `test_oauth_callback_happy_path` | Mock `Flow.fetch_token` → session `authorized` + result rempli |
| `test_oauth_callback_state_expired` | `expires_at < NOW` → 400 |
| `test_oauth_callback_state_consumed` | Replay → 400 |
| `test_oauth_callback_user_refused` | `?error=access_denied` → status='failed', HTML d'erreur |
| `test_oauth_session_lookup_hides_secrets` | `GET /session/{state}` ne contient ni `refresh_token` ni `client_secret` |
| `test_create_gdrive_connection_consumes_session` | POST avec `oauth_state` valide INSERT + DELETE pending session |
| `test_create_gdrive_connection_unauthorized_session` | state pointe sur session `pending`/`failed` → 422 |
| `test_get_connection_hides_secrets` | Réponse JSON sans clé `secret` / `refresh_token` |
| `test_reauthorize_updates_existing_connection` | Re-auth → UPDATE refresh_token, pas de nouvelle ligne |
| `test_purge_expired_oauth_sessions` | DELETE des expirées, ne touche pas les vivantes |
| `test_kind_gdrive_in_supported_kinds` | `SUPPORTED_KINDS` contient `gdrive` |

### Frontend (Vitest + RTL)

| Test | Vérifie |
|---|---|
| `gdriveOAuth.test.ts` — happy path | Mock `window.open` + `postMessage`, resolve avec state + user_email |
| `gdriveOAuth.test.ts` — popup bloquée | `window.open` null → throws `PopupBlockedError` |
| `gdriveOAuth.test.ts` — origin différente filtrée | postMessage depuis origin ≠ ignoré |
| `gdriveOAuth.test.ts` — state mismatch filtré | postMessage avec mauvais state ignoré |
| `gdriveOAuth.test.ts` — popup fermée sans message | `popup.closed === true` → reject `aborted` |
| `AdminRemoteBackupsPage.test.tsx` — sélection kind=gdrive | Affiche `GDriveFields` step 1, masque les autres |
| `AdminRemoteBackupsPage.test.tsx` — wizard step transitions | Step 1 → click → step 2 → message reçu → step 3 |
| `AdminRemoteBackupsPage.test.tsx` — bouton Re-autoriser visible uniquement sur gdrive | SFTP/S3/FTPS ne le voient pas |

### Stratégie de mocking backend

Tous les appels Google passent par `gdrive_client.py` (fine couche d'abstraction sur `googleapiclient.discovery.build`, `Flow.from_client_config`, etc.). Les tests mockent cette couche, pas `googleapiclient` directement.

---

## 10. Documentation utilisateur

Nouveau guide `docs/admin/gdrive-setup.md` (référencé par le bouton "Voir le guide" dans le modal) :

1. Aller sur Google Cloud Console → créer un projet.
2. APIs & Services → Library → activer "Google Drive API".
3. OAuth consent screen → External (Testing) ou Internal (Workspace), scope `drive.file`, add test users.
4. Credentials → Create OAuth client ID → type "Web application".
5. Authorized redirect URIs → coller la valeur fournie par le modal Harpocrate.
6. Copier Client ID + Client Secret dans le modal Harpocrate.
7. Cliquer "Autoriser avec Google".

Captures d'écran minimalistes dans `docs/admin/gdrive-setup-screens/`.

---

## 11. Limitations connues (à documenter)

- **Apps OAuth en mode "Testing" Google** : maximum 100 utilisateurs test déclarés, ET le `refresh_token` est forcé à expirer après **7 jours d'inactivité** (le user doit re-autoriser). Pour usage perso, suffit largement si l'instance backupe régulièrement (le refresh est utilisé donc le token reste vivant). Pour usage durable, passer l'app en "Production" Google Cloud Console — verification automatique sur scope non-sensitive `drive.file` (généralement instantanée pour ce scope, quelques jours pour des scopes plus larges). Une fois en Production, refresh_token long-lived sans rotation forcée.
- **Pas de partage de dossier** : le dossier `Harpocrate Backups` est dans le Drive du compte autorisateur. Changement de compte = nouvelle connexion.
- **Pas de listing remote** côté UI Harpocrate (volontaire, scope minimal). Pour voir/télécharger les backups, l'admin ouvre directement Drive.

---

## 12. Hors-scope (NON traité ici)

- Service Account / Shared Drives Workspace (futur LOT séparé si besoin).
- Scope `drive` complet (accès à tout le Drive de l'utilisateur) — refusé délibérément (review Google requise, surface d'attaque).
- Listing / téléchargement / restauration depuis Drive via l'UI Harpocrate.
- Synchronisation bidirectionnelle.
- Support d'autres providers OAuth (Dropbox, OneDrive) — la table `oauth_pending_session.provider` est prête mais aucun handler n'est implémenté.

---

## 13. Récapitulatif des artefacts à créer/modifier

### Migrations
- `backend/migrations/030_remote_backup_kinds_gdrive.sql` (nouveau)
- `backend/migrations/031_oauth_pending_session.sql` (nouveau)

### Backend Python
- `backend/src/app/services/remote_backup_providers/gdrive.py` (nouveau)
- `backend/src/app/services/remote_backup_providers/gdrive_client.py` (nouveau — couche d'abstraction pour tests)
- `backend/src/app/services/remote_backup_providers/__init__.py` (modif — factory + SUPPORTED_KINDS)
- `backend/src/app/services/remote_backup_providers/base.py` (modif — interface évolue)
- `backend/src/app/services/remote_backup_providers/{sftp,s3_compatible,ftps}.py` (modif mineure — `return None` explicite)
- `backend/src/app/services/gdrive_oauth_session.py` (nouveau)
- `backend/src/app/db/repositories/oauth_pending_session.py` (nouveau)
- `backend/src/app/api/v1/admin_remote_backups_oauth_gdrive.py` (nouveau — router dédié)
- `backend/src/app/api/v1/admin_remote_backups.py` (modif — extension POST pour `kind=gdrive` + `oauth_state`)
- `backend/src/app/services/snapshot_scheduler.py` (modif — ajout purge_expired_oauth_sessions)
- `backend/src/app/main.py` (modif — register du nouveau router)
- `backend/pyproject.toml` (modif — 3 deps Google)

### Frontend
- `frontend/src/lib/gdriveOAuth.ts` (nouveau)
- `frontend/src/lib/adminApi.ts` (modif — startGDriveOAuth, fetchGDriveOAuthSession, reauthorizeGDriveConnection, oauth_state dans createRemoteBackupConnection)
- `frontend/src/pages/AdminRemoteBackupsPage.tsx` (modif — `GDriveFields`, kind='gdrive' dans select, cellules Host/Paths adaptées, bouton Re-autoriser)
- `frontend/src/schemas/admin.ts` (modif — types pour gdrive)
- `frontend/src/i18n/fr.json` + `en.json` (modif — clés gdrive)

### Tests
- `backend/tests/test_oauth_pending_session_migration.py`
- `backend/tests/test_remote_backup_kinds_gdrive_migration.py`
- `backend/tests/test_gdrive_provider.py`
- `backend/tests/test_admin_remote_backups_oauth_gdrive.py`
- `backend/tests/test_admin_remote_backups_create_gdrive.py`
- `frontend/src/lib/gdriveOAuth.test.ts`
- `frontend/src/pages/AdminRemoteBackupsPage.test.tsx` (extension)

### Documentation
- `docs/admin/gdrive-setup.md` (nouveau)
- `docs/admin/gdrive-setup-screens/` (captures d'écran)

---

**Fin de spec.**
