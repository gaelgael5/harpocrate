# Lot 11 — UI Web (frontend)

> **Prérequis** : Lots 00-10. C'est le dernier lot, qui transforme le service en produit utilisable par des humains non-techniques.

## Objectif

Fournir une **interface web complète** permettant à un utilisateur humain de :
- Se connecter via Keycloak (OIDC)
- Bootstrapper son compte (créer passphrase + recevoir 24 mots de recovery)
- Faire son unlock à chaque session (passphrase → déchiffrement RAM)
- Gérer ses wallets, secrets, grants, API keys
- Exporter/importer des structures
- Consulter son audit log

C'est le **jalon M3** (MVP user-facing complet).

## Dépendances

- Lots 00-10

## Périmètre

### Inclus

- Application React 18 + TypeScript strict
- Routing : React Router v6
- UI : Mantine v7
- État : Zustand pour le store global, hooks locaux pour le reste
- Validation : Zod pour les schémas
- Auth : OIDC Keycloak via `oidc-client-ts`
- Crypto navigateur :
  - `argon2-browser` (WASM) pour Argon2id
  - `window.crypto.subtle` pour AES-GCM, RSA-OAEP, génération de clés
  - Bibliothèque interne dérivée du SDK Python pour la cohérence
- Tests E2E : Playwright sur les scénarios principaux

### Exclus

- Pas de mobile native (web responsive uniquement)
- Pas de mode offline (le serveur est requis)

### Découpage interne

Le lot 11 est gros. Il se subdivise en 4 sous-lots :

- **11a** : Setup projet + auth OIDC + bootstrap + unlock
- **11b** : Wallets (liste, création, détail, édition, suppression)
- **11c** : Secrets (liste, CRUD, placeholders, populate)
- **11d** : Grants, API keys, Export/Import, Audit log

## Spécifications fonctionnelles

### Architecture des écrans

```
/login                    → Redirection Keycloak
/oauth-callback           → Callback OIDC, redirection /unlock ou /first-login
/first-login              → Création passphrase + affichage 24 mots recovery
/unlock                   → Saisie passphrase pour déchiffrer en RAM
/                         → Dashboard (liste wallets)
/wallets/new              → Création wallet
/wallets/:id              → Détail wallet (onglets : secrets, grants, api-keys, settings)
/wallets/:id/secrets/new  → Nouveau secret (manuel ou placeholder)
/wallets/:id/secrets/:name → Détail secret
/wallets/:id/grants       → Liste/gestion partages
/wallets/:id/api-keys     → Liste/gestion API keys
/wallets/:id/audit        → Audit log filtré sur ce wallet
/wallets/:id/export       → Bouton + preview JSON
/wallets/import           → Drop zone JSON
/audit                    → Audit log global du user
/account                  → Settings : changer passphrase, renouveler recovery
```

### Écran `/first-login`

À l'arrivée, le serveur a renvoyé `404 first_login` → redirection ici.

Étapes :

1. **Génération côté client** :
   - `salt_passphrase = random(16)`
   - `salt_recovery = random(16)`
   - `recovery_seed = random(32)`
   - `recovery_phrase = bip39_encode(recovery_seed)` → 24 mots
   - Génération RSA keypair (2048 ou 4096 selon préférence)
   - `sym_key = random(32)`
2. **Saisie passphrase** : avec confirmation, validation longueur ≥ 12 (configurable)
3. **Affichage 24 mots de recovery** :
   - Confirmation explicite "Je les ai notés" avant de continuer
   - Avertissement : "Sans ces mots, et sans ta passphrase, tes données sont perdues définitivement"
   - Possibilité de télécharger un PDF (texte brut, format simple)
