# LOT 12B — Admin UI (Backup & Maintenance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-only UI pages for backup management and maintenance control, with a maintenance banner visible to all users.

**Architecture:** Decode JWT client-side to detect `realm_access.roles` containing `harpocrate-admin`; admin nav link and route only appear for admins. `MaintenanceBanner` polls the public status endpoint and shows a sticky alert for all users. `AdminBackupsPage` lists/creates/downloads/deletes/restores backups via the `/v1/admin/backups/*` endpoints. All text goes through i18n (fr + en).

**Tech Stack:** React 18, TypeScript strict, Mantine v7, TanStack Query v5, react-router-dom v6, i18next, Vitest + React Testing Library, Zod.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/schemas/admin.ts` | Zod schemas for admin API responses |
| Create | `frontend/src/hooks/useAdminRole.ts` | Decode JWT and return `isAdmin: boolean` |
| Create | `frontend/src/lib/adminApi.ts` | Typed API calls for admin endpoints |
| Create | `frontend/src/components/MaintenanceBanner.tsx` | Sticky banner polling maintenance status |
| Create | `frontend/src/pages/AdminBackupsPage.tsx` | Full backup management UI |
| Modify | `frontend/src/App.tsx` | Add `/admin/backups` protected route |
| Modify | `frontend/src/components/Layout.tsx` | Admin nav link (conditional on `isAdmin`) |
| Modify | `frontend/src/i18n/fr.json` | `admin.*` + `maintenance.*` translations |
| Modify | `frontend/src/i18n/en.json` | Same in English |
| Create | `frontend/src/tests/adminBackups.test.tsx` | Vitest tests for AdminBackupsPage |

---

### Task 1: Zod schemas for admin API

**Files:**
- Create: `frontend/src/schemas/admin.ts`

- [ ] **Step 1: Write the failing test to validate schema shapes**

Create `frontend/src/tests/adminSchemas.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import {
  MaintenanceStatusSchema,
  BackupSchema,
  BackupListResponseSchema,
} from '@/schemas/admin'

