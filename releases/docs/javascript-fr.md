# SDK JavaScript

Client JavaScript pur zero-knowledge pour Harpocrate Vault. Compatible Node 18+ et navigateurs modernes. Distinct du SDK TypeScript : ce package est livré en JS pur (sans étape de build TypeScript ni bundling), idéal pour les projets qui veulent un import direct.

Le SDK déchiffre les secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

Télécharger le tarball depuis cette page, puis :

```bash
npm install ./harpocrate-javascript-sdk-0.1.0.tar.gz
```

## Usage

```javascript
import { VaultClient } from '@harpocrate/sdk-js';

const client = await VaultClient.create({
  token: 'hrpv_1_...',       // ton API token
  baseUrl: 'https://vault.example.com',
});

// Crée un secret
const id = await client.createSecret('DB_PASSWORD', 's3cret!');

// Récupère et déchiffre côté client
const value = await client.getSecret('DB_PASSWORD');

// Met à jour
const gen = await client.putSecret('DB_PASSWORD', 'n3w-s3cret!');

// Supprime
await client.deleteSecret('DB_PASSWORD');
```

## Secrets organisés en arborescence (path-style)

```javascript
await client.createSecret('/db/prod/password', 's3cret!');
const value = await client.getSecret('/db/prod/password');
```

Le SDK utilise la résolution `/by-id/<uuid>` pour les secrets path-style.

## Compatibilité

- Node 18 ou plus récent (WebCrypto API native requise : `globalThis.crypto.subtle`)
- Navigateurs modernes (Chrome 60+, Firefox 60+, Safari 11+, Edge 79+)
- Pas de TypeScript, pas de build step

## Différence avec `@harpocrate/sdk` (TypeScript)

| Caractéristique | `@harpocrate/sdk` | `@harpocrate/sdk-js` |
|---|---|---|
| Langage | TypeScript | JavaScript pur |
| Bundling | tsup (CJS + ESM + .d.ts) | Source ESM directe |
| Idéal pour | Projets TypeScript | Projets JS sans build |

Les deux SDKs partagent la même surface d'API publique.