4. **Dérivations** :
   - `pass_key = Argon2id(passphrase, salt_passphrase, params)`
   - `recovery_key = Argon2id(recovery_seed, salt_recovery, params)`
   - `encrypted_rsa_private_key = AES-GCM(rsa_priv_pem, pass_key)`
   - `encrypted_sym_key_by_pass = AES-GCM(sym_key, pass_key)`
   - `encrypted_sym_key_by_recovery = AES-GCM(sym_key, recovery_key)`
5. **POST `/v1/me/bootstrap`** avec tous les blobs
6. **Stockage en RAM** :
   - `rsa_priv` et `sym_key` en clair en RAM (Zustand store, jamais persisté)
7. Redirection `/`

### Écran `/unlock`

À chaque arrivée si pas de session active (RAM vide) :

1. GET `/v1/me/crypto` → reçoit `salt_passphrase`, `encrypted_rsa_private_key`, `encrypted_sym_key_by_pass`, `kdf_params`, `rsa_public_key`
2. Saisie passphrase
3. `pass_key = Argon2id(passphrase, salt_passphrase, kdf_params)`
4. `rsa_priv = AES-GCM-decrypt(encrypted_rsa_private_key, pass_key)`
5. `sym_key = AES-GCM-decrypt(encrypted_sym_key_by_pass, pass_key)`
6. Si échec déchiffrement (InvalidTag) → "passphrase invalide"
7. Stockage RAM, redirection `/`

### Écran `/wallets/new`

1. Saisie : nom, description, tags
2. **Côté client** : `wallet_key = random(32)`
3. **Côté client** : `encrypted_wallet_key_for_owner = RSA-OAEP-encrypt(wallet_key, my_rsa_pub)`
4. POST `/v1/wallets` avec ces données
5. Cache `wallet_key` en RAM (TTL session) pour les opérations suivantes

### Écran `/wallets/:id/secrets/new`

Deux modes :

#### Mode "manuel"

1. Saisie : nom, description, tags, valeur (textarea, ou file upload pour binaire)
2. **Côté client** : récupère `wallet_key` (cache ou déchiffrement à la volée)
3. **Côté client** : `encrypted_value = AES-GCM-encrypt(value, wallet_key)`
4. POST `/v1/wallets/{id}/secrets`

#### Mode "placeholder + générateur"

1. Saisie : nom, description, tags
2. Choix du type de générateur (dropdown)
3. Formulaire dynamique selon le type (length, charset, ...)
4. POST `/v1/wallets/{id}/secrets/placeholder`
5. Sur la page de détail du secret, bouton "Generate value now" :
   - Génère côté client selon le descripteur
   - Chiffre avec wallet_key
   - POST `/v1/wallets/{id}/secrets/{name}/populate`

### Écran `/wallets/:id/secrets/:name`

Affichage :
- Métadonnées (nom, description, tags, generation_descriptor si présent)
- Bouton "Show value" → déchiffre côté client et affiche (avec timeout 30s pour re-cacher)
- Bouton "Copy to clipboard" (sans afficher)
- Bouton "Edit value" (si permission `[write]` ou si placeholder, `[init]`)
- Bouton "Regenerate" si descripteur présent
- Bouton "Delete" (si permission `[remove]`)
- History de versions (à partir des audit logs)

### Écran `/wallets/:id/grants`

- Liste des utilisateurs avec accès, leurs permissions
- Bouton "Share" :
  - Saisie email → GET `/v1/users/lookup?email=...`
  - Si trouvé : afficher `display_name` + RSA pub key (vérification visuelle optionnelle)
  - Sélection des permissions (checkboxes : read, add, init, write, remove, share)
  - **Côté client** : `encrypted_wallet_key_for_grantee = RSA-OAEP-encrypt(wallet_key, grantee_rsa_pub)`
  - POST `/v1/wallets/{id}/grants`
- Pour chaque grant existant : modifier permissions, révoquer
- Owner non modifiable (UI grise et désactive)

### Écran `/wallets/:id/api-keys`

