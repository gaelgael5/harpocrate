# Lot 17 — Secrets typés et rendu RJSF

> **Prérequis** : Lots 00-16.

## Objectif

Brancher les types et schemas du lot 15 sur la **création, lecture et édition des secrets**. Rendu dynamique du formulaire via **React JSON Schema Form (RJSF)**. Validation côté client avant chiffrement (le serveur reste E2E, ne voit jamais le contenu déchiffré).

Possibilité de **migrer un secret vers une version plus récente** du schema, à l'initiative de l'utilisateur.

## Dépendances

- Lots 00-16

## Périmètre

### Inclus

- Trigger DB : `secrets.schema_version_uuid.parent_uuid` doit matcher `secrets.type_uuid` (cohérence)
- API : `POST /secrets` accepte `type_uuid` optionnel
- API : `PATCH /secrets/{name}/migrate-schema` pour migrer vers la version courante
- API : `GET /secrets/{name}` enrichit la réponse avec le type et le schema utilisés
- Frontend :
  - Sélecteur de type au moment de la création d'un secret
  - Rendu RJSF dynamique en lecture / édition
  - Validation côté client AVANT chiffrement (refus de sauvegarder si invalide)
  - Bouton "Migrer vers vN" si une version plus récente existe
  - Fallback textarea pour secrets sans type (legacy / type=text/plain)
- Conservation rétrocompatible : secrets sans `type_uuid` continuent à fonctionner comme avant

### Exclus

- Pas de migration auto en masse
- Pas de validation des valeurs côté serveur (impossible E2E)
- Pas de seed de types prédéfinis
- Pas de génération auto de la valeur depuis un descriptor RJSF (ça reste les générateurs lot 06)

## Spécifications fonctionnelles

### Migration DB

```sql
-- migrations/008_secrets_typed_consistency.sql

-- Trigger : si type_uuid renseigné, schema_version_uuid doit avoir parent_uuid = type_uuid
CREATE OR REPLACE FUNCTION enforce_secret_schema_belongs_to_type()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.type_uuid IS NOT NULL AND NEW.schema_version_uuid IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM secret_schemas
            WHERE version_uuid = NEW.schema_version_uuid
              AND parent_uuid = NEW.type_uuid
        ) THEN
            RAISE EXCEPTION
                'secrets.schema_version_uuid must reference a schema with parent_uuid = secrets.type_uuid'
                USING ERRCODE = '23000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_secrets_type_schema_consistency
    BEFORE INSERT OR UPDATE OF type_uuid, schema_version_uuid ON secrets
    FOR EACH ROW EXECUTE FUNCTION enforce_secret_schema_belongs_to_type();
```

La cohérence (les deux NULL ou les deux NOT NULL) est déjà contrainte par le CHECK ajouté au lot 15. Ce trigger ajoute la cohérence sémantique : le schema doit appartenir au type indiqué.

### API

#### `POST /v1/wallets/{wallet_id}/secrets` (modifié)

- **Auth** : JWT ou API key
- **Body** :
```json
{
  "name": "aws-prod-credentials",
  "description": "Production AWS for ag-flow",
  "encrypted_value": "<base64 chiffré>",
  "tags": ["aws", "prod"],
  "type_uuid": "uuid-of-aws-credentials-type",
  "schema_version_uuid": "uuid-of-v2-schema"
}
```
- **Validations serveur** :
  - Si `type_uuid` fourni : `schema_version_uuid` doit l'être aussi (CHECK DB) et appartenir au type (trigger DB)
  - Si `schema_version_uuid` non fourni explicitement mais `type_uuid` oui : le serveur peut auto-résoudre via `current_version_uuid` du type. À discuter — au MVP on demande au client de l'envoyer explicitement pour éviter la magie. Le SDK JavaScript le résout côté client.
- **Effets** : INSERT avec les colonnes typées
- **Audit** : `secret.created` avec `metadata.type_uuid` si présent
- **Réponse** : standard

#### `GET /v1/wallets/{wallet_id}/secrets/{name}` (enrichi)

