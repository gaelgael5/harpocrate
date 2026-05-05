# P2 — Frontend migration vers by-id

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Faire pointer le frontend sur les routes backend by-id (livrées en P1) au lieu des routes par nom URL-encodées (qui cassent sur les noms à `/` à cause du décodage proxy `%2F → /`).

**Architecture:** L'URL React Router `/wallets/:walletId/secrets/:secretId` remplace `/wallets/:walletId/secrets/:secretName`. `SecretCard` navigue avec `secret.id` (UUID). `SecretDetailPage` lit `secretId` depuis l'URL et appelle les routes `/by-id/{sid}`. Les `encodeURIComponent` rustines disparaissent. `ExportAllPage` est aussi migré.

**Tech Stack:** Vite + React 18 + TS strict + react-router-dom + TanStack Query + Mantine + Vitest + React Testing Library.

---

## File Structure

| Fichier | Modification |
|---|---|
| `frontend/src/App.tsx:155` | Route `:secretName` → `:secretId` |
| `frontend/src/pages/WalletDetailPage.tsx:121-128` | `SecretCard` navigate par ID, retire `encodedName` |
| `frontend/src/pages/SecretDetailPage.tsx` | useParams lit `secretId`, queries/mutations utilisent `/by-id/{sid}`, retire les `encodeURIComponent` |
| `frontend/src/pages/ExportAllPage.tsx:109-112` | Boucle export utilise `/by-id/{sid}` |

Test : `frontend/src/tests/secret-by-id.test.tsx` (nouveau, smoke test que SecretDetailPage utilise bien la route by-id).

---

## Task 1: Renommer la route React Router en `:secretId`

**Files:** `frontend/src/App.tsx`

- [ ] **Step 1.1: Modifier la route**

Dans `frontend/src/App.tsx` ligne 155, remplacer :
```tsx
<Route
  path="/wallets/:walletId/secrets/:secretName"
  element={<SecretDetailPage />}
/>
```
par :
```tsx
<Route
  path="/wallets/:walletId/secrets/:secretId"
  element={<SecretDetailPage />}
/>
```

- [ ] **Step 1.2: Vérifier qu'aucune autre route ne référence `:secretName`**

```bash
cd /e/srcs/harpocrate && grep -rn ":secretName" frontend/src/ 2>&1
```
Expected : seul `App.tsx` (avant modif) et `SecretDetailPage.tsx` (sera modifié à la T3) le mentionnent.

- [ ] **Step 1.3: Pas de commit isolé** — on commitera tout en T5 (la route et les pages doivent migrer ensemble pour rester compilable).

---

## Task 2: `WalletDetailPage` — navigate par ID

**Files:** `frontend/src/pages/WalletDetailPage.tsx`

- [ ] **Step 2.1: Modifier `SecretCard`**

Lignes 119-156 (la fonction `SecretCard`), remplacer :
```tsx
function SecretCard({ secret, walletId }: { secret: SecretListItem | PathSecret; walletId: string }) {
  const navigate = useNavigate()
  const encodedName = encodeURIComponent(secret.name)

  return (
    <Card
      withBorder
      padding="sm"
      style={{ cursor: 'pointer' }}
      onClick={() => navigate(`/wallets/${walletId}/secrets/${encodedName}`)}
    >
```
par :
```tsx
function SecretCard({ secret, walletId }: { secret: SecretListItem | PathSecret; walletId: string }) {
  const navigate = useNavigate()

  return (
    <Card
      withBorder
      padding="sm"
      style={{ cursor: 'pointer' }}
      onClick={() => navigate(`/wallets/${walletId}/secrets/${secret.id}`)}
    >
```

(suppression de la ligne `const encodedName = ...` ; navigation par `secret.id`)

- [ ] **Step 2.2: Pas de commit isolé** — voir T5.

---

## Task 3: `SecretDetailPage` — utilise by-id

**Files:** `frontend/src/pages/SecretDetailPage.tsx`

- [ ] **Step 3.1: Renommer le param URL et adapter la query**

Ligne 43-46, remplacer :
```tsx
const { walletId, secretName } = useParams<{
  walletId: string
  secretName: string
}>()
```
par :
```tsx
const { walletId, secretId } = useParams<{
  walletId: string
  secretId: string
}>()
```

- [ ] **Step 3.2: Adapter la `useQuery`**