describe('admin schemas', () => {
  it('parses a maintenance status response', () => {
    const raw = {
      active: false,
      reason: null,
      started_at: null,
      effective_at: null,
      estimated_end_at: null,
    }
    const parsed = MaintenanceStatusSchema.parse(raw)
    expect(parsed.active).toBe(false)
  })

  it('parses a backup list response', () => {
    const raw = {
      backups: [
        {
          id: 'aaaaaaaa-0000-0000-0000-000000000001',
          filename: 'harpocrate-backup-2026-01-01-12-00-00.tar.age',
          size_bytes: 123456,
          checksum_sha256: 'deadbeef',
          description: 'test',
          created_at: '2026-01-01T12:00:00Z',
          created_by_user_id: null,
          imported: false,
          manifest: null,
        },
      ],
    }
    const parsed = BackupListResponseSchema.parse(raw)
    expect(parsed.backups).toHaveLength(1)
    expect(parsed.backups[0].filename).toBe('harpocrate-backup-2026-01-01-12-00-00.tar.age')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```
cd frontend && npx vitest run src/tests/adminSchemas.test.ts
```
Expected: FAIL — `@/schemas/admin` not found.

- [ ] **Step 3: Write `frontend/src/schemas/admin.ts`**

```typescript
import { z } from 'zod'

export const MaintenanceStatusSchema = z.object({
  active: z.boolean(),
  reason: z.string().nullable(),
  started_at: z.string().nullable(),
  effective_at: z.string().nullable(),
  estimated_end_at: z.string().nullable(),
})

export type MaintenanceStatus = z.infer<typeof MaintenanceStatusSchema>

export const BackupSchema = z.object({
  id: z.string().uuid(),
  filename: z.string(),
  size_bytes: z.number(),
  checksum_sha256: z.string(),
  description: z.string().nullable(),
  created_at: z.string(),
  created_by_user_id: z.string().uuid().nullable(),
  imported: z.boolean(),
  manifest: z.unknown().nullable(),
})

export type Backup = z.infer<typeof BackupSchema>

export const BackupListResponseSchema = z.object({
  backups: z.array(BackupSchema),
})

export type BackupListResponse = z.infer<typeof BackupListResponseSchema>

export const RestoreResultSchema = z.object({
  success: z.boolean(),
  restored_from_backup_id: z.string().uuid(),
  session_epoch_new: z.number(),
  env_restore_file_path: z.string(),
  next_actions: z.array(z.string()),
})

export type RestoreResult = z.infer<typeof RestoreResultSchema>
```

- [ ] **Step 4: Run test to verify it passes**

```
cd frontend && npx vitest run src/tests/adminSchemas.test.ts
```
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add frontend/src/schemas/admin.ts frontend/src/tests/adminSchemas.test.ts
git commit -m "feat(12b): schemas Zod admin maintenance + backups"
```

---

### Task 2: `useAdminRole` hook

**Files:**
- Create: `frontend/src/hooks/useAdminRole.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/useAdminRole.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Minimal JWT payload encoder (no signature — tests only)
function makeToken(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
  return `${header}.${body}.fakesig`
}

describe('hasAdminRole', () => {
  // Import the internal helper — we test the pure function directly
  it('returns true when realm_access.roles contains harpocrate-admin', async () => {
    const { hasAdminRole } = await import('@/hooks/useAdminRole')
    const token = makeToken({ realm_access: { roles: ['harpocrate-admin', 'user'] } })
    expect(hasAdminRole(token)).toBe(true)
  })

  it('returns false when role is absent', async () => {
    const { hasAdminRole } = await import('@/hooks/useAdminRole')
    const token = makeToken({ realm_access: { roles: ['user'] } })
    expect(hasAdminRole(token)).toBe(false)
  })

  it('returns false for an empty token', async () => {
    const { hasAdminRole } = await import('@/hooks/useAdminRole')
    expect(hasAdminRole('')).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```
cd frontend && npx vitest run src/tests/useAdminRole.test.ts
```
Expected: FAIL — `@/hooks/useAdminRole` not found.

- [ ] **Step 3: Write `frontend/src/hooks/useAdminRole.ts`**

```typescript
import { useQuery } from '@tanstack/react-query'
import { getAccessToken } from '@/lib/oidc'
import { useSessionStore } from '@/stores/session'

export function hasAdminRole(token: string): boolean {
  if (!token) return false
  try {
    const parts = token.split('.')
    if (parts.length < 2) return false
    const payload = parts[1]!
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    const claims = JSON.parse(json) as Record<string, unknown>
    const realmAccess = claims['realm_access'] as Record<string, unknown> | undefined
    const roles = realmAccess?.['roles']
    return Array.isArray(roles) && roles.includes('harpocrate-admin')
  } catch {
    return false
  }
}

export function useAdminRole(): boolean {
  const localAdminToken = useSessionStore((s) => s.localAdminToken)

  const { data: oidcToken } = useQuery({
    queryKey: ['oidc-access-token'],
    queryFn: getAccessToken,
    staleTime: 60_000,
    refetchInterval: 60_000,
  })

  const token = oidcToken ?? localAdminToken ?? ''
  return hasAdminRole(token)
}
```

- [ ] **Step 4: Run test to verify it passes**

```
cd frontend && npx vitest run src/tests/useAdminRole.test.ts
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```
git add frontend/src/hooks/useAdminRole.ts frontend/src/tests/useAdminRole.test.ts
git commit -m "feat(12b): hook useAdminRole — décode JWT realm_access.roles"
```

---

### Task 3: Admin API client

**Files:**
- Create: `frontend/src/lib/adminApi.ts`

- [ ] **Step 1: Write `frontend/src/lib/adminApi.ts`**

No separate test needed — this is a thin wrapper over `api`; it will be exercised by the page-level tests.

```typescript
import { api } from '@/lib/api-client'
import {
  MaintenanceStatusSchema,
  BackupListResponseSchema,
  BackupSchema,
  RestoreResultSchema,
  type MaintenanceStatus,
  type BackupListResponse,
  type Backup,
  type RestoreResult,
} from '@/schemas/admin'

export async function fetchMaintenanceStatus(): Promise<MaintenanceStatus> {
  const raw = await api.get<unknown>('/admin/maintenance/status')
  return MaintenanceStatusSchema.parse(raw)
}

export async function enableMaintenance(body: {
  reason: string
  delay_seconds?: number
  estimated_duration_minutes?: number
}): Promise<MaintenanceStatus> {
  const raw = await api.post<unknown>('/admin/maintenance/enable', body)
  return MaintenanceStatusSchema.parse(raw)
}

export async function disableMaintenance(): Promise<MaintenanceStatus> {
  const raw = await api.post<unknown>('/admin/maintenance/disable', {})
  return MaintenanceStatusSchema.parse(raw)
}

export async function fetchBackups(): Promise<BackupListResponse> {
  const raw = await api.get<unknown>('/admin/backups')
  return BackupListResponseSchema.parse(raw)
}

export async function fetchBackup(id: string): Promise<Backup> {
  const raw = await api.get<unknown>(`/admin/backups/${id}`)
  return BackupSchema.parse(raw)
}

export async function createBackup(body: {
  description?: string
}): Promise<Backup> {
  const raw = await api.post<unknown>('/admin/backups', body)
  return BackupSchema.parse(raw)
}

export async function deleteBackup(id: string): Promise<void> {
  await api.delete<void>(`/admin/backups/${id}`)
}

export function backupDownloadUrl(id: string): string {
  return `/v1/admin/backups/${id}/download`
}

export async function restoreBackup(
  id: string,
  body: { age_private_key: string; confirmation: string; auto_enable_maintenance: boolean },
): Promise<RestoreResult> {
  const raw = await api.post<unknown>(`/admin/backups/${id}/restore`, body)
  return RestoreResultSchema.parse(raw)
}
```

- [ ] **Step 2: TypeScript check**

```
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/lib/adminApi.ts
git commit -m "feat(12b): adminApi — wrapper API backup/maintenance"
```

---

### Task 4: i18n translations

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add translations to `frontend/src/i18n/fr.json`**

Add inside the root object (after `"devMode"` block):

```json
  "nav": {
    "wallets": "Coffres",
    "audit": "Audit",
    "account": "Compte",
    "integration": "Intégration",
    "admin": "Admin",
    "lock": "Verrouiller",
    "api_docs": "API docs",
    "theme_dark": "Passer en thème sombre",
    "theme_light": "Passer en thème clair"
  },
```

Also add at root level:

```json
  "maintenance": {
    "banner": "Mode maintenance actif — {{reason}}",
    "bannerNoReason": "Mode maintenance actif",
    "title": "Maintenance",
    "enable": "Activer la maintenance",
    "disable": "Désactiver la maintenance",
    "reason": "Raison",
    "reasonPlaceholder": "Mise à jour de la base de données",
    "delaySeconds": "Délai avant activation (secondes)",
    "estimatedMinutes": "Durée estimée (minutes)",
    "enabling": "Activation...",
    "disabling": "Désactivation...",
    "status": "Statut maintenance",
    "active": "Actif",
    "inactive": "Inactif",
    "startedAt": "Démarré à",
    "estimatedEnd": "Fin estimée"
  },
  "admin": {
    "title": "Administration",
    "backups": {
      "title": "Sauvegardes",
      "create": "Créer une sauvegarde",
      "creating": "Création...",
      "noBackups": "Aucune sauvegarde.",
      "filename": "Fichier",
      "size": "Taille",
      "date": "Date",
      "description": "Description",
      "download": "Télécharger",
      "delete": "Supprimer",
      "deleteConfirm": "Supprimer la sauvegarde {{filename}} ? Cette action est irréversible.",
      "deleting": "Suppression...",
      "restore": "Restaurer",
      "restoreTitle": "Restaurer depuis {{filename}}",
      "restoreWarning": "ATTENTION : La restauration écrase toute la base de données. Cette action est irréversible. Toutes les sessions actives seront invalidées.",
      "agePrivateKey": "Clé privée AGE",
      "agePrivateKeyPlaceholder": "AGE-SECRET-KEY-1...",
      "confirmationLabel": "Confirmation (tapez : {{expected}})",
      "confirmationPlaceholder": "RESTORE harpocrate-backup-...",
      "autoMaintenance": "Activer le mode maintenance automatiquement",
      "restoring": "Restauration en cours...",
      "restoreSuccess": "Restauration réussie — époque session : {{epoch}}",
      "restoreError": "Erreur lors de la restauration",
      "descriptionLabel": "Description (optionnel)",
      "createSuccess": "Sauvegarde créée",
      "deleteSuccess": "Sauvegarde supprimée"
    }
  }
```

- [ ] **Step 2: Add translations to `frontend/src/i18n/en.json`**

Same structure in English:

```json
  "nav": {
    "wallets": "Vaults",
    "audit": "Audit",
    "account": "Account",
    "integration": "Integration",
    "admin": "Admin",
    "lock": "Lock",
    "api_docs": "API docs",
    "theme_dark": "Switch to dark theme",
    "theme_light": "Switch to light theme"
  },
```

At root level:

```json
  "maintenance": {
    "banner": "Maintenance mode active — {{reason}}",
    "bannerNoReason": "Maintenance mode active",
    "title": "Maintenance",
    "enable": "Enable maintenance",
    "disable": "Disable maintenance",
    "reason": "Reason",
    "reasonPlaceholder": "Database update",
    "delaySeconds": "Delay before activation (seconds)",
    "estimatedMinutes": "Estimated duration (minutes)",
    "enabling": "Enabling...",
    "disabling": "Disabling...",
    "status": "Maintenance status",
    "active": "Active",
    "inactive": "Inactive",
    "startedAt": "Started at",
    "estimatedEnd": "Estimated end"
  },
  "admin": {
    "title": "Administration",
    "backups": {
      "title": "Backups",
      "create": "Create backup",
      "creating": "Creating...",
      "noBackups": "No backups.",
      "filename": "File",
      "size": "Size",
      "date": "Date",
      "description": "Description",
      "download": "Download",
      "delete": "Delete",
      "deleteConfirm": "Delete backup {{filename}}? This cannot be undone.",
      "deleting": "Deleting...",
      "restore": "Restore",
      "restoreTitle": "Restore from {{filename}}",
      "restoreWarning": "WARNING: Restoring overwrites the entire database. This action cannot be undone. All active sessions will be invalidated.",
      "agePrivateKey": "AGE private key",
      "agePrivateKeyPlaceholder": "AGE-SECRET-KEY-1...",
      "confirmationLabel": "Confirmation (type: {{expected}})",
      "confirmationPlaceholder": "RESTORE harpocrate-backup-...",
      "autoMaintenance": "Enable maintenance mode automatically",
      "restoring": "Restoring...",
      "restoreSuccess": "Restore successful — session epoch: {{epoch}}",
      "restoreError": "Restore error",
      "descriptionLabel": "Description (optional)",
      "createSuccess": "Backup created",
      "deleteSuccess": "Backup deleted"
    }
  }
```

- [ ] **Step 3: Verify JSON is valid**

```
cd frontend && node -e "require('./src/i18n/fr.json'); require('./src/i18n/en.json'); console.log('OK')"
```
Expected: `OK`.

- [ ] **Step 4: Commit**

```
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(12b): i18n admin/maintenance/backup (fr + en)"
```

---

### Task 5: MaintenanceBanner component

**Files:**
- Create: `frontend/src/components/MaintenanceBanner.tsx`

- [ ] **Step 1: Write `frontend/src/components/MaintenanceBanner.tsx`**

Pattern mirrors `DevModeBanner.tsx` — fixed position, visible to all users when active.

```typescript
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchMaintenanceStatus } from '@/lib/adminApi'

export const MAINTENANCE_BANNER_HEIGHT = 36

export function MaintenanceBanner() {
  const { t } = useTranslation()

  const { data } = useQuery({
    queryKey: ['maintenance-status'],
    queryFn: fetchMaintenanceStatus,
    refetchInterval: 30_000,
    retry: false,
  })

  if (!data?.active) return null

  const message = data.reason
    ? t('maintenance.banner', { reason: data.reason })
    : t('maintenance.bannerNoReason')

  return (
    <div
      role="alert"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: MAINTENANCE_BANNER_HEIGHT,
        zIndex: 1200,
        backgroundColor: '#e67700',
        color: '#fff',
        padding: '8px 16px',
        fontSize: 13,
        fontWeight: 600,
        textAlign: 'center',
        letterSpacing: '0.5px',
        borderBottom: '2px solid #fff3bf',
        boxSizing: 'border-box',
      }}
    >
      ⚠️ {message}
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/MaintenanceBanner.tsx
git commit -m "feat(12b): composant MaintenanceBanner — bandeau orange maintenance"
```

---

### Task 6: AdminBackupsPage

**Files:**
- Create: `frontend/src/pages/AdminBackupsPage.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/tests/adminBackups.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { AdminBackupsPage } from '@/pages/AdminBackupsPage'

// Minimal i18n setup
const testI18n = i18n.createInstance()
void testI18n.use(initReactI18next).init({
  lng: 'en',
  resources: {
    en: {
      translation: {
        'admin.backups.title': 'Backups',
        'admin.backups.create': 'Create backup',
        'admin.backups.noBackups': 'No backups.',
        'admin.backups.filename': 'File',
        'admin.backups.size': 'Size',
        'admin.backups.date': 'Date',
        'admin.backups.download': 'Download',
        'admin.backups.delete': 'Delete',
        'admin.backups.restore': 'Restore',
        'admin.backups.createSuccess': 'Backup created',
        'admin.backups.deleteSuccess': 'Backup deleted',
        'common.loading': 'Loading...',
        'common.cancel': 'Cancel',
        'common.confirm': 'Confirm',
        'maintenance.title': 'Maintenance',
        'maintenance.enable': 'Enable maintenance',
        'maintenance.disable': 'Disable maintenance',
        'maintenance.status': 'Maintenance status',
        'maintenance.active': 'Active',
        'maintenance.inactive': 'Inactive',
        'maintenance.reason': 'Reason',
        'maintenance.enabling': 'Enabling...',
        'maintenance.disabling': 'Disabling...',
      },
    },
  },
})

vi.mock('@/lib/adminApi', () => ({
  fetchBackups: vi.fn(),
  fetchMaintenanceStatus: vi.fn(),
  createBackup: vi.fn(),
  deleteBackup: vi.fn(),
  restoreBackup: vi.fn(),
  backupDownloadUrl: (id: string) => `/v1/admin/backups/${id}/download`,
  enableMaintenance: vi.fn(),
  disableMaintenance: vi.fn(),
}))

import * as adminApi from '@/lib/adminApi'

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <I18nextProvider i18n={testI18n}>
      <MantineProvider>
        <Notifications />
        <QueryClientProvider client={makeQC()}>
          <MemoryRouter>{children}</MemoryRouter>
        </QueryClientProvider>
      </MantineProvider>
    </I18nextProvider>
  )
}

const emptyBackupsResponse = { backups: [] }
const maintenanceInactive = {
  active: false,
  reason: null,
  started_at: null,
  effective_at: null,
  estimated_end_at: null,
}

describe('AdminBackupsPage', () => {
  beforeEach(() => {
    vi.mocked(adminApi.fetchBackups).mockResolvedValue(emptyBackupsResponse)
    vi.mocked(adminApi.fetchMaintenanceStatus).mockResolvedValue(maintenanceInactive)
  })

  it('shows empty state when there are no backups', async () => {
    render(<AdminBackupsPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('No backups.')).toBeInTheDocument()
    })
  })

  it('shows a backup row when one exists', async () => {
    vi.mocked(adminApi.fetchBackups).mockResolvedValue({
      backups: [
        {
          id: 'aaaaaaaa-0000-0000-0000-000000000001',
          filename: 'harpocrate-backup-2026-01-01-12-00-00.tar.age',
          size_bytes: 123456,
          checksum_sha256: 'deadbeef',
          description: 'test backup',
          created_at: '2026-01-01T12:00:00Z',
          created_by_user_id: null,
          imported: false,
          manifest: null,
        },
      ],
    })

    render(<AdminBackupsPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('harpocrate-backup-2026-01-01-12-00-00.tar.age')).toBeInTheDocument()
    })
  })

  it('shows maintenance status as inactive', async () => {
    render(<AdminBackupsPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('Inactive')).toBeInTheDocument()
    })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd frontend && npx vitest run src/tests/adminBackups.test.tsx
```
Expected: FAIL — `@/pages/AdminBackupsPage` not found.

- [ ] **Step 3: Write `frontend/src/pages/AdminBackupsPage.tsx`**

```typescript
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Table,
  Text,
  Button,
  Group,
  Badge,
  Loader,
  Center,
  Alert,
  Modal,
  TextInput,
  Textarea,
  NumberInput,
  Switch,
  Divider,
  Card,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'

import {
  fetchBackups,
  fetchMaintenanceStatus,
  createBackup,
  deleteBackup,
  restoreBackup,
  enableMaintenance,
  disableMaintenance,
  backupDownloadUrl,
} from '@/lib/adminApi'
import type { Backup } from '@/schemas/admin'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function RestoreModal({
  backup,
  opened,
  onClose,
}: {
  backup: Backup
  opened: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const stem = backup.filename.replace(/\.tar\.age$/, '')
  const expected = `RESTORE ${stem}`

  const [ageKey, setAgeKey] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [autoMaint, setAutoMaint] = useState(true)

  const mutation = useMutation({
    mutationFn: () =>
      restoreBackup(backup.id, {
        age_private_key: ageKey,
        confirmation,
        auto_enable_maintenance: autoMaint,
      }),
    onSuccess: (result) => {
      notifications.show({
        color: 'green',
        message: t('admin.backups.restoreSuccess', { epoch: result.session_epoch_new }),
      })
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
      onClose()
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('admin.backups.restoreError')
      notifications.show({ color: 'red', message: msg })
    },
  })

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('admin.backups.restoreTitle', { filename: backup.filename })}
      size="lg"
    >
      <Stack>
        <Alert color="red" title="⚠️">
          {t('admin.backups.restoreWarning')}
        </Alert>
        <TextInput
          label={t('admin.backups.agePrivateKey')}
          placeholder={t('admin.backups.agePrivateKeyPlaceholder')}
          value={ageKey}
          onChange={(e) => setAgeKey(e.currentTarget.value)}
        />
        <TextInput
          label={t('admin.backups.confirmationLabel', { expected })}
          placeholder={expected}
          value={confirmation}
          onChange={(e) => setConfirmation(e.currentTarget.value)}
        />
        <Switch
          label={t('admin.backups.autoMaintenance')}
          checked={autoMaint}
          onChange={(e) => setAutoMaint(e.currentTarget.checked)}
        />
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            loading={mutation.isPending}
            disabled={confirmation !== expected || !ageKey}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? t('admin.backups.restoring') : t('admin.backups.restore')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

function MaintenancePanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['maintenance-status'],
    queryFn: fetchMaintenanceStatus,
    refetchInterval: 15_000,
  })

  const [reason, setReason] = useState('')
  const [delay, setDelay] = useState<number | string>(0)
  const [duration, setDuration] = useState<number | string>(30)

  const enableMut = useMutation({
    mutationFn: () =>
      enableMaintenance({
        reason,
        delay_seconds: typeof delay === 'number' ? delay : 0,
        estimated_duration_minutes: typeof duration === 'number' ? duration : 30,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['maintenance-status'] }),
  })

  const disableMut = useMutation({
    mutationFn: disableMaintenance,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['maintenance-status'] }),
  })

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t('maintenance.status')}</Title>
          <Badge color={status?.active ? 'orange' : 'green'}>
            {status?.active ? t('maintenance.active') : t('maintenance.inactive')}
          </Badge>
        </Group>

        {status?.active ? (
          <Button
            color="green"
            loading={disableMut.isPending}
            onClick={() => disableMut.mutate()}
          >
            {disableMut.isPending ? t('maintenance.disabling') : t('maintenance.disable')}
          </Button>
        ) : (
          <Stack>
            <TextInput
              label={t('maintenance.reason')}
              placeholder={t('maintenance.reasonPlaceholder')}
              value={reason}
              onChange={(e) => setReason(e.currentTarget.value)}
            />
            <Group grow>
              <NumberInput
                label={t('maintenance.delaySeconds')}
                value={delay}
                onChange={setDelay}
                min={0}
              />
              <NumberInput
                label={t('maintenance.estimatedMinutes')}
                value={duration}
                onChange={setDuration}
                min={1}
              />
            </Group>
            <Button
              color="orange"
              loading={enableMut.isPending}
              disabled={!reason}
              onClick={() => enableMut.mutate()}
            >
              {enableMut.isPending ? t('maintenance.enabling') : t('maintenance.enable')}
            </Button>
          </Stack>
        )}
      </Stack>
    </Card>
  )
}