- **Auth** : JWT ou API key
- **Réponse** (champs ajoutés) :
```json
{
  "id": "...",
  "name": "...",
  "encrypted_value": "...",
  "tags": [...],
  "is_placeholder": false,
  "type": {
    "type_uuid": "...",
    "type": "aws",
    "sous_type": "credentials",
    "label": "AWS Credentials",
    "current_version_uuid": "uuid-of-v3"
  },
  "schema_version": {
    "version_uuid": "uuid-of-v2",
    "version": 2,
    "schema_data": { ... },
    "schema_ui": { ... },
    "is_current": false,
    "current_version_uuid": "uuid-of-v3"
  },
  "..."
}
```

Si `type_uuid IS NULL` : `type` et `schema_version` retournent `null`.

`schema_version.is_current = false` indique que le secret pointe vers une version dépassée → l'UI peut afficher le bouton "Migrer".

#### `PATCH /v1/wallets/{wallet_id}/secrets/{name}/migrate-schema`

- **Auth** : JWT (pas API key — décision E2E : seul un humain peut valider la nouvelle structure)
- **Permission** : `write` ou `init` sur le wallet
- **Body** :
```json
{
  "encrypted_value": "<base64 nouvellement chiffré, conforme au nouveau schema>",
  "target_schema_version_uuid": "uuid-of-v3"
}
```
- **Workflow** :
  1. Le client lit le secret avec sa version actuelle
  2. Le client déchiffre la valeur
  3. Le client lit le nouveau schema
  4. Le client adapte la valeur si nécessaire (RJSF peut afficher les champs à compléter)
  5. Le client re-chiffre
  6. Le client envoie la nouvelle valeur + le `target_schema_version_uuid`
- **Validations serveur** :
  - `target_schema_version_uuid` appartient au même `type_uuid` que le secret actuel
  - Le user a la permission `write` ou `init`
- **Effets** :
  - UPDATE secrets SET `encrypted_value` = nouveau, `schema_version_uuid` = target
  - INCREMENT `generation_version` (réutilisation du champ existant pour traçabilité)
- **Audit** : `secret.schema_migrated` avec `metadata.from_version`, `metadata.to_version`
- **Réponse** : `200`

#### Cohérence avec le générateur (lot 06)

Si un secret a un `generation_descriptor` (lot 06) ET un `type_uuid` (lot 17), les deux coexistent :
- Le `generation_descriptor` décrit comment **générer** une valeur
- Le `type_uuid` + `schema_version_uuid` décrivent comment **rendre / éditer** la valeur

Ils doivent être cohérents (un générateur de RSA keypair devrait être typé `tls/keypair-rsa` par exemple), mais le système ne le force pas. Décision admin.

### Sélection du type au moment de la création UI

```
New secret in wallet "ag-flow-prod"
══════════════════════════════════════════════

Name:        [aws_prod_creds____________________________]
Description: [Production AWS credentials______________]
Tags:        [aws] [prod] [+]

─── Type (optional) ───

  Type:      [Select a type ▾]
                ▾
                ── Recently used ──
                aws / credentials (AWS Credentials)
                ── All types ──
                aws / credentials (AWS Credentials)
                azure / service-principal
                gcp / service-account
                ssh / keypair-rsa
                tls / certificate
                ── No structure ──
                (No type — free text)

  Version:   [v2 (current) ▾]
                ▾
                v2 (current)
                v1

─── Value ───

  [Form rendered by RJSF based on selected schema]
  Or, if no type:
  ┌──────────────────────────────────────────┐
  │ (textarea libre)                         │
  └──────────────────────────────────────────┘

[Cancel]  [Create secret]
```

Quand un type est sélectionné, le formulaire RJSF apparaît en dessous, avec :
- Champs selon `schema_data` (input text, select, password masqué via `ui:widget`, etc.)
- Validation live (RJSF affiche les erreurs)
- Boutons disabled tant que pas valid