- Liste avec : nom, permissions, expires_at, last_used_at, revoked_at
- Bouton "Create API key" :
  - Saisie : nom, description, permissions, durée d'expiration
  - **Côté client** : génération de tous les éléments crypto (auth_secret, decryption_key, hash, blobs)
  - POST `/v1/wallets/{id}/api-keys`
  - **Affichage one-shot du token** avec :
    - Boîte avec scroll
    - Bouton copy
    - Bouton "I have copied it" (forcé pour fermer)
    - Avertissement "Ce token ne sera jamais réaffiché"
- Pour chaque API key : modifier metadata, révoquer

### Écran `/audit` et `/wallets/:id/audit`

- Tableau filtrable : action, date, acteur, cible, succès
- Filtres : date range, action (dropdown), wallet (sur audit global)
- Pagination

### Écran `/account`

- Affichage : email, display_name, paramètres KDF
- Bouton "Change passphrase" :
  - Saisie ancienne (déchiffre RAM) + nouvelle x2
  - Re-dérive blobs avec nouvelle pass_key
  - PUT `/v1/me/passphrase`
- Bouton "Renew recovery phrase" :
  - Génère nouveau seed + 24 mots
  - Affiche les nouveaux mots
  - Re-chiffre `sym_key` avec nouveau `recovery_key`
  - PUT `/v1/me/recovery`

### Écran `/wallets/:id/export`

- Preview du JSON (sans valeurs)
- Bouton "Download" → fichier `vault-{name}-{date}.json`

### Écran `/wallets/import`

- Drop zone ou bouton "Choose file"
- Validation côté client du JSON (Zod schema)
- Preview : nom du wallet à créer, liste des secrets
- Confirmation
- **Côté client** : génère `wallet_key`, calcule `encrypted_wallet_key_for_owner`
- POST `/v1/wallets/import`

## Spécifications techniques

### Stack et structure

```
frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── routes/
│   │   ├── auth/
│   │   │   ├── Login.tsx
│   │   │   ├── OAuthCallback.tsx
│   │   │   ├── FirstLogin.tsx
│   │   │   └── Unlock.tsx
│   │   ├── wallets/
│   │   │   ├── WalletList.tsx
│   │   │   ├── WalletNew.tsx
│   │   │   ├── WalletDetail.tsx
│   │   │   ├── WalletExport.tsx
│   │   │   └── WalletImport.tsx
│   │   ├── secrets/
│   │   │   ├── SecretList.tsx
│   │   │   ├── SecretNew.tsx
│   │   │   ├── SecretDetail.tsx
│   │   │   └── SecretEdit.tsx
│   │   ├── grants/
│   │   │   ├── GrantList.tsx
│   │   │   └── GrantNew.tsx
│   │   ├── api_keys/
│   │   │   ├── ApiKeyList.tsx
│   │   │   └── ApiKeyNew.tsx
│   │   ├── audit/
│   │   │   └── AuditLog.tsx
│   │   └── account/
│   │       └── Account.tsx
│   ├── stores/
│   │   ├── auth.ts              # JWT, OIDC
│   │   ├── crypto.ts            # rsa_priv, sym_key, wallet_keys cache
│   │   └── ui.ts                # toasts, modals
│   ├── crypto/
│   │   ├── argon2.ts            # wrapper argon2-browser
│   │   ├── aes_gcm.ts           # window.crypto.subtle
│   │   ├── rsa.ts
│   │   ├── bip39.ts
│   │   └── generators/          # mêmes que SDK Python, en TS
│   ├── api/
│   │   ├── client.ts            # axios/fetch wrapper
│   │   ├── auth.ts              # endpoints /me/*
│   │   ├── wallets.ts
│   │   ├── secrets.ts
│   │   ├── grants.ts
│   │   ├── api_keys.ts
│   │   └── audit.ts
│   ├── components/
│   │   ├── Layout.tsx
│   │   ├── PermissionsCheckboxes.tsx
│   │   ├── PassphraseInput.tsx
│   │   ├── RecoveryPhraseDisplay.tsx
│   │   ├── SecretValueDisplay.tsx
│   │   ├── GeneratorForm.tsx
│   │   └── ...
│   ├── schemas/                 # Zod
│   ├── hooks/
│   ├── i18n/                    # FR + EN
│   └── types/
├── public/
├── tests/
│   └── e2e/                     # Playwright
├── package.json
├── vite.config.ts
├── tsconfig.json
└── README.md
```