Lignes 115-124, remplacer :
```tsx
const { data: secret, isLoading, error } = useQuery({
  queryKey: ['secret', walletId, secretName],
  queryFn: async () => {
    const raw = await api.get<unknown>(
      `/wallets/${walletId ?? ''}/secrets/${encodeURIComponent(secretName ?? '')}`,
    )
    return SecretDetailResponseSchema.parse(raw)
  },
  enabled: !!walletId && !!secretName,
})
```
par :
```tsx
const { data: secret, isLoading, error } = useQuery({
  queryKey: ['secret', walletId, secretId],
  queryFn: async () => {
    const raw = await api.get<unknown>(
      `/wallets/${walletId ?? ''}/secrets/by-id/${secretId ?? ''}`,
    )
    return SecretDetailResponseSchema.parse(raw)
  },
  enabled: !!walletId && !!secretId,
})
```

- [ ] **Step 3.3: Adapter `handleSaveEdit` (PUT)**

Ligne 70-73, remplacer :
```tsx
await api.put<unknown>(
  `/wallets/${walletId}/secrets/${encodeURIComponent(secret.name)}`,
  { encrypted_value: toBase64(encValue) },
)
```
par :
```tsx
await api.put<unknown>(
  `/wallets/${walletId}/secrets/by-id/${secret.id}`,
  { encrypted_value: toBase64(encValue) },
)
```

Et ligne 79, remplacer :
```tsx
await queryClient.invalidateQueries({ queryKey: ['secret', walletId, secret.name] })
```
par :
```tsx
await queryClient.invalidateQueries({ queryKey: ['secret', walletId, secret.id] })
```

- [ ] **Step 3.4: Adapter `handleDelete` (DELETE)**

Ligne 93, remplacer :
```tsx
await api.delete<unknown>(`/wallets/${walletId}/secrets/${encodeURIComponent(secret.name)}`)
```
par :
```tsx
await api.delete<unknown>(`/wallets/${walletId}/secrets/by-id/${secret.id}`)
```

- [ ] **Step 3.5: Mettre à jour le commentaire en tête de fichier**

Lignes 1-9, remplacer le bloc :
```tsx
/**
 * Secret detail page — shows metadata, decrypts and displays value on demand.
 *
 * Decrypt flow:
 * 1. GET /v1/wallets/{id}/secrets/{name} → encrypted_value + encrypted_wallet_key
 * 2. Decrypt wallet_key using rsa_priv (RSA-OAEP)
 * 3. Decrypt value using wallet_key (AES-GCM)
 * 4. Show for 30 seconds then auto-hide
 */
```
par :
```tsx
/**
 * Secret detail page — shows metadata, decrypts and displays value on demand.
 *
 * Decrypt flow:
 * 1. GET /v1/wallets/{id}/secrets/by-id/{secret_id} → encrypted_value + encrypted_wallet_key
 * 2. Decrypt wallet_key using rsa_priv (RSA-OAEP)
 * 3. Decrypt value using wallet_key (AES-GCM)
 * 4. Show for 30 seconds then auto-hide
 */
```

- [ ] **Step 3.6: Pas de commit isolé** — voir T5.

---

## Task 4: `ExportAllPage` — utilise by-id pour la boucle

**Files:** `frontend/src/pages/ExportAllPage.tsx`

- [ ] **Step 4.1: Modifier l'appel dans la boucle**

Ligne 109-112 (avec `s` étant un secret de la liste), remplacer :
```tsx
const detailRaw = await api.get<unknown>(
  `/wallets/${wallet.id}/secrets/${encodeURIComponent(s.name)}`,
)
```
par :
```tsx
const detailRaw = await api.get<unknown>(
  `/wallets/${wallet.id}/secrets/by-id/${s.id}`,
)
```

- [ ] **Step 4.2: Pas de commit isolé** — voir T5.

---

## Task 5: Build TypeScript + commit unifié

**Files:** tous ceux des Tasks 1-4.

- [ ] **Step 5.1: TypeScript strict check**

```bash
cd /e/srcs/harpocrate/frontend && npx tsc --noEmit 2>&1 | tail -20
```
Expected : aucune erreur sur `App.tsx`, `WalletDetailPage.tsx`, `SecretDetailPage.tsx`, `ExportAllPage.tsx`.