Si l'admin a configuré `schema_ui` :
```json
{
  "secret_access_key": {
    "ui:widget": "password",
    "ui:options": { "copyable": true, "reveal": true }
  },
  "ui:order": ["access_key_id", "secret_access_key", "region"]
}
```

→ RJSF rend `secret_access_key` comme champ password masqué avec bouton "afficher" et "copier".

### Rendu en lecture

Quand on lit un secret typé :

```
aws_prod_creds                                       [Edit] [...]
══════════════════════════════════════════════════════════════════

Type:        AWS Credentials (v2)
Description: Production AWS credentials
Tags:        aws · prod
Wallet:      ag-flow-prod

─── Values ───

Access Key ID:      AKIAIOSFODNN7EXAMPLE  [Copy]
Secret Access Key:  ••••••••••••  [Reveal] [Copy]
Region:             eu-west-3

⚠ A newer version (v3) is available for this type. [Migrate to v3]

─── Metadata ───

Created:     2026-01-15 by alice@example.com
Updated:     2026-04-22 by bob@example.com
Generation:  v2 (schema), v1 (value version)
```

Si `is_placeholder = true` : afficher l'icône placeholder + bouton "Populate" qui ouvre le formulaire en mode édition vide.

### Mode édition

Réutilise le composant RJSF avec `formData` pré-rempli depuis la valeur déchiffrée.

```
Edit aws_prod_creds
══════════════════════════════════════════════

Access Key ID:      [AKIAIOSFODNN7EXAMPLE_______]
Secret Access Key:  [•••••••••••••_______________] [👁 Reveal]
Region:             [eu-west-3 ▾]

[Cancel]  [Save]
```

Le bouton "Save" est désactivé tant que :
- Le formulaire n'est pas valid (RJSF dit OK)
- Au moins un champ a changé

Click "Save" : le client chiffre la nouvelle valeur, envoie `PATCH /secrets/{name}`.

### Migration de schema UI

Quand `schema_version.is_current = false` :

```
⚠ A newer version (v3) is available

  Changes in v3:
  - Added field: "session_token" (optional)
  - Region enum extended with us-west-2

  [Review changes]  [Migrate to v3]
```

