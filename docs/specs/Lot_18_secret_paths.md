# Lot 18 — Organisation hiérarchique des secrets via paths

> **Prérequis** : Lots 00-17.

## Objectif

Permettre l'organisation des secrets dans une **structure de répertoires virtuels** au sein d'un wallet. Les secrets peuvent être nommés avec des paths type filesystem (`/bob@gmail.com/anthropic_api_key`, `/shared/slack_webhook`), et l'API expose des endpoints de **navigation** (lister les répertoires) et de **filtrage** (lister les secrets d'un répertoire précis, sans descendre dans les sous-répertoires).

Cette organisation est **purement logique** : aucune sémantique de permissions n'est attachée aux paths (les permissions restent au niveau wallet via grants). C'est un outil d'organisation pour faciliter la gestion dans des wallets contenant des centaines de secrets.

## Dépendances

- Lots 00-17

## Périmètre

### Inclus

- Table `secret_path_index` pour indexer efficacement les segments de path
- Trigger automatique de peuplement de l'index lors de INSERT/UPDATE/DELETE sur `secrets`
- Validation des noms de secrets : profondeur max 10 niveaux, caractères autorisés, pas de segments vides
- Endpoint `GET /wallets/{id}/tree` : navigation de répertoires (renvoie les sous-répertoires directs d'un path)
- Endpoint `GET /wallets/{id}/secrets` enrichi : paramètre `?path=` pour filtrer par répertoire (non récursif)
- UI : arborescence avec breadcrumb + navigation par répertoire
- Migration : les secrets existants sans `/` restent à la racine, pas d'impact
- Documentation : convention de nommage, exemples, best practices

### Exclus

- Pas de permissions granulaires par path (reste une feature potentielle future)
- Pas de déplacement en masse (`POST /secrets/bulk-move`)
- Pas de copie de répertoire complet
- Pas de quotas par path (reste au niveau wallet)

## Spécifications fonctionnelles

### Convention de nommage

Les secrets peuvent contenir des `/` dans leur nom pour représenter une hiérarchie :

```
Exemples valides :
  legacy_secret                        (racine, pas de path)
  shared/slack_webhook                 (dans /shared/)
  bob@gmail.com/anthropic_api_key     (dans /bob@gmail.com/)
  prod/databases/postgres_password     (dans /prod/databases/)
```

**Règles** :
- Les segments de path (partie entre deux `/`) doivent matcher `[a-zA-Z0-9@._-]+`
- Profondeur max : 10 niveaux (11 segments si on compte le nom final)
- Pas de segments vides (`//` interdit)
- Pas de `.` ou `..` (pas de navigation relative)
- Le `/` initial est optionnel dans l'écriture mais normalisé en lecture (un secret `bob@gmail.com/key` est stocké et affiché comme `/bob@gmail.com/key`)

### Validation au moment de la création/modification

```python
import re

PATH_SEGMENT_PATTERN = re.compile(r'^[a-zA-Z0-9@._-]+$')
MAX_PATH_DEPTH = 10

def validate_secret_name(name: str) -> None:
    """Valide le nom d'un secret avec path."""
    # Normaliser : ajouter / initial si absent
    if not name.startswith('/') and '/' in name:
        name = '/' + name
    
    # Vérifier segments vides
    if '//' in name:
        raise ValueError("Empty path segments not allowed")
    
    # Split et valider profondeur
    segments = [s for s in name.split('/') if s]  # retire les vides
    if len(segments) > MAX_PATH_DEPTH + 1:  # +1 pour le nom final
        raise ValueError(f"Path too deep (max {MAX_PATH_DEPTH} levels)")
    
    # Valider chaque segment
    for seg in segments:
        if seg in ('.', '..'):
            raise ValueError("Relative path navigation not allowed")
        if not PATH_SEGMENT_PATTERN.match(seg):
            raise ValueError(f"Invalid path segment '{seg}': only alphanumeric, @._- allowed")
    
    return name  # normalisé
```

### Table d'index

```sql
-- migrations/009_secret_path_index.sql

CREATE TABLE secret_path_index (
    secret_id           UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    wallet_id           UUID NOT NULL,  -- dénormalisé pour perf
    path_segment        TEXT NOT NULL,  -- ex: "/bob@gmail.com/", "/bob@gmail.com/subfolder/"
    depth               INTEGER NOT NULL,
    
    PRIMARY KEY (secret_id, depth),
    CONSTRAINT secret_path_index_depth_positive CHECK (depth > 0)
);

CREATE INDEX idx_secret_path_index_lookup 
    ON secret_path_index(wallet_id, path_segment);

CREATE INDEX idx_secret_path_index_depth
    ON secret_path_index(wallet_id, depth);
```

**Peuplement pour un secret nommé `/bob@gmail.com/subfolder/key`** :

| secret_id | wallet_id | path_segment | depth |
|---|---|---|---|
| uuid | wallet-uuid | /bob@gmail.com/ | 1 |
| uuid | wallet-uuid | /bob@gmail.com/subfolder/ | 2 |

Pour un secret à la racine `legacy_secret` (pas de `/`) : **aucune ligne** dans l'index.

### Trigger de peuplement automatique

```sql
CREATE OR REPLACE FUNCTION populate_secret_path_index() 
RETURNS TRIGGER AS $$
DECLARE
    parts TEXT[];
    i INT;
    accum TEXT := '';
    normalized_name TEXT;
BEGIN
    -- Nettoyer l'ancien index
    DELETE FROM secret_path_index WHERE secret_id = NEW.id;
    
    -- Si le nom ne contient pas de /, ne rien indexer (secret racine)
    IF position('/' in NEW.name) = 0 THEN
        RETURN NEW;
    END IF;
    
    -- Normaliser : ajouter / initial si absent
    normalized_name := NEW.name;
    IF NOT starts_with(normalized_name, '/') THEN
        normalized_name := '/' || normalized_name;
    END IF;
    
    -- Split par /
    parts := string_to_array(normalized_name, '/');
    
    -- Construire les path_segments cumulatifs
    -- parts[1] est vide (avant le / initial), donc on commence à parts[2]
    FOR i IN 2..array_length(parts, 1) - 1 LOOP  -- -1 pour exclure le nom final
        accum := accum || '/' || parts[i];
        INSERT INTO secret_path_index (secret_id, wallet_id, path_segment, depth)
        VALUES (NEW.id, NEW.wallet_id, accum || '/', i - 1);
    END LOOP;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_secrets_populate_path_index
    AFTER INSERT OR UPDATE OF name ON secrets
    FOR EACH ROW EXECUTE FUNCTION populate_secret_path_index();
```

**Exemple d'exécution** :

Secret nommé `bob@gmail.com/subfolder/key` (normalisé en `/bob@gmail.com/subfolder/key`) :
- `parts = ['', 'bob@gmail.com', 'subfolder', 'key']`
- Boucle i=2 : `accum = '/bob@gmail.com'`, INSERT (`/bob@gmail.com/`, depth=1)
- Boucle i=3 : `accum = '/bob@gmail.com/subfolder'`, INSERT (`/bob@gmail.com/subfolder/`, depth=2)
- Boucle s'arrête (i=4 serait le nom final `key`, exclu)

### Endpoints

#### `GET /v1/wallets/{wallet_id}/tree`

Navigation de répertoires.

- **Auth** : JWT ou API key
- **Permission** : `read` sur le wallet
- **Query params** :
  - `path` (optionnel, default `/`) : répertoire à explorer
- **Comportement** :
  - Normalise `path` : ajoute `/` final si absent
  - Retourne les **sous-répertoires directs** (depth = depth_du_path + 1)
  - Ne descend jamais récursivement
  - Si `path=/` : retourne les répertoires racine (depth=1)
- **Réponse** :

```json
{
  "path": "/bob@gmail.com/",
  "secrets_at_this_level_count": 2,
  "folders": [
    {
      "name": "subfolder",
      "full_path": "/bob@gmail.com/subfolder/",
      "secrets_count": 3,
      "subfolders_count": 1
    },
    {
      "name": "archives",
      "full_path": "/bob@gmail.com/archives/",
      "secrets_count": 12,
      "subfolders_count": 0
    }
  ]
}
```

Si `path=/` (racine) :

```json
{
  "path": "/",
  "secrets_at_this_level_count": 5,
  "folders": [
    { "name": "bob@gmail.com", "full_path": "/bob@gmail.com/", ... },
    { "name": "alice@example.com", "full_path": "/alice@example.com/", ... },
    { "name": "shared", "full_path": "/shared/", ... }
  ]
}
```

**Requête SQL** :

```sql
-- Pour path="/bob@gmail.com/" (depth=1), on cherche les répertoires de depth=2

WITH target_depth AS (
    SELECT CASE 
        WHEN $2 = '/' THEN 1
        ELSE (length($2) - length(replace($2, '/', '')))
    END AS depth
)
SELECT 
    substring(path_segment from length($2) + 1 for position('/' in substring(path_segment from length($2) + 1)) - 1) AS name,
    path_segment AS full_path,
    COUNT(DISTINCT secret_id) AS secrets_count,
    COUNT(DISTINCT CASE WHEN pi2.depth > (SELECT depth FROM target_depth) + 1 THEN pi2.secret_id END) AS subfolders_count
FROM secret_path_index pi
LEFT JOIN secret_path_index pi2 ON pi2.secret_id = pi.secret_id
WHERE pi.wallet_id = $1
  AND pi.depth = (SELECT depth FROM target_depth) + 1
  AND pi.path_segment LIKE $2 || '%'
  AND pi.path_segment != $2
GROUP BY pi.path_segment
ORDER BY name;
```

Comptage des secrets au niveau demandé :

```sql
-- Secrets qui ont exactement ce path comme dernier niveau
SELECT COUNT(*) FROM secrets s
WHERE s.wallet_id = $1
  AND (
      ($2 = '/' AND s.name NOT LIKE '%/%')  -- racine
      OR
      (s.name LIKE $2 || '%' AND s.name NOT LIKE $2 || '%/%')  -- path non-racine
  );
```

#### `GET /v1/wallets/{wallet_id}/secrets` (enrichi)

Liste des secrets avec filtrage par path.

- **Auth** : JWT ou API key
- **Permission** : `read` sur le wallet
- **Query params** (existants + nouveau) :
  - `path` (optionnel, default racine) : répertoire à filtrer
  - `q` (existant) : recherche textuelle
  - `tags` (existant) : filtrage par tags
  - `limit`, `cursor` (existant) : pagination
- **Comportement** :
  - Normalise `path` : ajoute `/` final si absent
  - Retourne **uniquement les secrets directs** du path (pas les sous-répertoires)
  - Si `path` vide ou absent : secrets racine (ceux sans `/`)
  - Si `path=/bob@gmail.com/` : secrets dont le nom est `/bob@gmail.com/{nom}` (pas `/bob@gmail.com/subfolder/{nom}`)
- **Réponse** : standard (structure existante des lots précédents)

**Requête SQL** :

```sql
-- Cas racine (path vide ou "/")
SELECT s.* FROM secrets s
WHERE s.wallet_id = $1
  AND s.name NOT LIKE '%/%'
ORDER BY s.name
LIMIT $limit OFFSET $offset;

-- Cas path non-racine ("/bob@gmail.com/")
SELECT s.* FROM secrets s
WHERE s.wallet_id = $1
  AND s.name LIKE $path || '%'
  AND s.name NOT LIKE $path || '%/%'  -- exclut les sous-répertoires
ORDER BY s.name
LIMIT $limit OFFSET $offset;
```

Optimisation via index (éviter le LIKE sur gros volumes) :

```sql
-- Utiliser secret_path_index pour filtrer puis joindre
WITH secrets_in_path AS (
    SELECT DISTINCT pi.secret_id
    FROM secret_path_index pi
    WHERE pi.wallet_id = $1
      AND pi.path_segment = $path
      AND pi.depth = (length($path) - length(replace($path, '/', '')))
      AND NOT EXISTS (
          SELECT 1 FROM secret_path_index pi2
          WHERE pi2.secret_id = pi.secret_id
            AND pi2.depth > pi.depth
      )
)
SELECT s.* FROM secrets s
JOIN secrets_in_path sip ON sip.secret_id = s.id
ORDER BY s.name
LIMIT $limit OFFSET $offset;
```

### Renommage et déplacement

Un secret peut être déplacé via `PATCH /secrets/{id}` avec `{ "name": "nouveau/path/nom" }`. Le trigger met automatiquement à jour l'index.

**Workflow UI** :

```
Secret: /bob@gmail.com/old_key

[Rename]

New name: /bob@gmail.com/archives/old_key

[Save]
```

→ `PATCH /secrets/{id}` avec `{ "name": "/bob@gmail.com/archives/old_key" }`

Le trigger supprime les anciennes entrées dans `secret_path_index` et crée les nouvelles. Transparent pour l'utilisateur.

### UI

#### Page `/wallets/{id}` avec navigation

```
Wallet: ag-flow-prod
═══════════════════════════════════════════════════════════

Path: / bob@gmail.com / subfolder /

📁 Folders (2)
  📁 archives          (12 secrets)
  📁 keys              (3 secrets)

🔑 Secrets in this folder (2)
  🔑 anthropic_api_key     Updated 2d ago
  🔑 github_token          Updated 5d ago

[+ New secret in this folder]
[⬆ Up to /bob@gmail.com/]
```

Clic sur `📁 archives` → navigue vers `/bob@gmail.com/subfolder/archives/`.

Clic sur breadcrumb `bob@gmail.com` → navigue vers `/bob@gmail.com/`.

#### Modale "New secret" avec path pré-rempli

```
New secret in /bob@gmail.com/subfolder/

Name: [anthropic_api_key_v2________________]

Full path will be: /bob@gmail.com/subfolder/anthropic_api_key_v2

...
```

Le path courant est pré-rempli, l'user saisit juste le nom final. Si il veut créer dans un sous-dossier, il peut écrire `archives/key` et le nom final sera `/bob@gmail.com/subfolder/archives/key`.

#### Vue racine (secrets sans path)

```
Path: /

📁 Folders (3)
  📁 bob@gmail.com     (8 secrets)
  📁 alice@example.com (5 secrets)
  📁 shared            (12 secrets)

🔑 Secrets at root (5)
  🔑 legacy_secret_1
  🔑 old_api_key
  ...

[+ New secret at root]
```

## Spécifications techniques

### Service backend

```python
# app/services/secrets.py (extrait des modifications)

from typing import Optional

async def list_secrets_by_path(
    conn: asyncpg.Connection,
    wallet_id: UUID,
    path: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> dict:
    """Liste les secrets d'un path spécifique (non récursif)."""
    
    # Normaliser path
    if not path or path == '/':
        # Secrets racine (sans /)
        query = """
            SELECT * FROM secrets
            WHERE wallet_id = $1
              AND name NOT LIKE '%/%'
            ORDER BY name
            LIMIT $2
        """
        params = [wallet_id, limit]
    else:
        # Normaliser : ajouter / final si absent
        if not path.endswith('/'):
            path = path + '/'
        
        # Secrets directs du path (pas les sous-répertoires)
        query = """
            SELECT * FROM secrets
            WHERE wallet_id = $1
              AND name LIKE $2 || '%'
              AND name NOT LIKE $2 || '%/%'
            ORDER BY name
            LIMIT $3
        """
        params = [wallet_id, path, limit]
    
    rows = await conn.fetch(query, *params)
    return {"secrets": [dict(r) for r in rows]}


async def get_wallet_tree(
    conn: asyncpg.Connection,
    wallet_id: UUID,
    path: str = '/',
) -> dict:
    """Retourne l'arborescence d'un path."""
    
    # Normaliser
    if not path.endswith('/'):
        path = path + '/'
    
    # Calculer depth cible
    if path == '/':
        target_depth = 1
    else:
        target_depth = path.count('/')
    
    # Récupérer les sous-répertoires
    query = """
        WITH folder_stats AS (
            SELECT 
                pi.path_segment,
                COUNT(DISTINCT pi.secret_id) AS secrets_count,
                COUNT(DISTINCT CASE WHEN pi2.depth > $3 THEN pi2.secret_id END) AS subfolders_count
            FROM secret_path_index pi
            LEFT JOIN secret_path_index pi2 ON pi2.secret_id = pi.secret_id
            WHERE pi.wallet_id = $1
              AND pi.depth = $3
              AND pi.path_segment LIKE $2 || '%'
              AND pi.path_segment != $2
            GROUP BY pi.path_segment
        )
        SELECT 
            substring(path_segment from length($2) + 1 for position('/' in substring(path_segment from length($2) + 1)) - 1) AS name,
            path_segment AS full_path,
            secrets_count,
            subfolders_count
        FROM folder_stats
        ORDER BY name
    """
    
    folders = await conn.fetch(query, wallet_id, path, target_depth)
    
    # Compter les secrets au niveau courant
    if path == '/':
        secrets_count = await conn.fetchval(
            "SELECT COUNT(*) FROM secrets WHERE wallet_id = $1 AND name NOT LIKE '%/%'",
            wallet_id,
        )
    else:
        secrets_count = await conn.fetchval(
            """SELECT COUNT(*) FROM secrets 
               WHERE wallet_id = $1 
                 AND name LIKE $2 || '%' 
                 AND name NOT LIKE $2 || '%/%'""",
            wallet_id, path,
        )
    
    return {
        "path": path,
        "secrets_at_this_level_count": secrets_count,
        "folders": [
            {
                "name": f["name"],
                "full_path": f["full_path"],
                "secrets_count": f["secrets_count"],
                "subfolders_count": f["subfolders_count"],
            }
            for f in folders
        ],
    }
```

### Endpoints FastAPI

```python
# app/api/v1/wallets.py

@router.get("/{wallet_id}/tree")
async def get_wallet_tree_endpoint(
    wallet_id: UUID,
    path: str = Query(default="/", description="Path to explore"),
    pool: asyncpg.Pool = Depends(get_pool),
    actor: Actor = Depends(require_read_permission(wallet_id)),
):
    async with pool.acquire() as conn:
        result = await get_wallet_tree(conn, wallet_id, path)
    return result


@router.get("/{wallet_id}/secrets")
async def list_secrets_endpoint(
    wallet_id: UUID,
    path: Optional[str] = Query(default=None, description="Filter by path"),
    q: Optional[str] = None,
    tags: Optional[list[str]] = Query(default=None),
    limit: int = Query(default=50, le=100),
    cursor: Optional[str] = None,
    pool: asyncpg.Pool = Depends(get_pool),
    actor: Actor = Depends(require_read_permission(wallet_id)),
):
    async with pool.acquire() as conn:
        result = await list_secrets_by_path(conn, wallet_id, path, limit, cursor)
        # Combiner avec filtres existants (q, tags) si nécessaire
    return result
```

### SDK Python (modifications)

Le SDK Python (lot 09) doit être mis à jour pour supporter les paths.

#### Méthode `get_tree()`

```python
# harpocrate_sdk/client.py

class VaultClient:
    # ... méthodes existantes ...
    
    def get_tree(self, wallet_name: str, path: str = "/") -> dict:
        """
        Retourne l'arborescence d'un wallet à un path donné.
        
        Args:
            wallet_name: Nom du wallet
            path: Path à explorer (default: "/")
        
        Returns:
            {
                "path": "/bob@gmail.com/",
                "secrets_at_this_level_count": 2,
                "folders": [
                    {"name": "subfolder", "full_path": "/bob@gmail.com/subfolder/", ...}
                ]
            }
        """
        wallet_id = self._resolve_wallet_id(wallet_name)
        resp = self._request("GET", f"/v1/wallets/{wallet_id}/tree", params={"path": path})
        return resp.json()
```

#### Paramètre `path` dans `list_secrets()`

```python
def list_secrets(
    self, 
    wallet_name: str, 
    path: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50
) -> list[dict]:
    """
    Liste les secrets d'un wallet, optionnellement filtrés par path.
    
    Args:
        wallet_name: Nom du wallet
        path: Filtre par path (ex: "/bob@gmail.com/"). Si None, liste tout.
        tags: Filtre par tags (existant)
        limit: Nombre max de résultats
    
    Returns:
        Liste de secrets avec leurs métadonnées (encrypted_value, tags, etc.)
    
    Note:
        Le path filtre de manière NON-RÉCURSIVE : seuls les secrets directs
        du path sont retournés (pas les sous-répertoires).
    """
    wallet_id = self._resolve_wallet_id(wallet_name)
    params = {"limit": limit}
    if path is not None:
        params["path"] = path
    if tags:
        params["tags"] = tags
    
    resp = self._request("GET", f"/v1/wallets/{wallet_id}/secrets", params=params)
    return resp.json()["secrets"]
```

#### Méthode `get_secret()` avec path dans le nom

Pas de changement nécessaire — la méthode accepte déjà `secret_name` comme string, qui peut contenir des `/` :

```python
# Existant, fonctionne déjà avec paths
client.get_secret(
    wallet_name="ag-flow-prod",
    secret_name="/bob@gmail.com/anthropic_api_key"
)
```

Le SDK normalise automatiquement en ajoutant le `/` initial si absent :

```python
def get_secret(self, wallet_name: str, secret_name: str) -> str:
    """Récupère et déchiffre un secret."""
    # Normalisation du nom
    if '/' in secret_name and not secret_name.startswith('/'):
        secret_name = '/' + secret_name
    
    wallet_id = self._resolve_wallet_id(wallet_name)
    # ... suite existante
```

#### Exemples d'usage avec paths

```python
from harpocrate import VaultClient

client = VaultClient.from_env()

# Navigation de l'arborescence
tree = client.get_tree("ag-flow-prod", path="/")
print("Dossiers racine :", [f["name"] for f in tree["folders"]])

tree_bob = client.get_tree("ag-flow-prod", path="/bob@gmail.com/")
print("Sous-dossiers de Bob :", [f["name"] for f in tree_bob["folders"]])

# Liste des secrets d'un path
secrets_bob = client.list_secrets("ag-flow-prod", path="/bob@gmail.com/")
print("Secrets de Bob :", [s["name"] for s in secrets_bob])

# Récupération d'un secret avec path
anthropic_key = client.get_secret(
    wallet_name="ag-flow-prod",
    secret_name="/bob@gmail.com/anthropic_api_key"
)
```

#### Tests SDK à ajouter

```python
# tests/test_sdk_paths.py

def test_get_tree_root(client, mock_wallet):
    tree = client.get_tree("test-wallet", path="/")
    assert tree["path"] == "/"
    assert "folders" in tree

def test_get_tree_subfolder(client, mock_wallet):
    tree = client.get_tree("test-wallet", path="/bob@gmail.com/")
    assert tree["path"] == "/bob@gmail.com/"

def test_list_secrets_with_path_filter(client, mock_wallet):
    secrets = client.list_secrets("test-wallet", path="/bob@gmail.com/")
    # Vérifier que seuls les secrets directs sont retournés
    assert all("/bob@gmail.com/" in s["name"] for s in secrets)
    assert not any(s["name"].count("/") > 2 for s in secrets)  # pas de sous-dossiers

def test_get_secret_with_path_normalizes(client, mock_wallet):
    # Sans / initial
    secret = client.get_secret("test-wallet", "bob@gmail.com/key")
    # Le SDK doit normaliser en /bob@gmail.com/key
    # Vérifier via mock que la requête HTTP a bien envoyé le nom normalisé
```

#### Distribution PyPI (sdist)

```bash
# pyproject.toml (extrait)
[project]
name = "harpocrate-sdk"
version = "0.2.0"  # bump pour ajout get_tree() et path support
description = "SDK Python pour Harpocrate avec support des paths hiérarchiques"
```

Build et publication :

```bash
python -m build --sdist
twine upload dist/harpocrate-sdk-0.2.0.tar.gz
```

**Note** : Les SDKs npm (`@harpocrate/sdk`) et CLI Bash (`harpocrate`) seront mis à jour dans des lots futurs. Le lot 18 se concentre sur le SDK Python uniquement.

### Frontend

```typescript
// frontend/src/routes/wallets/WalletDetail.tsx

function WalletDetail({ walletId }: Props) {
  const [currentPath, setCurrentPath] = useState('/');
  
  const { data: tree } = useQuery(
    ['wallet', walletId, 'tree', currentPath],
    () => api.get(`/v1/wallets/${walletId}/tree`, { params: { path: currentPath } })
  );
  
  const { data: secrets } = useQuery(
    ['wallet', walletId, 'secrets', currentPath],
    () => api.get(`/v1/wallets/${walletId}/secrets`, { params: { path: currentPath } })
  );
  
  return (
    <Stack>
      <Breadcrumb path={currentPath} onNavigate={setCurrentPath} />
      
      <FoldersSection 
        folders={tree?.folders} 
        onNavigate={(folder) => setCurrentPath(folder.full_path)} 
      />
      
      <SecretsSection 
        secrets={secrets?.secrets}
        currentPath={currentPath}
      />
      
      <Button onClick={() => openCreateSecretModal(currentPath)}>
        + New secret in this folder
      </Button>
    </Stack>
  );
}
```

## Critères de succès

1. ✅ Migration applique : table `secret_path_index` créée, trigger actif
2. ✅ Validation des noms rejette caractères interdits, profondeur > 10, segments vides
3. ✅ Trigger peuple correctement l'index pour un secret multi-niveaux
4. ✅ Trigger ne crée aucune ligne pour un secret racine (sans `/`)
5. ✅ `GET /tree?path=/` retourne les répertoires racine
6. ✅ `GET /tree?path=/bob@gmail.com/` retourne les sous-répertoires directs uniquement
7. ✅ `GET /secrets?path=` (vide) retourne les secrets racine
8. ✅ `GET /secrets?path=/bob@gmail.com/` retourne les secrets directs, pas les sous-répertoires
9. ✅ `secrets_count` et `subfolders_count` corrects dans `/tree`
10. ✅ Normalisation automatique : `path=bob@gmail.com` → `path=/bob@gmail.com/`
11. ✅ Renommage d'un secret met à jour l'index automatiquement
12. ✅ Suppression d'un secret nettoie l'index (CASCADE)
13. ✅ UI breadcrumb fonctionne
14. ✅ UI navigation par dossiers fonctionne
15. ✅ UI création de secret avec path pré-rempli
16. ✅ Pagination fonctionne avec path (cursor)
17. ✅ Audit log enregistre les accès filtrés par path (metadata `path`)
18. ✅ SDK Python : méthode `get_tree()` fonctionne
19. ✅ SDK Python : paramètre `path=` dans `list_secrets()` filtre correctement
20. ✅ SDK Python : `get_secret()` normalise automatiquement les noms avec path
21. ✅ SDK Python : tests avec paths passent
22. ✅ SDK Python : package sdist `harpocrate-sdk` 0.2.0 publié sur PyPI

## Pièges connus

- **Performance avec profondeur** : un secret à 10 niveaux crée 10 lignes dans l'index. Pour 10 000 secrets moyens à 3 niveaux → 30 000 lignes d'index. Acceptable, mais monitorer la taille de la table.
- **Trigger sur UPDATE de `name`** : si on renomme 1000 secrets en masse (script de réorganisation), le trigger se déclenche 1000 fois. Pas de batch update optimisé. Acceptable car rare.
- **LIKE avec %** : la requête `name LIKE '/bob@gmail.com/%'` est index-friendly si Postgres détecte le pattern prefix. Tester le plan d'exécution. Si lent, revenir à la jointure via `secret_path_index`.
- **Normalisation du path** : critique. Si l'UI envoie `bob@gmail.com` sans `/` initial, le backend doit normaliser. Sinon les requêtes ne matchent rien.
- **Secrets racine et `/`** : un secret nommé exactement `/` (juste un slash) est-il valide ? Non — la validation rejette (segment vide). Documenter.
- **Breadcrumb UI sur mobile** : si le path est `/bob@gmail.com/subfolder/archives/2023/q4/`, le breadcrumb devient illisible. Tronquer ou scroll horizontal.
- **Comptage `secrets_at_this_level_count` vs `secrets_count` dans folders** : attention à ne pas confondre. `secrets_at_this_level_count` = secrets directs du path demandé. `folder.secrets_count` = secrets directs du folder (pas récursif non plus). Bien les distinguer dans l'UI.
- **Migration des secrets existants** : ne rien faire. Les secrets sans `/` restent racine, accessibles via `?path=` (vide). Si l'admin veut les organiser, il les renomme manuellement ou via script.
- **API key scopée à un wallet avec path** : une API key donne accès au wallet entier. Pour restreindre par path, il faudrait des permissions granulaires (hors scope lot 18). L'agent qui consomme peut filter `?path=` mais rien n'empêche techniquement de lire un autre path.

## Tests

### Backend

- `test_validate_secret_name_accepts_valid_paths`
- `test_validate_secret_name_rejects_invalid_chars`
- `test_validate_secret_name_rejects_too_deep`
- `test_validate_secret_name_rejects_empty_segments`
- `test_validate_secret_name_normalizes_path`
- `test_trigger_populates_index_for_multilevel_secret`
- `test_trigger_does_not_populate_index_for_root_secret`
- `test_trigger_updates_index_on_rename`
- `test_trigger_cleans_index_on_delete`
- `test_get_tree_root_returns_top_folders`
- `test_get_tree_subfolder_returns_direct_children_only`
- `test_get_tree_counts_are_correct`
- `test_list_secrets_by_path_root_excludes_paths`
- `test_list_secrets_by_path_folder_excludes_subfolders`
- `test_list_secrets_by_path_normalizes_trailing_slash`
- `test_pagination_with_path_filter`

### SDK Python

- `test_get_tree_root`
- `test_get_tree_subfolder`
- `test_list_secrets_with_path_filter`
- `test_list_secrets_without_path_returns_all`
- `test_get_secret_with_path_normalizes`
- `test_get_secret_with_path_without_leading_slash`
- `test_create_secret_with_path`

### Frontend

- `test_breadcrumb_renders_path_segments`
- `test_breadcrumb_click_navigates_to_parent`
- `test_folders_list_navigates_on_click`
- `test_secrets_list_filtered_by_current_path`
- `test_new_secret_modal_prefills_path`
- `test_rename_secret_updates_path_in_ui`

## Ce qui suit

Avec ce lot, l'organisation des secrets est complète. Les prochaines étapes possibles :

- **Lot 19** (optionnel) : Permissions granulaires par path (table `secret_path_grants`)
- **Lot 20** (optionnel) : Catalogue de types prédéfinis (seed aws/credentials, gcp/sa, ssh/keypair, etc.)
- **Documentation utilisateur multilingue** (les 16 fichiers `docs/{fr,en}/` identifiés en phase 2)

Ou bien retour à ag.flow pour intégrer la consommation Harpocrate dans le module role avec les paths personnels par user.