export function AdminBackupsPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [restoreTarget, setRestoreTarget] = useState<Backup | null>(null)
  const [description, setDescription] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-backups'],
    queryFn: fetchBackups,
  })

  const createMut = useMutation({
    mutationFn: () => createBackup({ description: description || undefined }),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.backups.createSuccess') })
      setDescription('')
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteBackup(id),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.backups.deleteSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
    },
  })

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }

  if (error) {
    return <Alert color="red">{error instanceof Error ? error.message : t('common.error')}</Alert>
  }

  return (
    <Stack>
      <Title order={2}>{t('admin.backups.title')}</Title>

      <MaintenancePanel />

      <Divider />

      <Card withBorder>
        <Stack>
          <Title order={4}>{t('admin.backups.create')}</Title>
          <Textarea
            label={t('admin.backups.descriptionLabel')}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            rows={2}
          />
          <Button
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
            w="fit-content"
          >
            {createMut.isPending ? t('admin.backups.creating') : t('admin.backups.create')}
          </Button>
        </Stack>
      </Card>

      {data?.backups.length === 0 ? (
        <Text c="dimmed">{t('admin.backups.noBackups')}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('admin.backups.filename')}</Table.Th>
              <Table.Th>{t('admin.backups.size')}</Table.Th>
              <Table.Th>{t('admin.backups.date')}</Table.Th>
              <Table.Th>{t('admin.backups.description')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.backups.map((b) => (
              <Table.Tr key={b.id}>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {b.filename}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatBytes(b.size_bytes)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {dayjs(b.created_at).format('YYYY-MM-DD HH:mm')}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {b.description ?? '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <Button
                      component="a"
                      href={backupDownloadUrl(b.id)}
                      download={b.filename}
                      size="xs"
                      variant="outline"
                    >
                      {t('admin.backups.download')}
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      color="orange"
                      onClick={() => setRestoreTarget(b)}
                    >
                      {t('admin.backups.restore')}
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      color="red"
                      loading={deleteMut.isPending}
                      onClick={() => {
                        if (confirm(t('admin.backups.deleteConfirm', { filename: b.filename }))) {
                          deleteMut.mutate(b.id)
                        }
                      }}
                    >
                      {t('admin.backups.delete')}
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {restoreTarget && (
        <RestoreModal
          backup={restoreTarget}
          opened={true}
          onClose={() => setRestoreTarget(null)}
        />
      )}
    </Stack>
  )
}
```

- [ ] **Step 4: Run tests**

```
cd frontend && npx vitest run src/tests/adminBackups.test.tsx
```
Expected: PASS (3 tests).

- [ ] **Step 5: TypeScript check**

```
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 6: Commit**

```
git add frontend/src/pages/AdminBackupsPage.tsx frontend/src/tests/adminBackups.test.tsx
git commit -m "feat(12b): page AdminBackupsPage — backup/restore/maintenance UI"
```

---

### Task 7: Wire App.tsx, Layout.tsx, and MaintenanceBanner

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Modify `frontend/src/App.tsx`**

Add import at top (after existing page imports):

```typescript
import { AdminBackupsPage } from '@/pages/AdminBackupsPage'
import { MaintenanceBanner } from '@/components/MaintenanceBanner'
import { MAINTENANCE_BANNER_HEIGHT } from '@/components/MaintenanceBanner'
```

In `ContentWithBannerOffset`, account for the maintenance banner by reading the query result. Actually, since `MaintenanceBanner` is `position: fixed` with `zIndex: 1200` and doesn't shift layout, we don't need to offset content for it — it overlaps like a toast. The existing approach (only dev banner offsets content) stays the same.

Add `<MaintenanceBanner />` right after `<DevModeBanner />`:

```typescript
      <DevModeBanner />
      <MaintenanceBanner />
```

Add the admin route inside the protected routes block (after `/integration`):

```typescript
            <Route path="/admin/backups" element={<AdminBackupsPage />} />
```

- [ ] **Step 2: Modify `frontend/src/components/Layout.tsx`**

Add import:

```typescript
import { useAdminRole } from '@/hooks/useAdminRole'
```

Inside the `Layout` function, add:

```typescript
  const isAdmin = useAdminRole()
```

Add nav link after the integration link (conditional):

```typescript
        {isAdmin && (
          <NavLink
            component={RouterNavLink}
            to="/admin/backups"
            label={t('nav.admin')}
          />
        )}
```

- [ ] **Step 3: TypeScript check**

```
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 4: Run all frontend tests**

```
cd frontend && npx vitest run
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat(12b): câblage route /admin/backups + nav admin conditionnel + MaintenanceBanner"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|-------------|------|
| Admin role detection from JWT | Task 2 |
| Maintenance banner for all users | Task 5 |
| Admin nav link conditional | Task 7 |
| `/admin/backups` route | Task 7 |
| Backup list | Task 6 |
| Create backup | Task 6 |
| Download backup | Task 6 |
| Delete backup | Task 6 |
| Restore with confirmation modal | Task 6 |
| Maintenance enable/disable | Task 6 |
| i18n fr + en | Task 4 |
| Zod schemas | Task 1 |
| API client | Task 3 |

### Type consistency check

- `Backup` type (from `BackupSchema`) used in `AdminBackupsPage` ✓
- `MaintenanceStatus` from `MaintenanceStatusSchema` used in `MaintenanceBanner` + `MaintenancePanel` ✓
- `hasAdminRole` exported from `useAdminRole.ts`, used in tests ✓
- `MAINTENANCE_BANNER_HEIGHT` exported from `MaintenanceBanner.tsx`, used in `App.tsx` ✓
- `backupDownloadUrl` returns `string` used in `<Button component="a" href=...>` ✓