Click "Migrate to v3" → ouvre le formulaire RJSF v3 avec :
- Les champs existants pré-remplis depuis l'ancienne valeur
- Les nouveaux champs vides (l'user les remplit ou les laisse selon `required`)
- Bouton "Save migration"

```
Migrate aws_prod_creds from v2 to v3
══════════════════════════════════════════════

Existing fields:
  Access Key ID:     [AKIAIOSFODNN7EXAMPLE_______]  (preserved)
  Secret Access Key: [•••••••••••••_____________]  (preserved)
  Region:            [eu-west-3 ▾]                 (preserved)

New fields in v3:
  Session Token:     [____________________]
  (optional, leave empty if not applicable)

[Cancel]  [Save migration]
```

Si le passage v2 → v3 introduit des champs `required` non remplissables automatiquement, l'user doit les saisir avant de pouvoir migrer.

### Fallback : secrets sans type

Pour les secrets dont `type_uuid IS NULL` (legacy, ou créés volontairement sans type) :
- Lecture : textarea simple ou champ unique
- Édition : textarea simple
- Pas de validation structurée

Le bouton "Add type" peut apparaître pour permettre à l'user de **typer rétroactivement** un secret existant. Workflow :
1. User clique "Add type"
2. Sélectionne un type
3. Sélectionne une version
4. RJSF essaie de pré-remplir depuis la valeur existante (parsing JSON ; si échec, les champs sont vides)
5. User complète si nécessaire
6. Save → re-encrypt + UPDATE secrets SET `type_uuid`, `schema_version_uuid`

C'est un workflow type "migration", traité par un endpoint spécifique :

#### `PATCH /v1/wallets/{wallet_id}/secrets/{name}/assign-type`

- **Auth** : JWT
- **Permission** : `write`
- **Body** :
```json
{
  "type_uuid": "...",
  "schema_version_uuid": "...",
  "encrypted_value": "<nouvellement chiffré>"
}
```
- **Validations** : type_uuid et schema_version_uuid cohérents (trigger DB)
- **Audit** : `secret.type_assigned`

## Spécifications techniques

### Stack frontend

- **`@rjsf/core`** : moteur de rendu
- **`@rjsf/validator-ajv8`** : validation AJV pour JSON Schema 2020-12
- **`@rjsf/mantine`** : thème Mantine pour cohérence visuelle (sinon `@rjsf/utils` + custom)

### Composant `<TypedSecretForm />`

```typescript
import { Form } from '@rjsf/mantine';
import validator from '@rjsf/validator-ajv8';

interface Props {
  schemaData: object;
  schemaUI: object;
  initialValue?: object;
  onSubmit: (value: object) => void;
  onChange?: (value: object) => void;
  readOnly?: boolean;
}

export function TypedSecretForm({
  schemaData,
  schemaUI,
  initialValue,
  onSubmit,
  onChange,
  readOnly,
}: Props) {
  return (
    <Form
      schema={schemaData}
      uiSchema={{
        ...schemaUI,
        'ui:submitButtonOptions': { norender: true },  // bouton externe
      }}
      formData={initialValue}
      validator={validator}
      onSubmit={(data) => onSubmit(data.formData)}
      onChange={(data) => onChange?.(data.formData)}
      disabled={readOnly}
      readonly={readOnly}
      liveValidate
    />
  );
}
```

### Widgets RJSF custom (optionnel, recommandé)

Pour mieux gérer les secrets, on définit quelques widgets custom RJSF :

```typescript
import type { WidgetProps } from '@rjsf/utils';

const SecretPasswordWidget = (props: WidgetProps) => {
  const [revealed, setRevealed] = useState(false);
  const { value, onChange, options } = props;
  const copyable = options?.copyable;
  const canReveal = options?.reveal !== false;

  return (
    <div>
      <input
        type={revealed ? 'text' : 'password'}
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
      />
      {canReveal && (
        <button onClick={() => setRevealed(r => !r)}>
          {revealed ? '🙈 Hide' : '👁 Reveal'}
        </button>
      )}
      {copyable && (
        <button onClick={() => navigator.clipboard.writeText(value || '')}>
          📋 Copy
        </button>
      )}
    </div>
  );
};

const widgets = {
  password: SecretPasswordWidget,
};
```

Reconnu via `ui:widget: "password"` dans le schema_ui.

### Service backend modifié

```python
# app/services/secrets.py (extrait, partie modifiée)

async def create_secret(
    conn: asyncpg.Connection,
    wallet_id: UUID,
    actor: Actor,
    payload: SecretCreatePayload,
) -> dict:
    # Validation existante de permission, name unique, etc.

    # Validation cohérence type_uuid / schema_version_uuid
    if payload.type_uuid and payload.schema_version_uuid:
        # Trigger DB validera, mais on retourne erreur métier 400 plutôt que 500
        type_match = await conn.fetchval(
            "SELECT 1 FROM secret_schemas WHERE version_uuid = $1 AND parent_uuid = $2",
            payload.schema_version_uuid, payload.type_uuid,
        )
        if not type_match:
            raise BusinessError("schema_version_does_not_belong_to_type")

    # Vérif que le type n'est pas deprecated (warning, pas blocage)
    if payload.type_uuid:
        deprecated = await conn.fetchval(
            "SELECT deprecated_at FROM secret_types WHERE type_uuid = $1",
            payload.type_uuid,
        )
        # On accepte mais on pourrait logger
        if deprecated:
            logger.info("secret_created_with_deprecated_type", type_uuid=str(payload.type_uuid))

    # INSERT
    row = await conn.fetchrow(
        """INSERT INTO secrets
           (wallet_id, name, description, encrypted_value, is_placeholder,
            type_uuid, schema_version_uuid, ...)
           VALUES (...)
           RETURNING id, ...""",
        ...
    )

    return enrich_secret_response(conn, row)


async def enrich_secret_response(conn: asyncpg.Connection, secret_row: dict) -> dict:
    """Ajoute les infos de type et schema si présents."""
    base = {... standard fields ...}

    if secret_row.get("type_uuid"):
        type_row = await conn.fetchrow(
            "SELECT * FROM secret_types WHERE type_uuid = $1",
            secret_row["type_uuid"],
        )
        schema_row = await conn.fetchrow(
            "SELECT * FROM secret_schemas WHERE version_uuid = $1",
            secret_row["schema_version_uuid"],
        )
        is_current = type_row["current_version_uuid"] == secret_row["schema_version_uuid"]

        base["type"] = {
            "type_uuid": str(type_row["type_uuid"]),
            "type": type_row["type"],
            "sous_type": type_row["sous_type"],
            "label": type_row["label"],
            "current_version_uuid": str(type_row["current_version_uuid"]),
        }
        base["schema_version"] = {
            "version_uuid": str(schema_row["version_uuid"]),
            "version": schema_row["version"],
            "schema_data": schema_row["schema_data"],
            "schema_ui": schema_row["schema_ui"],
            "is_current": is_current,
            "current_version_uuid": str(type_row["current_version_uuid"]),
        }
    else:
        base["type"] = None
        base["schema_version"] = None

    return base


async def migrate_schema(
    conn: asyncpg.Connection,
    secret_id: UUID,
    actor: Actor,
    target_version_uuid: UUID,
    new_encrypted_value: bytes,
) -> dict:
    # Charger le secret actuel
    secret = await conn.fetchrow("SELECT * FROM secrets WHERE id = $1", secret_id)
    if not secret["type_uuid"]:
        raise BusinessError("secret_has_no_type_cannot_migrate")

    # Vérifier que target appartient au même type
    target = await conn.fetchrow(
        "SELECT * FROM secret_schemas WHERE version_uuid = $1",
        target_version_uuid,
    )
    if target["parent_uuid"] != secret["type_uuid"]:
        raise BusinessError("schema_version_does_not_belong_to_type")

    # UPDATE
    await conn.execute(
        """UPDATE secrets
           SET encrypted_value = $1,
               schema_version_uuid = $2,
               generation_version = generation_version + 1,
               updated_at = NOW(),
               updated_by_user_id = $3
           WHERE id = $4""",
        new_encrypted_value, target_version_uuid, actor.user_id, secret_id,
    )

    # Audit
    await audit_log(conn, "secret.schema_migrated",
                    actor_user_id=actor.user_id,
                    target_secret_id=secret_id,
                    metadata={
                        "from_version_uuid": str(secret["schema_version_uuid"]),
                        "to_version_uuid": str(target_version_uuid),
                    })
```

### Composant page édition

```typescript
function EditSecretPage({ wallet, secret }: Props) {
  const decryptedValue = useDecryptedValue(secret);  // hook qui déchiffre via wallet_key
  const [formData, setFormData] = useState(decryptedValue);

  const isTyped = secret.type !== null;

  const onSave = async () => {
    let payload: string;
    if (isTyped) {
      payload = JSON.stringify(formData);
    } else {
      payload = formData as string;  // textarea
    }
    const encrypted = await encryptValue(payload, walletKey);
    await api.patch(`/v1/wallets/${wallet.id}/secrets/${secret.name}`, {
      encrypted_value: encrypted,
    });
  };

  if (isTyped) {
    return (
      <TypedSecretForm
        schemaData={secret.schema_version.schema_data}
        schemaUI={secret.schema_version.schema_ui}
        initialValue={JSON.parse(decryptedValue)}
        onChange={setFormData}
        onSubmit={onSave}
      />
    );
  } else {
    return (
      <Textarea
        value={decryptedValue}
        onChange={(e) => setFormData(e.target.value)}
      />
    );
  }
}
```

### SDK Python (lot 09) — adaptations mineures

Le SDK ne change quasi rien : il manipule des bytes chiffrés. Mais on peut ajouter une méthode helper :

```python
class HarpocrateClient:
    def get_secret_typed(self, wallet_name: str, secret_name: str) -> dict:
        """Comme get_secret mais retourne aussi le type info."""
        resp = self._request(...)
        result = {
            "value": self._decrypt(resp["encrypted_value"], wallet_key),
            "type": resp.get("type"),
            "schema_version": resp.get("schema_version"),
        }
        if result["type"]:
            # Parse JSON si typé
            result["value"] = json.loads(result["value"])
        return result
```

## Critères de succès

1. ✅ Migration applique : trigger de cohérence type↔schema actif
2. ✅ Création secret avec `type_uuid` + `schema_version_uuid` cohérents → 201
3. ✅ Création secret avec `schema_version_uuid` d'un autre type → 400
4. ✅ Création secret sans type (legacy) → 201, fonctionne comme avant
5. ✅ `GET /secrets/{name}` enrichit avec `type` et `schema_version` si typé
6. ✅ `is_current = false` si version dépassée
7. ✅ `PATCH /migrate-schema` → met à jour `schema_version_uuid` et `encrypted_value`
8. ✅ `PATCH /migrate-schema` vers une version d'un autre type → 400
9. ✅ `PATCH /migrate-schema` interdit pour API key (401 ou 403)
10. ✅ `PATCH /assign-type` permet de typer un secret legacy
11. ✅ UI sélecteur de type lors création
12. ✅ UI rend RJSF correctement avec schema_data + schema_ui
13. ✅ UI `password` widget masque la valeur, bouton reveal/copy
14. ✅ UI `ui:order` respecté
15. ✅ UI validation avant envoi : refus si invalid
16. ✅ UI affiche bouton "Migrate to vN" si version dépassée
17. ✅ UI workflow migration : pré-rempli, nouveaux champs visibles, save fonctionne
18. ✅ UI fallback textarea pour secrets sans type
19. ✅ UI "Add type" pour typer un secret legacy
20. ✅ Audit log avec metadata pour migration et assign-type
21. ✅ Type deprecated affiché en grisé dans le sélecteur (mais sélectionnable)

## Pièges connus

- **Trigger DB de cohérence** : critique. Sans lui, on peut avoir un secret qui pointe vers un schema d'un autre type → l'UI plante en lecture. Bien le tester avec INSERT/UPDATE valides et invalides.
- **Migration partielle** : un user peut commencer une migration et abandonner. Pas de transaction multi-étape côté serveur. Le secret reste en v_old jusqu'à ce qu'il commit. C'est OK.
- **Échec de migration parce qu'un nouveau champ required est non-rempli** : l'UI doit le détecter avant le submit. RJSF `liveValidate` aide.
- **Secret typé avec valeur non-conforme** (cas où le schema a changé sans migration) : RJSF en mode édition affichera des erreurs sur les champs non conformes. L'user peut quand même save (s'il complète) — mais on ne peut pas l'empêcher de save si la valeur est conforme à `schema_data` même si elle ne l'était pas à l'origine. C'est OK.
- **`generation_descriptor` (lot 06) + `type_uuid` (lot 17)** : indépendants. Un secret peut avoir les deux. Le `generation_descriptor` est utilisé pour `populate` (lot 06), le `type_uuid` pour le rendu UI. Cohérence laissée à l'admin.
- **`type_uuid` deprecated et création de secret** : on accepte toujours (backward compat), juste un log. L'UI peut afficher un warning.
- **API key et migration** : refusée. Décision E2E : un automate ne devrait pas changer la structure d'un secret sans validation humaine.
- **API key et assign-type** : aussi refusée pour les mêmes raisons.
- **Performance enrich_secret_response** : 2 SELECT supplémentaires par lecture de secret. Pour des listes de 100+ secrets, faire un JOIN unique :