### Crypto navigateur

#### `argon2-browser`

```typescript
// src/crypto/argon2.ts
import argon2 from 'argon2-browser';

export async function deriveKey(
  passphrase: string,
  salt: Uint8Array,
  params: { memory_kb: number; iterations: number; parallelism: number },
): Promise<Uint8Array> {
  const result = await argon2.hash({
    pass: passphrase,
    salt,
    type: argon2.ArgonType.Argon2id,
    mem: params.memory_kb,
    time: params.iterations,
    parallelism: params.parallelism,
    hashLen: 32,
  });
  return result.hash;
}
```

#### AES-GCM

```typescript
// src/crypto/aes_gcm.ts
export async function aesGcmEncrypt(
  plaintext: Uint8Array,
  key: Uint8Array,
): Promise<Uint8Array> {
  const cryptoKey = await crypto.subtle.importKey(
    'raw', key, 'AES-GCM', false, ['encrypt'],
  );
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, cryptoKey, plaintext),
  );
  // Format : nonce || ciphertext || tag (le tag est inclus par WebCrypto)
  const out = new Uint8Array(nonce.length + ct.length);
  out.set(nonce, 0);
  out.set(ct, nonce.length);
  return out;
}

export async function aesGcmDecrypt(
  blob: Uint8Array,
  key: Uint8Array,
): Promise<Uint8Array> {
  const cryptoKey = await crypto.subtle.importKey(
    'raw', key, 'AES-GCM', false, ['decrypt'],
  );
  const nonce = blob.slice(0, 12);
  const ct = blob.slice(12);
  return new Uint8Array(
    await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce }, cryptoKey, ct),
  );
}
```

#### RSA

```typescript
// src/crypto/rsa.ts
export async function generateRsaKeypair(keySize: 2048 | 4096): Promise<{
  publicKey: Uint8Array;
  privateKey: Uint8Array;
}> {
  const pair = await crypto.subtle.generateKey(
    {
      name: 'RSA-OAEP',
      modulusLength: keySize,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: 'SHA-256',
    },
    true,
    ['encrypt', 'decrypt'],
  );
  const pub = new Uint8Array(await crypto.subtle.exportKey('spki', pair.publicKey));
  const priv = new Uint8Array(await crypto.subtle.exportKey('pkcs8', pair.privateKey));
  return { publicKey: pub, privateKey: priv };
}

export async function rsaOaepEncrypt(
  plaintext: Uint8Array,
  publicKeyDer: Uint8Array,
): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'spki', publicKeyDer, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt'],
  );
  return new Uint8Array(
    await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, key, plaintext),
  );
}
```

### Store crypto (Zustand)

```typescript
// src/stores/crypto.ts
import { create } from 'zustand';

interface CryptoState {
  rsaPrivateKey: Uint8Array | null;
  symKey: Uint8Array | null;
  walletKeys: Map<string, { key: Uint8Array; expiresAt: number }>;
  setUnlock: (rsaPriv: Uint8Array, symKey: Uint8Array) => void;
  cacheWalletKey: (walletId: string, key: Uint8Array) => void;
  getWalletKey: (walletId: string) => Uint8Array | null;
  lock: () => void;  // efface tout
}

export const useCryptoStore = create<CryptoState>((set, get) => ({
  rsaPrivateKey: null,
  symKey: null,
  walletKeys: new Map(),
  setUnlock: (rsaPriv, symKey) => set({ rsaPrivateKey: rsaPriv, symKey }),
  cacheWalletKey: (walletId, key) => {
    const map = new Map(get().walletKeys);
    map.set(walletId, { key, expiresAt: Date.now() + 600_000 });
    set({ walletKeys: map });
  },
  getWalletKey: (walletId) => {
    const entry = get().walletKeys.get(walletId);
    if (!entry || entry.expiresAt < Date.now()) return null;
    return entry.key;
  },
  lock: () => set({ rsaPrivateKey: null, symKey: null, walletKeys: new Map() }),
}));
```