Si erreurs : corriger AVANT de commiter. Les types `SecretListItem` et `PathSecret` ont déjà `id: string` (`schemas/secrets.ts` et schema dans `WalletDetailPage`), donc la migration ne devrait rien casser au compile.

- [ ] **Step 5.2: ESLint**

```bash
cd /e/srcs/harpocrate/frontend && npm run lint 2>&1 | tail -10
```
Expected : pas de nouveaux warnings/erreurs sur les fichiers modifiés.

- [ ] **Step 5.3: Vitest sur les tests existants**

```bash
cd /e/srcs/harpocrate/frontend && npm test -- --run 2>&1 | tail -20
```
Expected : tous les tests existants PASS (les tests touchant ces pages — s'il y en a — peuvent nécessiter mise à jour, mais a priori il n'y a pas de tests sur SecretDetailPage/ExportAllPage).

- [ ] **Step 5.4: Commit unifié**

```bash
cd /e/srcs/harpocrate && git add frontend/src/App.tsx frontend/src/pages/WalletDetailPage.tsx frontend/src/pages/SecretDetailPage.tsx frontend/src/pages/ExportAllPage.tsx
git commit -m "feat(frontend): migration secrets vers routes by-id (UUID au lieu de nom URL-encodé)"
```

---

## Task 6: Test smoke React Testing Library

**Files:** `frontend/src/tests/secret-by-id.test.tsx` (nouveau)

- [ ] **Step 6.1: Créer un test smoke qui vérifie l'URL appelée**

Créer `frontend/src/tests/secret-by-id.test.tsx` :

```tsx
/**
 * Smoke test : SecretDetailPage appelle bien GET /by-id/{sid} (et pas l'ancienne URL).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock de l'API client
vi.mock('@/lib/api-client', () => ({
  api: {
    get: vi.fn(() => Promise.resolve({
      id: 'ab12cd34-0000-0000-0000-000000000001',
      name: '/users/no_email/api-1',
      encrypted_value: 'YWFhYQ==',
      encrypted_wallet_key: 'YmJiYg==',
      description: null,
      tags: [],
      is_placeholder: false,
      generation_version: 1,
      type_uuid: null,
      schema_version_uuid: null,
    })),
    put: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class extends Error {},
}))

// Mock crypto store (inutile pour ce smoke test mais évite les warnings)
vi.mock('@/stores/crypto', () => ({
  useCryptoStore: vi.fn(() => null),
}))

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock notifications
vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import { api } from '@/lib/api-client'
import { SecretDetailPage } from '@/pages/SecretDetailPage'

describe('SecretDetailPage with by-id route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls GET /v1/wallets/{wid}/secrets/by-id/{sid}, not the legacy name route', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/wallets/wid-1/secrets/sid-42']}>
          <Routes>
            <Route path="/wallets/:walletId/secrets/:secretId" element={<SecretDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/wallets/wid-1/secrets/by-id/sid-42')
    })
  })
})
```

- [ ] **Step 6.2: Lancer le test**

```bash
cd /e/srcs/harpocrate/frontend && npm test -- --run secret-by-id 2>&1 | tail -15
```
Expected : test PASS.

- [ ] **Step 6.3: Commit**

```bash
git add frontend/src/tests/secret-by-id.test.tsx
git commit -m "test(frontend): smoke test SecretDetailPage utilise route by-id"
```

---

## Acceptance criteria P2

- ✅ TypeScript strict OK sur tous les fichiers modifiés
- ✅ ESLint OK
- ✅ Vitest : tests existants verts + nouveau test smoke vert
- ✅ `SecretCard` navigate vers `/wallets/{wid}/secrets/{secret.id}` (UUID)
- ✅ `SecretDetailPage` GET/PUT/DELETE utilisent `/by-id/{secret.id}`
- ✅ `ExportAllPage` boucle export utilise `/by-id/{s.id}`
- ✅ Plus aucun `encodeURIComponent` dans les URLs `/secrets/...`

## Hors scope P2

- L'ancienne route React Router `/secrets/:secretName` est supprimée — un user qui a un bookmark vers l'ancien format aura un 404 React Router. Acceptable parce que ces bookmarks ne marchaient déjà pas pour les noms à `/`.
- Les routes backend `/{name}` restent intactes (cohabitation depuis P1) — utiles pour les SDK Python qui n'ont pas encore migré (P3).
