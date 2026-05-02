# Lot 07 — Export / Import structure de wallet

> **Prérequis** : Lots 00-06.

## Objectif

Permettre la **promotion entre environnements** : exporter la structure d'un wallet (noms, tags, descripteurs de génération — sans valeurs) en JSON, puis l'importer sur une autre instance ou comme nouveau wallet.

## Dépendances

- Lots 00-06

## Périmètre

### Inclus

- Endpoint `GET /v1/wallets/{id}/export`
- Endpoint `POST /v1/wallets/import`
- Format JSON versionné (`format_version: "1"`)
- Validation stricte à l'import (schéma, noms uniques, descripteurs valides)
- Création atomique (transaction) du wallet + grants owner + secrets en placeholder
- Audit log : `wallet.exported_structure`, `wallet.imported`

### Exclus

- Pas d'API key autorisée (humain seulement)
- Pas de "auto-generate" à l'import (ce sera du ressort du SDK au lot 09)
- Pas de promotion automatisée multi-instance (roadmap)
- Pas de diff entre wallets (roadmap)

## Spécifications fonctionnelles

### Format JSON d'échange

```json
{
  "format_version": "1",
  "exported_at": "2026-05-01T14:23:00Z",
  "exported_from": "vault.dev.yoops.org",
  "wallet": {
    "name": "ag.flow Production",
    "description": "...",
    "tags": ["agflow", "prod"]
  },
  "secrets": [
    {
      "name": "ANTHROPIC_API_KEY",
      "description": "Clé Anthropic principale",
      "tags": ["llm", "anthropic"],
      "generation_descriptor": {
        "type": "random",
        "length": 64,
        "charset": "alphanum"
      },
      "linked_secret_name": null
    },
    {
      "name": "DATABASE_URL",
      "tags": ["db"],
      "generation_descriptor": {
        "type": "template",
        "template": "postgresql://{user}:{password}@{host}:5432/{db}",
        "variables": {
          "user": { "literal": "agflow" },
          "password": { "type": "random", "length": 32, "charset": "alphanum" },
          "host": { "literal": "postgres.home.lan" },
          "db": { "literal": "agflow" }
        }
      }
    }
  ]
}
```

**Notes** :
- **Pas de valeurs** (jamais)
- **Pas d'IDs** UUID source (le wallet importé est un nouvel objet)
- **`linked_secret_name`** au lieu de `linked_secret_id` : le lien est résolu par nom à l'import
- **`exported_from`** : informatif, pas de contrôle

### `GET /v1/wallets/{id}/export`

- **Auth** : JWT, permission `[read]`
- **Réponse** : `200`, `Content-Type: application/json`, `Content-Disposition: attachment; filename="vault-{wallet_name}-{date}.json"`
- **Body** : le JSON ci-dessus

### `POST /v1/wallets/import`

- **Auth** : JWT (utilisateur authentifié peut importer comme nouveau wallet)
- **Body** :
```json
{
  "format_version": "1",
  "wallet": { "name": "...", "description": "...", "tags": [...] },
  "secrets": [...],
  "encrypted_wallet_key_for_owner": "<base64>"
}
```
- **Validations** :
  - `format_version == "1"`
  - Tous les `secrets[*].name` uniques dans la liste
  - Chaque `generation_descriptor` valide (mêmes règles que lot 06)
  - Chaque `linked_secret_name` réfère à un autre secret de la liste
  - Tags normalisés
  - `encrypted_wallet_key_for_owner` non vide
- **Effets** : transaction atomique
  - INSERT wallets (owner = caller)
  - INSERT wallet_grants owner
  - INSERT wallet_tags
  - INSERT secrets pour chacun (en placeholder, descripteur stocké, linked_secret_id résolu post-insertion)
- **Réponse** : `201`
```json
{
  "wallet_id": "uuid",
  "secrets_created": 3,
  "skipped": []
}
```

## Spécifications techniques

### Schéma Pydantic du format d'export

```python
# app/models/api/export.py

class ExportedSecret(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] = []
    generation_descriptor: GenerationDescriptor | None = None
    linked_secret_name: str | None = None

class ExportedWallet(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] = []

class WalletExport(BaseModel):
    format_version: Literal["1"]
    exported_at: datetime | None = None
    exported_from: str | None = None
    wallet: ExportedWallet
    secrets: list[ExportedSecret]

    @model_validator(mode="after")
    def validate_unique_names(self):
        names = [s.name for s in self.secrets]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate secret names")
        return self

    @model_validator(mode="after")
    def validate_linked_names(self):
        names = {s.name for s in self.secrets}
        for s in self.secrets:
            if s.linked_secret_name and s.linked_secret_name not in names:
                raise ValueError(
                    f"linked_secret_name '{s.linked_secret_name}' not in import list"
                )
        return self
```

### Création atomique en deux passes

À l'import, on a deux passes pour gérer `linked_secret_name` :