### Auth OIDC

`oidc-client-ts` configuré avec :
- `authority = https://keycloak.yoops.org/realms/agflow`
- `client_id = harpocrate`
- `redirect_uri = https://vault.yoops.org/oauth-callback`
- `scope = openid email profile`

Récupération du token via `userManager.signinRedirect()` et `signinRedirectCallback()`.

### Inactivity timeout

Si pas d'interaction utilisateur pendant 15 minutes, déclencher `cryptoStore.lock()` et rediriger vers `/unlock`. Tracker via mousemove/keypress events.

### i18n

Au minimum FR + EN. Utiliser `react-i18next`. Préférence Gael probablement FR par défaut, mais l'app doit être bilingue.

## Critères de succès

1. ✅ User peut se connecter via Keycloak
2. ✅ First login : génère RSA, dérive Argon2id, affiche 24 mots, bootstrap
3. ✅ User peut se déconnecter et se reconnecter avec sa passphrase
4. ✅ Recovery phrase fonctionne (perdre passphrase, récupérer via 24 mots)
5. ✅ Création wallet + secret + lecture round-trip fonctionne
6. ✅ Partage avec un autre user fonctionne
7. ✅ Le second user peut lire les secrets partagés
8. ✅ Création d'API key affiche le token one-shot
9. ✅ API key créée fonctionne avec le SDK/CLI (test E2E croisé)
10. ✅ Export d'un wallet → JSON sans valeurs
11. ✅ Import d'un JSON → nouveau wallet en placeholders
12. ✅ Audit log filtrable
13. ✅ Change passphrase fonctionne (re-déchiffrement OK avec la nouvelle)
14. ✅ Inactivity timeout déclenche lock
15. ✅ TypeScript strict, pas de `any` toléré
16. ✅ Mantine v7, design cohérent
17. ✅ Tests Playwright des scénarios principaux passent

## Pièges connus

- **`window.crypto.subtle` retourne des Promises** : tout async/await partout.
- **Format des clés exportées** : SPKI pour publique, PKCS8 pour privée. Cohérent avec Python `cryptography` (pas le format PEM mais le DER brut).
- **`argon2-browser` WASM** : nécessite que le site soit en HTTPS ou localhost. En dev, utiliser `vite` qui gère ça.
- **Stockage en RAM uniquement** : ne JAMAIS persister `rsa_priv`, `sym_key`, `wallet_key` dans localStorage/sessionStorage. Zustand stocke en mémoire seulement par défaut, ne pas activer `persist` middleware sur le store crypto.
- **Recovery phrase** : ne JAMAIS la stocker, ne JAMAIS la transmettre. Affichée une fois, copiée par l'humain, oubliée par le navigateur.
- **Token one-shot pour API key** : afficher avec `select-all` au focus pour faciliter la copie. Ne pas envoyer dans des analytics ou logs.
- **`crypto.getRandomValues()`** suffit pour les nonces et seeds. Ne pas utiliser `Math.random()`.
- **AES-GCM avec WebCrypto** : le tag est inclus dans la sortie de `encrypt()` (les 16 derniers bytes du résultat). Pas besoin de séparer manuellement.
- **BIP-39 wordlist** : embarquer les 2048 mots officiels (anglais standard, ou anglais + français selon le store). Le seed encode 256 bits + 8 bits checksum sur 24 mots.
- **Keycloak silent refresh** : configurer `silent_redirect_uri` pour éviter les popups de re-login.
- **CORS** : le backend doit autoriser l'origine du frontend. Configurer dans FastAPI `CORSMiddleware`.
- **CSP strict** : pas d'`unsafe-eval` (sauf pour WASM Argon2 qui peut nécessiter `'wasm-unsafe-eval'`).
- **Inactivity timeout pendant input passphrase** : ne pas l'appliquer pendant la saisie active (sinon UX cassée).
- **Mantine `ColorScheme`** : supporter dark/light mode (préférence Gael : dark probable).
- **Re-derivation Argon2 chaque login** : prend ~1-3 secondes en navigateur. Afficher un spinner explicite "Déchiffrement en cours...".
- **Validation Zod côté client** : doit matcher exactement les contraintes Pydantic du backend, pour éviter les surprises 422.
- **Routing protégé** : tous les chemins `/wallets/*`, `/account`, `/audit` requièrent JWT + crypto unlocked. Sinon redirection vers `/unlock`.

