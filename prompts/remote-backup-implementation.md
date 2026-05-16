# Brief — Implémenter un système de backup de base de données vers un service distant

> **À l'attention de l'agent IA qui prend ce brief** : il s'agit d'une spec
> fonctionnelle complète, distillée d'une implémentation déjà en production.
> Adapte la stack à ton projet (FastAPI/Django/Express/Rails…), mais respecte
> les invariants fonctionnels et les pièges documentés en bas.
> N'invente pas de scope au-delà de ce qui est demandé. Si une décision n'est
> pas couverte ici, demande à l'utilisateur — ne décide pas seul.

---

## 1. Contexte fonctionnel

Une application web administrable possède une base de données (PostgreSQL,
MySQL, MongoDB — peu importe). On veut permettre à un admin de :

1. **Déclarer** une ou plusieurs **connexions distantes** (SFTP, S3-compatible,
   FTPS) où l'application pourra pousser des dumps de sa base.
2. **Tester** la connexion depuis l'UI sans avoir à attendre un push réel.
3. **Pousser manuellement** un backup déjà créé vers une de ces connexions.
4. **Programmer** des pushs automatiques (déclenchés par un scheduler interne
   à l'app — cron-like ou à intervalle fixe).
5. **Voir l'état** : connexion saine ou pas, derniers push réussis/échoués.

Le système doit être **zero-knowledge sur les credentials** : une fois saisis,
ils ne sont jamais re-affichés.

> **⚠ Important — Stockage des credentials** : ce projet **N'IMPLÉMENTE PAS**
> son propre chiffrement local des credentials. Les credentials des connexions
> distantes (`{username, password}`, `{access_key_id, secret_access_key}`,
> etc.) sont stockés dans une **instance Harpocrate** distante (gestionnaire
> de secrets externe). Le projet doit utiliser le **SDK Harpocrate déjà
> intégré** (Python / JS / Rust / Go selon la stack) pour POST/GET les secrets.
> Voir section 2.5 pour le contrat fonctionnel attendu du SDK.

---

## 2. Décisions de design figées

Ces décisions sont issues d'un retour d'expérience sur un projet en prod.
Ne pas les remettre en cause sans raison forte.

### 2.1 Une connexion = N usages possibles

Une même connexion remote (1 host SFTP, 1 bucket S3) peut servir à plusieurs
usages : par exemple `snapshots automatiques fréquents` ET `full backups
manuels rares`. Pour ne pas dupliquer la connexion, **chaque connexion porte
plusieurs paths cible** :

- SFTP/FTPS : `remote_path_snapshots` + `remote_path_full` (chacun nullable)
- S3 : `prefix_snapshots` + `prefix_full` (chacun nullable)

Une connexion peut n'avoir qu'un seul des deux configuré (ex: dédiée aux
snapshots uniquement).

### 2.2 Test de connexion : 200 OK systématique

L'endpoint `POST /test-connection` retourne **TOUJOURS HTTP 200**, avec un
body `{ok: true}` ou `{ok: false, error: "...", message: "détail lisible"}`.

**Pourquoi** : Cloudflare et beaucoup de reverse-proxies remplacent les 5xx
par leur propre page d'erreur générique, ce qui masque le message du
provider (essentiel pour diagnostiquer "permission denied", "no such file",
"connection refused"). Un 200 avec un payload d'erreur passe.

### 2.3 Provider abstraction stateless sur le path

Définir une interface :

```python
class RemoteBackupProvider(Protocol):
    async def test_connection(self, path: str) -> None: ...
    async def upload_stream(self, path: str, filename: str,
                            source: AsyncIterator[bytes]) -> int: ...
```

Le `path` (ou prefix S3) est passé en argument à chaque opération, **pas**
stocké dans le constructeur. Cela permet à une même instance de provider
de cibler plusieurs paths sans réinstancier.

### 2.4 Streaming pour SFTP/FTPS, fichier temp pour S3

- **SFTP** : utiliser `asyncssh` (Python) ou équivalent natif async. Streaming
  natif via `sftp.open(path, 'wb')` + write chunks.
- **FTPS** : utiliser `aioftp` ou équivalent. Streaming natif.
- **S3** : utiliser le SDK officiel (boto3 / AWS SDK / etc.). Le multipart
  upload nécessite généralement un fileobj — donc bufferiser le stream dans
  un fichier temporaire local (cleanup garanti via `try/finally`). Coût disque
  = taille du backup, libéré à la fin.

Chunk size recommandée : **64 KiB**. Lit le fichier dans un thread pool
(`asyncio.to_thread`) pour ne pas bloquer la boucle.

### 2.5 Credentials : stockés dans Harpocrate via le formalisme déclaratif

**Principe** : ce projet **ne stocke pas** les credentials en local (pas de
table `credentials_encrypted BYTEA`, pas d'AES-GCM maison). Les credentials
sont délégués à une instance **Harpocrate** distante, via :

1. Le **formalisme déclaratif `${vault://api_key_id:path}`** pour référencer
   le secret en DB.
2. Le **SDK Harpocrate** pour les opérations CRUD sur le secret côté Harpocrate.
3. Le **loader** du formalisme pour la résolution lecture (run-time).

Le formalisme complet est documenté en **annexe A** de ce document. Lis-la
AVANT de coder cette section.

**Modèle de stockage en DB locale** :

Au lieu de stocker un blob chiffré, on stocke une **référence textuelle** vers
le secret. Trois colonnes :

| Colonne | Type | Notes |
|---|---|---|
| `vault_api_key_id` | TEXT NULL | Identifiant de l'API key Harpocrate (ex: `"prod"`, `"api1"`). Configuré globalement via `HARPOCRATE_VAULT_API_KEY_ID` — l'admin ne le choisit pas par connexion. |
| `vault_secret_path` | TEXT NULL | Path déterministe : `remote-backups/{connection_uuid}`. Généré par l'app, pas saisi. |

Les deux colonnes sont NULL ensemble (pas de creds) ou non-NULL ensemble.
La référence pour le loader se construit à la volée :
```
ref = f"${{vault://{vault_api_key_id}:{vault_secret_path}}}"
```

**Contenu du secret** stocké côté Harpocrate (objet structuré, ex pour SFTP) :
```json
{
  "username": "harpo-backup",
  "auth_method": "password",
  "password": "..."
}
```

**Convention de path déterministe** : `remote-backups/{connection_uuid}` —
immuable (uuid de la connexion), pas de collision possible, facile à
identifier côté admin Harpocrate. Si tu veux segmenter par environnement,
préfixer par exemple `prod/remote-backups/...` mais **garde déterministe**.

**Opérations attendues du SDK Harpocrate** (en plus du loader read-only) :

| Opération | Quand | Notes |
|---|---|---|
| `client.put_secret(path, payload)` | Création / re-saisie de credentials | `path` = ce que l'app a généré, payload = dict |
| `client.delete_secret(path)` | Suppression de la connexion | Best-effort : si Harpocrate est down, log warning + delete row locale quand même |

Pour la **lecture**, on n'appelle PAS le SDK directement — on passe par le
loader avec la référence `${vault://...}` (cohérent avec le reste du projet).

**Rotation/changement de credentials** : à l'update d'une connexion, si
l'admin re-saisit les credentials, on fait `client.put_secret(same_path,
new_payload)` — le path est déterministe (UUID de la connexion), donc
inchangé. Pas de gestion d'historique chaîné côté app — Harpocrate gère
ses versions en interne s'il en a.

**UI — flag `has_credentials`** : le DTO de connexion expose `has_credentials:
bool = vault_secret_path IS NOT NULL`. L'UI affiche :
- `has_credentials=true` → alerte verte « ✓ Identifiants enregistrés (Vault).
  Laisser les champs vides pour les conserver. »
- `has_credentials=false` → alerte orange « ⚠ Aucun identifiant. Saisissez-les
  pour activer la connexion. »

L'UI **ne fait jamais d'appel direct** au SDK Harpocrate — elle passe par
les endpoints HTTP du backend qui orchestre.

**Gestion d'indisponibilité Harpocrate** : si Harpocrate est down quand le
loader essaie de résoudre une référence, le push échoue avec une erreur
explicite (`"vault_unavailable"`). Logger une anomalie système (cf. 2.8).
Le scheduler retentera au prochain tick.

**Variables d'environnement requises** (à documenter dans `.env.example`) :
```bash
# Identifiant de l'API key utilisée par CE module pour les remote backups.
# Doit correspondre à un suffixe ${ID} déclaré ci-dessous.
HARPOCRATE_VAULT_API_KEY_ID=prod

# Variables d'amorçage : une paire (TOKEN, URL) par api_key_id.
# Le suffixe (ici PROD) doit matcher (insensible à la casse) les
# api_key_id utilisés dans les références ${vault://prod:...}.
HARPOCRATE_API_TOKEN_PROD=hrp_1_xxxxxxxxxxxxxxxxxxxx
HARPOCRATE_API_URL_PROD=https://vault.example.com
```

Plusieurs `api_key_id` peuvent coexister (`API_TOKEN_API1`, `API_TOKEN_PROD`,
etc.) — le module remote-backups n'en utilise qu'un seul, désigné par
`HARPOCRATE_VAULT_API_KEY_ID`. Les autres `api_key_id` peuvent être utilisés
par d'autres modules de l'app (configuration générale, secrets externes,
etc.) via le même loader.

### 2.6 Sérialisation des opérations longues

Si l'app a déjà un scheduler interne (snapshots automatiques) ET un système
de backup manuel ET un push manuel, **un seul `pg_dump` ou équivalent à la
fois**. Sinon : doublement CPU/IO/RAM, contention disque, requêtes user qui
timeout.

Pattern : un `asyncio.Lock` (ou équivalent thread-safe selon le langage)
exposé via un module commun (`backup_lock`), acquis par tous les workers
qui font des opérations lourdes.

### 2.7 Skip-if-no-change

Avant de lancer un backup automatique programmé, comparer :
- `MAX(updated_at)` des tables métier significatives (users, données
  business, audit log)
- `MAX(created_at) FROM table_des_backups_locaux`

Si le dernier backup est plus récent que la dernière modification → skip
(status = `skipped`, raison loggée). Évite de remplir le stockage distant
avec des backups bit-à-bit identiques.

### 2.8 Anomalies système pour les échecs de push automatique

Quand un push automatique échoue (pas un test manuel), créer un événement
dans une table d'**anomalies système** (différente des anomalies par-utilisateur
si tu en as déjà une) avec :
- `severity` : info / warning / critical
- `source` : ex `"snapshot_remote_push"`
- `source_ref_id` : UUID du remote concerné
- `message` : texte lisible
- `metadata` : JSONB avec contexte (filename, error détaillé, etc.)
- `acknowledged_at` / `acknowledged_by_user_id`

**Hystérésis** : ne créer qu'**une seule anomalie ouverte (non-ack) par
(source_ref_id, severity)** à la fois. Si une est déjà ouverte, on ne
re-crée pas — sinon on spam à chaque tick. L'UI affiche le compteur
d'anomalies non-ack.

---

## 3. Modèle de données

### Table `remote_backup_connection`

| Champ | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | TEXT NOT NULL | unique (case-insensitive) |
| kind | TEXT NOT NULL | CHECK in ('sftp', 's3', 'ftps') |
| config | JSONB NOT NULL DEFAULT `{}` | host, port, paths, etc. selon kind |
| vault_api_key_id | TEXT NULL | api_key_id Harpocrate (ex: `"prod"`). NULL = creds non configurés. |
| vault_secret_path | TEXT NULL | path déterministe `remote-backups/{id}`. NULL en même temps que `vault_api_key_id`. |
| created_at, updated_at | TIMESTAMPTZ | trigger updated_at |
| created_by_user_id | UUID FK NULL | ON DELETE SET NULL |
| deleted_at | TIMESTAMPTZ NULL | soft-delete |

CHECK contraint :
```sql
CHECK (
  (vault_api_key_id IS NULL AND vault_secret_path IS NULL) OR
  (vault_api_key_id IS NOT NULL AND vault_secret_path IS NOT NULL)
)
```

> **Note** : pas de colonne `credentials_encrypted` — les credentials vivent
> dans Harpocrate, pas en local. Voir 2.5 et **annexe A**.

**Schéma de `config` selon `kind`** :

```json
// SFTP
{
  "host": "sftp.example.com",
  "port": 22,
  "host_key_fingerprint": "SHA256:...",   // optionnel, TOFU si absent
  "remote_path_snapshots": "/snapshots",  // optionnel
  "remote_path_full": "/full"              // optionnel
}

// FTPS
{
  "host": "ftp.example.com",
  "port": 21,
  "use_tls": true,
  "remote_path_snapshots": "...",
  "remote_path_full": "..."
}

// S3
{
  "endpoint_url": "https://s3.fr-par.scw.cloud",   // vide pour AWS
  "region": "fr-par",
  "bucket": "my-backups",
  "path_style": true,                              // true pour R2/B2/MinIO
  "prefix_snapshots": "snapshots/",                // optionnel
  "prefix_full": "full/"                           // optionnel
}
```

### Table `system_anomaly_events` (si tu n'as pas d'équivalent)

| Champ | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| detected_at | TIMESTAMPTZ DEFAULT NOW() | |
| severity | TEXT CHECK in ('info','warning','critical') | |
| anomaly_type | TEXT | ex `"remote_push_failed"` |
| source | TEXT | ex `"snapshot_remote_push"` |
| source_ref_id | UUID NULL | ID de l'objet concerné |
| message | TEXT | lisible UI |
| metadata | JSONB | contexte technique |
| acknowledged_at | TIMESTAMPTZ NULL | |
| acknowledged_by_user_id | UUID FK NULL | |

Index :
- `(detected_at DESC) WHERE acknowledged_at IS NULL` — query dominante UI
- `(source, source_ref_id)` — group by remote

---

## 4. Composants à implémenter

### 4.1 Backend

#### Module `vault/loader` (résolution de références déclaratives)

Implémente le formalisme `${vault://api_key_id:path}` et `${env://VAR}` (cf.
annexe A). À implémenter une fois si le projet n'a pas déjà ce loader.

Si le projet a déjà un loader pour ses configs, **réutilise-le tel quel**.
Ce module remote-backups consommera juste l'API publique du loader :

```python
# API publique attendue du loader (à mapper sur l'existant si déjà présent) :
def resolve_reference(ref: str) -> str | dict:
    """Résout une référence ${vault://...} ou ${env://...} → valeur."""
```

Pour notre cas, la valeur résolue est un **dict** (le payload JSON du
secret), pas une string. Si le loader existant ne supporte que les strings,
on appelle le SDK Harpocrate directement pour la lecture du secret remote-
backup (le path est connu, le client aussi). Demande à l'utilisateur si
ce n'est pas clair.

#### Module `vault/client` (wrapper SDK pour CRUD)

Le loader est read-only. Pour create/update/delete d'un secret, on a besoin
d'un client direct au SDK Harpocrate.

```python
class HarpocrateVaultClient:
    def __init__(self, url: str, token: str): ...
    async def put_secret(self, path: str, payload: dict) -> None: ...
    async def get_secret(self, path: str) -> dict: ...
    async def delete_secret(self, path: str) -> None: ...
```

Construit depuis `HARPOCRATE_API_TOKEN_{ID}` + `HARPOCRATE_API_URL_{ID}` où
`{ID}` = `HARPOCRATE_VAULT_API_KEY_ID` en upper-case. Le projet peut déjà
avoir une factory `build_clients(api_keys)` (cf. annexe A) — réutilise-la.

#### Module `services/remote_backup_connections`
- DTO `RemoteBackupConnection` avec :
  - `vault_api_key_id: str | None`
  - `vault_secret_path: str | None`
  - `has_credentials: bool` (= `vault_secret_path IS NOT NULL`)
- `list_connections(conn) -> list[DTO]` — n'appelle PAS le vault (juste la DB).
- `get_connection(conn, id) -> DTO | None` — idem.
- `fetch_credentials(vault_client, connection) -> dict | None` ⚠ **uniquement**
  pour les providers, jamais dans une réponse HTTP. Appelle
  `vault_client.get_secret(connection.vault_secret_path)`.
- `create_connection(conn, vault_client, name, kind, config, credentials, created_by) -> UUID`
  → génère `connection_id = uuid4()`, `path = f"remote-backups/{connection_id}"`,
  appelle `vault_client.put_secret(path, credentials)` PUIS insert row avec
  `vault_api_key_id` (depuis env) + `vault_secret_path = path`. Si insert
  échoue : `vault_client.delete_secret(path)` pour ne pas laisser d'orphelin.
- `update_connection(conn, vault_client, id, name?, config?, credentials?)`
  → si `credentials` fourni : `vault_client.put_secret(existing_path, ...)`
  (overwrite). Le path est immuable.
- `delete_connection(conn, vault_client, id)` — soft-delete row PUIS
  `vault_client.delete_secret(path)` best-effort.
- `resolve_path(config: dict, kind: str, usage: "snapshots"|"full") -> str | None`
  → factorise la convention `remote_path_*` vs `prefix_*` selon le kind
  (rien à voir avec le path Harpocrate — c'est le path côté serveur SFTP/S3).

#### Module `services/remote_backup_providers`
- Interface `RemoteBackupProvider` (Protocol) : `test_connection(path)` +
  `upload_stream(path, filename, source)`.
- `SftpProvider`, `FtpsProvider`, `S3CompatibleProvider` — chacun dans son
  fichier.
- Factory `get_provider(kind, config, credentials) -> Provider`.
- Exception commune `RemoteBackupProviderError`.

#### Endpoints HTTP (admin only)
- `GET    /admin/backup-remotes` — liste
- `POST   /admin/backup-remotes` — créer (creds chiffrés à l'insert)
- `GET    /admin/backup-remotes/{id}` — détail (sans creds)
- `PATCH  /admin/backup-remotes/{id}` — update partiel (creds re-chiffrés si fournis, sinon préservés)
- `DELETE /admin/backup-remotes/{id}` — soft-delete (204)
- `POST   /admin/backup-remotes/test` — body : `{kind, config, credentials, path}`. Pour la **création** ou **édition avec resaisie creds**.
- `POST   /admin/backup-remotes/{id}/test` — body : `{path, config?}`. Utilise les creds **stockés** (édition sans resaisir).
- `POST   /admin/backups/{backup_id}/push-to-remote/{remote_id}` — push manuel d'un backup local vers un remote (utilise `resolve_path("full")`).

**Codes HTTP** :
- Tests : **toujours 200**, body `{ok, error?, message?}`.
- Push : **422 Unprocessable Entity** si erreur provider (bypass Cloudflare),
  jamais 502.
- 409 si nom de connexion en doublon.

#### Worker périodique (si scheduler existant)
- Boucle async, tick à intervalle fixe (typique 60s pour scheduled, 30s pour
  monitoring lag).
- Acquiert le lock global `backup_lock` autour des opérations lourdes.
- Pour chaque schedule due : créer backup local + push selon `remote_id` configuré.

### 4.2 Frontend

- Page liste des connexions (1 ligne par connexion : nom, kind, host, paths).
- Modale création/édition :
  - Sélecteur de kind (SFTP/S3/FTPS) → champs spécifiques au kind affichés.
  - Champs credentials : si édition + `has_credentials=true`, alerte verte
    « Identifiants enregistrés. Laisser vide pour les conserver. ». Si
    `has_credentials=false`, alerte orange « Aucun identifiant enregistré ».
  - Pour chaque path (snapshots, full) : input + bouton **Tester** à côté.
    - Si form contient des creds saisis → utilise endpoint `/test`
    - Sinon (édition sans resaisie) → utilise `/{id}/test` avec creds DB
    - Affiche résultat ✓/✗ inline sous l'input
- Bouton Test n'utilise PAS le bouton Sauvegarder (test sans persister).
- Page liste : afficher les paths configurés (« non configuré » si vide).

### 4.3 i18n

Toutes les chaînes UI doivent passer par un système d'i18n (clés FR + EN
au minimum).

---

## 5. Pièges et leçons apprises (CRITIQUE)

### 5.1 SFTP chrooté

OpenSSH `ChrootDirectory` impose que la racine du chroot soit **owned by
root, non writable par d'autres**. Conséquence : l'utilisateur SFTP ne peut
PAS écrire à la racine de son chroot. Il faut un sous-dossier owned par lui.

L'admin doit faire (en SSH classique, pas SFTP) :
```bash
sudo mkdir -p /chroot_root/data
sudo chown user:user /chroot_root/data
sudo chmod 750 /chroot_root/data
```

Puis configurer le `remote_path` de la connexion sur `/data` (path **relatif
au chroot**, pas absolu côté serveur).

### 5.2 SFTP `open(path, "wb")` échoue si le parent n'existe pas

Contrairement à `os.open`, `sftp.open(path, "wb")` ne crée pas les répertoires
parents. Il faut faire `sftp.makedirs(parent_dir, exist_ok=True)` avant.

Mais `makedirs` peut aussi échouer (chroot, permissions). Helper recommandé :

```python
async def _ensure_path(sftp, path):
    try:
        await sftp.stat(path)  # déjà présent → OK
        return
    except (OSError, asyncssh.Error):
        pass
    try:
        await sftp.makedirs(path, exist_ok=True)
    except (OSError, asyncssh.Error) as exc:
        # Enrichir l'erreur avec realpath('.') pour révéler un chroot
        cwd = await sftp.realpath(".")
        raise RemoteBackupProviderError(
            f"SFTP cannot prepare path={path!r}: {exc}. "
            f"User home (after login) is {cwd!r}. "
            f"Either create the directory on the server or set path "
            f"to a directory accessible from {cwd!r}."
        )
```

Le `realpath('.')` révèle immédiatement à l'admin si l'user est chrooté
(et où) — diagnostic critique.

### 5.3 Slot/role Postgres : password jamais re-affichable

Si tu utilises ce pattern pour de la **réplication PostgreSQL** (créer un
rôle `replicator` avec password), le password est généré côté serveur,
**affiché UNE fois** dans la modale de création (mode "show & forget"), et
jamais re-affichable. Le hash dans `pg_authid` côté master est suffisant —
le client (standby) le saisira dans son `primary_conninfo`.

UI doit avoir un bouton « J'ai copié les commandes — fermer » non-skippable
(pas de close-on-click-outside, pas d'Escape).

### 5.4 Test de connexion = ping TCP minimum

Si tu ne stockes pas les creds permettant un vrai test (ex: replication),
le test minimum utile = **ping TCP** sur `host:port` via
`asyncio.open_connection` avec timeout 2s. Pas plus. C'est juste « le réseau
me laisse-t-il atteindre cette machine ». La validation fonctionnelle
(« le service répond-il correctement ») se fait par d'autres moyens.

### 5.5 Anomalies : hystérésis obligatoire

Sans hystérésis, un push automatique qui échoue toutes les 30s crée 2880
anomalies par jour. Toujours vérifier `WHERE acknowledged_at IS NULL` avant
d'en créer une nouvelle pour le même `(source_ref_id, severity)`.

### 5.6 Dependencies dans le Dockerfile

Si ton `Dockerfile` a une liste hardcodée de deps Python (au lieu de lire
`pyproject.toml`/`requirements.txt`), **garde la liste en sync manuellement**.
Sinon : container qui boot avec `ModuleNotFoundError` au prochain ajout de
dep. Refactor recommandé : `pip install .` avec un stub minimal.

### 5.7 Streaming sans bloquer la boucle

Pour lire un fichier local par chunks dans un coroutine :

```python
async def _stream_file_chunks(path: Path, chunk_size: int = 64 * 1024):
    f = await asyncio.to_thread(path.open, "rb")
    try:
        while True:
            chunk = await asyncio.to_thread(f.read, chunk_size)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(f.close)
```

`open()` et `read()` synchrones bloqueraient la boucle event sur les gros
fichiers. `asyncio.to_thread` les déporte dans le thread pool.

### 5.8 Vault Harpocrate — orphelins et incohérences

Trois cas à gérer :

1. **Insert DB échoue après `vault.store()` réussi** → secret orphelin dans
   le vault. Parade : `try/except` autour du repo insert, avec
   `vault.delete(secret_id)` best-effort dans le `except`.

2. **`vault.delete()` échoue à la suppression d'une connexion** → le
   secret reste dans le vault mais la connexion est supprimée. Parade :
   delete row LOCAL en premier, puis tentative delete vault. En cas
   d'échec vault, log warning « secret orphelin <secret_id>, à nettoyer
   manuellement ». Pas de retry auto (risque de boucle si Harpocrate down
   longtemps).

3. **`vault.fetch()` retourne 404** (secret supprimé hors-app) → le push
   échoue avec `"vault_secret_missing"`. Création d'une anomalie système.
   La connexion reste dans la DB mais devient inutilisable jusqu'à
   resaisie des credentials par l'admin.

### 5.9 Vault — pas d'appel inutile

Le SDK Harpocrate fait potentiellement un round-trip réseau à chaque appel.
**Ne PAS appeler `vault.fetch()` dans les listings** ou les vues de détail —
seulement au moment où un provider va réellement ouvrir une connexion. Le
flag `has_credentials` (calculé sur `harpocrate_secret_id IS NOT NULL`) est
suffisant pour l'UI.

### 5.10 Filename validation

Sécurité : avant `sftp.open(remote_path/filename, "wb")`, vérifier que le
filename ne contient ni `/` ni `\` :

```python
if "/" in remote_filename or "\\" in remote_filename:
    raise ValueError("remote_filename must not contain path separators")
```

Évite qu'un filename `"../etc/passwd"` (mal contrôlé en amont) sorte du
`remote_path`.

---

## 6. Plan d'implémentation suggéré

Découper en LOTs commitables, chacun testable indépendamment :

1. **LOT 1** : `vault_client` (wrapper SDK Harpocrate) + tests avec mock du
   SDK. Vérifie que les vars `HARPOCRATE_URL` / `HARPOCRATE_API_KEY` sont
   chargées et que les 4 opérations (store/fetch/delete/update) fonctionnent
   contre un vault mock.
2. **LOT 2** : repo + service `remote_backup_connections` + endpoints CRUD
   basiques (sans test connect ni push). Le service utilise `vault_client`
   pour les credentials. Tests unitaires avec vault mocké.
3. **LOT 3** : provider abstraction + 3 implémentations (SFTP/S3/FTPS).
   Tests avec mocks réseau (pas de SFTP/S3 réel).
4. **LOT 4** : endpoint test connect + endpoint push manuel.
5. **LOT 5** : UI page liste + modale création/édition + bouton test
   (utilise les endpoints, pas le SDK directement côté navigateur).
6. **LOT 6** : intégration au scheduler (si existant) + hystérésis anomalies.

Chaque LOT termine par : `tests passent`, `lint clean`, `commit`.

---

## 7. Ce que ce brief ne couvre PAS

- **SSH automation** côté Harpocrate (Harpocrate exécute les commandes
  master/standby lui-même). Garder pour plus tard si besoin.
- **Réplication asynchrone** (MQTT, etc.) pour des sites sans accès direct
  master↔standby.
- **Failover automatique** (Patroni, etc.).
- **Restore** depuis un backup distant (download + apply). C'est un autre
  workflow.

Si l'utilisateur demande l'un de ces points, c'est une nouvelle conversation
avec son propre brief.

---

## 8. Validation finale

Avant de déclarer le travail fini, vérifier :

- [ ] Les credentials ne sont **jamais** retournés par une API HTTP.
- [ ] Aucun chiffrement local maison — uniquement le SDK + formalisme Harpocrate.
- [ ] La table `remote_backup_connection` n'a **PAS** de colonne
      `credentials_encrypted` ; elle a `vault_api_key_id` + `vault_secret_path`
      (CHECK que les deux soient NULL ensemble ou non-NULL ensemble).
- [ ] Le `vault_secret_path` est déterministe : `remote-backups/{uuid}`.
      Pas de saisie admin, pas de collision possible.
- [ ] `vault_client.get_secret()` n'est appelé QUE par les providers (pas
      dans listings, pas dans GET détail).
- [ ] La création d'une connexion fait `vault_client.put_secret()` AVANT
      l'insert DB, avec rollback (`delete_secret`) si l'insert échoue.
- [ ] Le test connect retourne **toujours 200** (jamais 5xx).
- [ ] Les paths nullable acceptent vraiment NULL côté DB.
- [ ] Le push manuel échoue proprement avec **422** si le path n'est pas
      configuré (pas 500, pas 502).
- [ ] L'UI affiche `has_credentials: true` après création (et false avant).
- [ ] Le filename est validé contre les separators.
- [ ] Une anomalie de push raté n'est créée qu'une fois (hystérésis).
- [ ] `HARPOCRATE_URL` et `HARPOCRATE_API_KEY` sont documentées dans
      `.env.example` ; le boot échoue clairement si elles manquent.
- [ ] Les tests passent isolément (vault mocké, pas d'appel réseau réel).

---

## Annexe A — Formalisme de résolution déclarative Harpocrate

> ⚠ **Lis cette annexe AVANT d'implémenter la section 2.5.** Elle décrit le
> contrat exact du loader et du formalisme `${vault://...}` utilisé dans tout
> le projet pour référencer des secrets externes.

### Principe

Harpocrate utilise un formalisme de résolution déclarative pour référencer
des valeurs externes dans les configurations. Une référence déclare **une
action** et **ses paramètres** — un loader résout la valeur au runtime.

```
${<action>://<paramètres>}
```

Ce formalisme est résolu par le loader au démarrage de l'application (ou à
la demande pour les modules qui le justifient, comme remote-backups). Les
références ne sont jamais évaluées en dehors du loader — elles restent des
chaînes opaques jusqu'à la résolution.

### Actions disponibles

#### `vault://` — Lecture d'un secret Harpocrate

```
${vault://<api_key_id>:<path>}
```

| Composant | Type | Description |
|---|---|---|
| `vault` | action | Lire un secret dans le coffre Harpocrate |
| `api_key_id` | string | Identifiant de l'API key dans la table de config locale |
| `path` | string | Chemin du secret dans le wallet (voir section Path ci-dessous) |

Exemples :
```
${vault://api1:anthropic_api_key}
${vault://api1:shared/slack_webhook}
${vault://prod:databases/postgres_password}
${vault://prod:remote-backups/11111111-2222-3333-4444-555555555555}
```

#### `env://` — Lecture d'une variable d'environnement / `.env`

```
${env://<VAR_NAME>}
```

Lit la valeur de `<VAR_NAME>` depuis l'environnement du process. En pratique
les variables sont chargées depuis un fichier `.env` via `python-dotenv` (ou
équivalent) avant que le loader s'exécute — ce qui rend `env://` et "lire
dans le `.env`" équivalents.

**Rôle principal** : alternative locale à `vault://` pour le développement
et les environnements sans Harpocrate. La même clé de config peut pointer
vers des sources différentes selon le contexte de déploiement :

```
dev  → ${env://ANTHROPIC_API_KEY}         # valeur dans .env local
prod → ${vault://api1:anthropic_api_key}  # valeur dans Harpocrate
```

**Comportement** : fail fast si `<VAR_NAME>` est absente — pas de valeur
par défaut silencieuse.

### Formalisme du `path` dans `vault://`

Le `path` identifie un secret dans un wallet :

```
{segment}/{segment}/{nom_du_secret}
```

| Règle | Détail |
|---|---|
| Séparateur de niveaux | `/` |
| Caractères autorisés par segment | lettres, chiffres, `@`, `.`, `_`, `-` |
| Profondeur maximum | 10 niveaux |
| Segments vides | Interdits (`//` invalide) |
| Navigation relative | Interdite (`.` et `..` invalides) |
| Normalisation | Trim automatique des `/` en début et fin |

Conventions recommandées :

```
shared/{nom_du_secret}              # secrets partagés
{email}/{nom_du_secret}             # secrets personnels par utilisateur
{env}/{nom_du_secret}               # secrets par environnement
{categorie}/{nom_du_secret}         # secrets par catégorie
{env}/{categorie}/{nom_du_secret}   # combiné
```

> ⚠️ L'isolation par path est **organisationnelle, pas cryptographique**.
> Tous les utilisateurs ayant accès au wallet peuvent techniquement lire
> tous les secrets, quel que soit leur path. Pour une isolation
> cryptographique réelle, utiliser des wallets séparés.

### Table de config locale (api_keys)

Associe chaque `api_key_id` à ses credentials Harpocrate. Initialisée au
démarrage depuis les variables d'amorçage :

```bash
# Format : HARPOCRATE_API_TOKEN_{ID} et HARPOCRATE_API_URL_{ID}
HARPOCRATE_API_TOKEN_API1=hrp_1_...
HARPOCRATE_API_URL_API1=https://vault.example.com

HARPOCRATE_API_TOKEN_PROD=hrp_1_...
HARPOCRATE_API_URL_PROD=https://vault.example.com
```

Structure en mémoire :
```python
api_keys = {
    "api1": {"url": "https://vault.example.com", "token": "hrp_1_xxx..."},
    "prod": {"url": "https://vault.example.com", "token": "hrp_1_yyy..."},
}
```

### Implémentation de référence du loader (Python)

```python
import re
import os
from harpocrate import VaultClient

VAULT_PATTERN = re.compile(r'^\$\{vault://([^:]+):([^}]+)\}$')
ENV_PATTERN   = re.compile(r'^\$\{env://([^}]+)\}$')

def build_clients(api_keys: dict) -> dict:
    """Construit les clients Harpocrate depuis la table de config."""
    return {
        identifier: VaultClient(url=cfg["url"], token=cfg["token"])
        for identifier, cfg in api_keys.items()
    }

def resolve(value: str, clients: dict) -> str:
    """Résout une référence déclarative. Retourne la valeur inchangée si
    ce n'est pas une référence."""
    vault_match = VAULT_PATTERN.match(value)
    if vault_match:
        api_key_id, path = vault_match.group(1), vault_match.group(2)
        if api_key_id not in clients:
            raise ValueError(f"Unknown vault api_key_id: '{api_key_id}'")
        return clients[api_key_id].get_secret(path)

    env_match = ENV_PATTERN.match(value)
    if env_match:
        var_name = env_match.group(1)
        v = os.environ.get(var_name)
        if v is None:
            raise ValueError(f"Environment variable not found: '{var_name}'")
        return v

    return value  # valeur littérale

def load_config(raw: dict, api_keys: dict) -> dict:
    """Résout toutes les références dans un dictionnaire de config."""
    clients = build_clients(api_keys)
    return {k: resolve(v, clients) if isinstance(v, str) else v
            for k, v in raw.items()}
```

### Bootstrap des api_keys depuis l'environnement

```python
api_keys = {
    key.removeprefix("HARPOCRATE_API_TOKEN_").lower(): {
        "token": token,
        "url": os.environ[f"HARPOCRATE_API_URL_{key.removeprefix('HARPOCRATE_API_TOKEN_')}"],
    }
    for key, token in os.environ.items()
    if key.startswith("HARPOCRATE_API_TOKEN_")
}
```

### Extensibilité

Le formalisme `${<action>://...}` est ouvert à d'autres actions :

```
${vault://api_key_id:path}    → Harpocrate (implémenté)
${env://VAR_NAME}             → Variable d'env / .env (implémenté)
${file:///path/to/file}       → Fichier local (futur)
${ssm://param_name}           → AWS Parameter Store (futur)
${secret://k8s_secret_name}   → Kubernetes Secret (futur)
```

Pour ajouter une action : nouveau pattern + nouveau handler dans `resolve()`.

### Règles importantes pour l'implémentation

- **Résolution au démarrage uniquement** pour les configs statiques — pas
  de résolution à chaque requête. Pour notre module remote-backups, la
  résolution est à la demande (au moment du push), c'est une exception
  justifiée par le caractère dynamique des credentials.
- **Résultat en RAM** — les valeurs résolues ne sont jamais persistées sur
  disque.
- **Jamais dans les logs** — ne pas loguer les valeurs résolues, uniquement
  les clés.
- **Fail fast** — si une référence ne peut pas être résolue, lever une
  exception au démarrage plutôt que silencieusement retourner `None`.
- **Une API key par identifiant** — ne pas partager une API key entre
  plusieurs `api_key_id`.

Bon courage.
