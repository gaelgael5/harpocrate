# SDK TypeScript

Client TypeScript zero-knowledge pour Harpocrate Vault. Compatible Node 18+ et navigateurs modernes.

Le SDK déchiffre les secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

Télécharger le tarball depuis cette page, puis :

```bash
npm install ./harpocrate-typescript-sdk-0.2.0.tgz
```

Ou dans un `package.json` :

```json
{
  "dependencies": {
    "@harpocrate/sdk": "file:./harpocrate-typescript-sdk-0.2.0.tgz"
  }
}
```

## Usage

```typescript
import { VaultClient } from '@harpocrate/sdk';

const client = await VaultClient.create({
  token: 'hrpv_1_...',       // ton API token
  baseUrl: 'https://vault.example.com',
});

// Crée un secret
const id = await client.createSecret('DB_PASSWORD', 's3cret!');
console.log('id =', id);

// Récupère et déchiffre côté client
const value = await client.getSecret('DB_PASSWORD');
console.log('value =', value);

// Met à jour
const gen = await client.putSecret('DB_PASSWORD', 'n3w-s3cret!');

// Supprime
await client.deleteSecret('DB_PASSWORD');
```

## Secrets organisés en arborescence (path-style)

Les noms contenant `/` sont supportés de manière transparente :

```typescript
await client.createSecret('/db/prod/password', 's3cret!');
const value = await client.getSecret('/db/prod/password');
```

Depuis la version 0.2.0, le SDK utilise la résolution `/by-id/<uuid>` pour les
secrets path-style (résolution via `GET /secrets?path=<parent>`). Cela évite
toute dépendance au comportement des reverse proxies vis-à-vis des `/`
URL-encodés (`%2F`).

## Compatibilité

- Node 18 ou plus récent (WebCrypto API native requise)
- Navigateurs modernes (Chrome 60+, Firefox 60+, Safari 11+, Edge 79+)
- TypeScript 5.0+

## Pour aller plus loin

Voir le [README complet du SDK](https://github.com/gaelgael5/harpocrate/tree/main/sdk-typescript) sur GitHub.