```sql
SELECT s.*, t.*, sc.*
FROM secrets s
LEFT JOIN secret_types t ON t.type_uuid = s.type_uuid
LEFT JOIN secret_schemas sc ON sc.version_uuid = s.schema_version_uuid
WHERE s.wallet_id = $1
```

À implémenter dès le départ pour éviter le N+1.

- **schema_data et schema_ui peuvent être lourds** : ne pas les inclure dans la liste des secrets, seulement dans le détail. Le sélecteur de type charge schema_data à la sélection (un seul appel `/secret-types/{id}`).
- **RJSF avec champs en lecture seule** : `readonly` prop fait ça mais `disabled` peut interférer. Tester. Pour la lecture, on peut aussi rendre custom (pas de form, juste affichage des paires clé/valeur).
- **Champs sensibles toujours masqués par défaut en lecture** : si `ui:widget: "password"`, l'affichage par défaut est masqué. Bouton "reveal" pour afficher.
- **Copy to clipboard** : sur HTTPS uniquement. En dev local sur HTTP, fallback à document.execCommand("copy") ou warning.
- **Schema avec $ref externes** : RJSF ne résout pas $ref vers URLs externes par défaut. Si on veut, ajouter un loader. MVP : ne pas supporter.
- **Locale dans schema_data.title et schema.description** : ces strings ne sont pas i18n (lot 16 ne couvre pas le contenu user-defined). Future amélioration : `title_i18n: { en: "...", fr: "..." }` géré par RJSF custom.

