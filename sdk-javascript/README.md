# Harpocrate SDK JavaScript

Client JavaScript pur (sans TypeScript) zero-knowledge pour [Harpocrate Vault](https://github.com/gaelgael5/harpocrate).

Le SDK déchiffre les valeurs des secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

```bash
npm install @harpocrate/sdk-js
```

## Usage

```javascript
import { VaultClient } from '@harpocrate/sdk-js';

const client = await VaultClient.create({
  token: 'hrpv_1_...', // ton API token
  baseUrl: 'https://vault.example.com',
});

// Crée un secret avec un nom path-style (organisé en arborescence)
const id = await client.createSecret('/db/prod/password', 's3cret!');
console.log('created:', id);

// Récupère et déchiffre côté client
const value = await client.getSecret('/db/prod/password');
console.log('value:', value);

// Met à jour
const gen = await client.putSecret('/db/prod/password', 'n3w-s3cret!');
console.log('generation:', gen);

// Supprime
await client.deleteSecret('/db/prod/password');
```

## Support des secrets path-style

Les noms contenant `/` (ex: `db/prod/password`) sont supportés de manière
transparente. En interne, le SDK :

1. Détecte le `/` dans le nom
2. Liste les secrets du dossier parent via `GET /secrets?path=<parent>`
3. Trouve l'UUID correspondant
4. Effectue l'opération via les routes `/secrets/by-id/<sid>`

Cette stratégie évite la dépendance au comportement des reverse proxies vis-à-vis
des `/` URL-encodés (`%2F`) — pattern aligné sur le SDK Python 0.6.0.

## Différence avec `@harpocrate/sdk` (TypeScript)

- **`@harpocrate/sdk-js`** : JavaScript pur, source publiée telle quelle (`src/*.js`),
  sans bundling ni étape de build. Idéal pour les projets qui ne veulent pas de
  TypeScript ou consomment via require/import direct dans Node ou navigateur moderne.
- **`@harpocrate/sdk`** : TypeScript avec déclarations `.d.ts` générées, bundle ESM + CJS.
  Idéal pour les projets TypeScript.

Les deux SDKs partagent la même surface d'API publique.

## Compatibilité

- Node 18+ (WebCrypto API natif requis : `globalThis.crypto.subtle`)
- Navigateurs modernes (Chrome 60+, Firefox 60+, Safari 11+, Edge 79+)
- Format de token `hrpv_*` identique aux SDK Python/Rust/TypeScript/Go/C#
- Crypto AES-256-GCM (format `nonce(12) || ciphertext || tag(16)`)

## Tests

```bash
npm install
npm test
```

## Licence

MIT
