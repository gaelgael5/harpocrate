# Harpocrate SDK — TypeScript / JavaScript

Client zero-knowledge pour [Harpocrate Vault](https://github.com/gaelgael5/harpocrate).
Compatible Node 18+ et browsers modernes (Web Crypto API requise).

## Installation

```bash
npm install @harpocrate/sdk
```

## Usage

```ts
import { VaultClient } from '@harpocrate/sdk'

const client = await VaultClient.create({
  token: 'hrpv_1_...',
  baseUrl: 'https://vault.yoops.org',
})

// Lire un secret (déchiffrement client AES-256-GCM via Web Crypto)
const value = await client.getSecret('ANTHROPIC_API_KEY')
console.log(value)

// Lister
const list = await client.listSecrets()
for (const s of list.secrets) {
  console.log(`${s.name} (placeholder=${s.is_placeholder})`)
}

// Créer
const id = await client.createSecret('MY_KEY', 'secret-value')

// Mettre à jour
const gen = await client.putSecret('MY_KEY', 'new-value')

// Supprimer
await client.deleteSecret('MY_KEY')
```

## En JavaScript (CommonJS)

```js
const { VaultClient } = require('@harpocrate/sdk')

(async () => {
  const client = await VaultClient.create({
    token: 'hrpv_1_...',
    baseUrl: 'https://vault.yoops.org',
  })
  const value = await client.getSecret('ANTHROPIC_API_KEY')
  console.log(value)
})()
```

Le paquet expose les deux formats (CJS + ESM) + les types TypeScript.

## Périmètre v0.1.0

- ✅ Parsing token `hrpv_*` (format identique aux autres SDK)
- ✅ Crypto AES-256-GCM via Web Crypto API
- ✅ HTTP client (fetch global, surchargeable via `options.fetch`)
- ✅ Get / List / Create / Put / Delete secrets
- ✅ Cache wallet_key avec déduplication des appels concurrents
- ❌ Placeholders + générateurs (futur)
- ❌ Détection rotation auth_error (LOT 22, futur portage TS)

## Build & test

```bash
npm install
npm run build       # tsup → dist/index.{cjs,mjs,d.ts}
npm run test        # vitest run
npm run lint        # tsc --noEmit
```

## Publication npm

À effectuer manuellement par le mainteneur :

```bash
npm version <patch|minor|major>
npm publish --access public
```