## Tests

### Backend

- `test_trigger_rejects_schema_from_other_type`
- `test_create_secret_with_valid_type_and_schema`
- `test_create_secret_with_mismatched_type_schema_400`
- `test_create_secret_without_type_legacy`
- `test_get_secret_enriched_with_type_and_schema`
- `test_get_secret_is_current_false_for_old_version`
- `test_migrate_schema_updates_correctly`
- `test_migrate_schema_increments_generation_version`
- `test_migrate_schema_target_in_other_type_400`
- `test_migrate_schema_blocked_for_api_key`
- `test_assign_type_to_legacy_secret`
- `test_audit_log_for_migration`
- `test_join_query_lists_secrets_with_type_no_n_plus_1`

### Frontend

- `test_type_selector_loads_types_list`
- `test_rjsf_renders_form_from_schema`
- `test_rjsf_password_widget_masks_value`
- `test_rjsf_password_widget_reveal_works`
- `test_rjsf_password_widget_copy_works`
- `test_form_validation_blocks_invalid_submit`
- `test_form_change_detection_for_save_button`
- `test_migrate_button_appears_when_old_version`
- `test_migrate_workflow_prefills_existing_fields`
- `test_migrate_workflow_shows_new_fields`
- `test_legacy_secret_falls_back_to_textarea`
- `test_assign_type_to_legacy_secret_workflow`