## Sous-lots détaillés

### 11a — Setup + Auth + Bootstrap + Unlock (~1500 lignes TS)

- Setup Vite + Mantine + Zustand + Zod + i18next
- Crypto modules : argon2, aes_gcm, rsa, bip39
- Store auth + crypto
- Pages : Login, OAuthCallback, FirstLogin, Unlock
- Layout principal avec navigation, indicateur unlock
- Tests E2E : flow complet bootstrap + unlock

### 11b — Wallets (~1000 lignes TS)

- Pages : WalletList, WalletNew, WalletDetail (skeleton onglets), WalletEdit
- Composants : WalletCard, TagsInput
- Tests E2E : créer/lister/modifier/supprimer

### 11c — Secrets (~1500 lignes TS)

- Pages : SecretList, SecretNew (manuel + placeholder), SecretDetail, SecretEdit
- GeneratorForm dynamique pour 9 types de générateurs
- Implémentation TS de tous les générateurs (cohérent avec SDK Python)
- SecretValueDisplay avec timeout
- Tests E2E : flux complet création manuelle + placeholder + populate

### 11d — Reste (~1500 lignes TS)

- Pages : GrantList, GrantNew, ApiKeyList, ApiKeyNew, AuditLog, Export, Import, Account
- Composants : PermissionsCheckboxes, ApiKeyTokenDisplay, AuditEventRow
- Tests E2E : partage entre 2 users, création API key, export/import round-trip

## Tests à écrire

Tests Playwright (E2E):

- `test_e2e_bootstrap_flow`
- `test_e2e_unlock_with_passphrase`
- `test_e2e_unlock_wrong_passphrase`
- `test_e2e_recovery_phrase_displayed_and_warned`
- `test_e2e_create_wallet`
- `test_e2e_create_secret_manual`
- `test_e2e_create_placeholder_and_populate`
- `test_e2e_share_wallet_between_users`
- `test_e2e_grantee_can_read_shared_secret`
- `test_e2e_create_api_key_token_displayed_once`
- `test_e2e_api_key_works_with_curl` (test croisé : token créé en UI, lu via curl)
- `test_e2e_export_import_round_trip`
- `test_e2e_audit_log_filterable`
- `test_e2e_change_passphrase`
- `test_e2e_inactivity_timeout_locks`

Tests unitaires (Vitest) :

- Tous les modules crypto (round-trip)
- Tous les générateurs TS
- Stores Zustand
- Validation Zod schemas

## Récap final du projet

Avec ce lot 11, le projet Harpocrate est **complet pour MVP** :

- Backend complet : 36 endpoints API, séparation JWT/API key, E2E crypto, audit
- SDK Python + CLI Bash : automation pour install.sh et agents Docker
- UI Web : utilisable par humains non-tech

**Roadmap post-MVP** : voir `HARPOCRATE_OVERVIEW.md` section 9.

Bon ship.