```python
async with conn.transaction():
    # Wallet + grant owner
    wallet_id = await ...

    # Pass 1 : INSERT tous les secrets sans linked_secret_id
    name_to_id: dict[str, UUID] = {}
    for s in body.secrets:
        secret_id = await conn.fetchval(
            """INSERT INTO secrets (
                wallet_id, name, description,
                is_placeholder, generation_descriptor,
                created_by_user_id
            ) VALUES ($1, $2, $3, TRUE, $4::jsonb, $5)
            RETURNING id""",
            wallet_id, s.name, s.description,
            json.dumps(s.generation_descriptor.model_dump()) if s.generation_descriptor else None,
            user.id,
        )
        name_to_id[s.name] = secret_id

    # Pass 2 : UPDATE linked_secret_id
    for s in body.secrets:
        if s.linked_secret_name:
            await conn.execute(
                "UPDATE secrets SET linked_secret_id = $1 WHERE id = $2",
                name_to_id[s.linked_secret_name],
                name_to_id[s.name],
            )

    # Tags
    for tag in body.wallet.tags:
        await conn.execute(
            "INSERT INTO wallet_tags (wallet_id, tag) VALUES ($1, $2)",
            wallet_id, tag.lower().strip(),
        )
    for s in body.secrets:
        for tag in s.tags:
            await conn.execute(
                "INSERT INTO secret_tags (secret_id, tag) VALUES ($1, $2)",
                name_to_id[s.name], tag.lower().strip(),
            )
```

### Export

```python
# Récupérer le wallet, les tags, les secrets avec leurs tags et descripteurs
async with pool.acquire() as conn:
    wallet = await conn.fetchrow("SELECT * FROM wallets WHERE id = $1", wallet_id)
    wallet_tags = [r["tag"] for r in await conn.fetch(
        "SELECT tag FROM wallet_tags WHERE wallet_id = $1", wallet_id
    )]
    secrets = await conn.fetch(
        """SELECT s.*,
              array_agg(st.tag) FILTER (WHERE st.tag IS NOT NULL) as tags,
              ls.name as linked_secret_name
           FROM secrets s
           LEFT JOIN secret_tags st ON st.secret_id = s.id
           LEFT JOIN secrets ls ON ls.id = s.linked_secret_id
          WHERE s.wallet_id = $1
       GROUP BY s.id, ls.name""",
        wallet_id,
    )

# Composer le JSON et renvoyer
```

## Critères de succès

1. ✅ Export d'un wallet avec 3 secrets dont 1 lié → JSON correct, sans valeurs, avec `linked_secret_name`
2. ✅ Import du même JSON sur la même instance → nouveau wallet créé, mêmes secrets en placeholder
3. ✅ Import avec `format_version="2"` → 400
4. ✅ Import avec doublons de noms → 422
5. ✅ Import avec `linked_secret_name` invalide → 422
6. ✅ Import atomique : si une insertion échoue, rollback complet (vérifier avec test injectant un descripteur invalide)
7. ✅ Permission `[read]` requise pour export
8. ✅ Filename de download contient le nom du wallet et la date
9. ✅ Audit log `wallet.exported_structure` avec metadata `{secret_count: N}`
10. ✅ Audit log `wallet.imported` avec metadata `{source_wallet_name, secret_count}`

## Pièges connus

- **`format_version`** strict en `"1"` (string, pas int) : permet les schémas futurs `"2"`, `"1.1"`, etc.
- **Tags normalisés à l'import** : appliquer lowercase + trim côté serveur, ne pas faire confiance à l'export.
- **Descripteurs validés à l'import** : utiliser le même `GenerationDescriptor` discriminated union du lot 06.
- **`linked_secret_name`** : résolu par nom à l'import. Si le nom est ambigu (ne devrait pas, on a UNIQUE constraint), l'unicité dans la liste est validée d'abord.
- **`encrypted_wallet_key_for_owner`** doit être fourni par le client : il a généré une nouvelle wallet_key et l'a chiffrée avec sa propre RSA pub.
- **Aucune valeur dans le JSON exporté** : tester explicitement qu'aucun champ `encrypted_value` n'apparaît dans la sortie.
- **`exported_from`** : utiliser `settings.public_url` ou un domaine configurable, pas de hardcode.
- **Compatibilité ascendante** : tout futur changement de schéma export doit incrémenter `format_version` et garder le parser de v1 intact pour l'import.
- **Taille du JSON** : un wallet avec 1000 secrets fait potentiellement 1 MB de JSON. OK pour FastAPI mais à garder en tête.

## Exemple

```bash
# Export
curl -X GET .../v1/wallets/$WALLET_ID/export -H "Authorization: Bearer $JWT" \
  -o exported.json

# Import sur une autre instance
curl -X POST .../v1/wallets/import \
  -H "Authorization: Bearer $JWT_OTHER_INSTANCE" \
  -H "Content-Type: application/json" \
  -d @<(jq '. + {encrypted_wallet_key_for_owner: "..."}' exported.json)
```

## Tests à écrire

- `test_export_returns_json_no_values`
- `test_export_includes_descriptors_and_tags`
- `test_export_filename_attachment`
- `test_import_happy_path`
- `test_import_creates_placeholders`
- `test_import_validates_format_version`
- `test_import_rejects_duplicate_names`
- `test_import_resolves_linked_secret_name`
- `test_import_atomic_rollback_on_error`
- `test_round_trip_export_import_preserves_structure`

## Ce qui suit

Le **lot 08** introduit les API keys, l'élément le plus dense en logique sécurité.