## Roadmap au-delà du lot 17

Ces items sont post-MVP, à traiter quand le besoin émerge :

- **Catalogue de types prédéfinis** : seed Harpocrate avec aws/credentials, gcp/sa, ssh/keypair, tls/cert, etc.
- **Validation `type_uuid` dans l'API key** : restreindre une API key à certains types de secrets
- **Migration en masse** : admin déclenche la migration de tous les secrets d'une vN vers vN+1 (mais nécessite passage individuel utilisateur car E2E)
- **`title_i18n` dans schema_data** : labels traduits par locale
- **Schema avec `$ref` externes** : composabilité de schemas (un type "aws/credentials-with-mfa" qui inclut "aws/credentials" + champs MFA)
- **Templates de schema_ui** : presets RJSF par catégorie (cred secrets, cert secrets, etc.) pour aider l'admin à créer des types cohérents
- **Diff visuel entre versions de schema** : "qu'est-ce qui a changé entre v2 et v3 ?"
- **Rollback de migration** : si l'user a migré et veut revenir à l'ancienne version

## Ce qui suit

C'est la fin de la roadmap "structuration des secrets". Le système est complet :
- L15 → catalogue de types versionnés + UI admin
- L16 → UI bilingue (FR/EN)
- L17 → consommation des types côté secrets, RJSF, migration

Prochaine étape probable selon les besoins : **documentation utilisateur multilingue** (les 16 fichiers en `docs/{fr,en}/` qu'on avait identifiés en phase 2 au début), ou **catalogue de types prédéfinis** (lot 18 optionnel), ou nouvelles features fonctionnelles.
