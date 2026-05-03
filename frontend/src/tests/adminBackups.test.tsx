import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { AdminBackupsPage } from '@/pages/AdminBackupsPage'

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
        'admin.backups.descriptionLabel': 'Description (optional)',
        'admin.backups.creating': 'Creating...',
        'admin.backups.description': 'Description',
        'common.loading': 'Loading...',
        'common.cancel': 'Cancel',
        'common.confirm': 'Confirm',
        'common.error': 'Error',
        'maintenance.title': 'Maintenance',
        'maintenance.enable': 'Enable maintenance',
        'maintenance.disable': 'Disable maintenance',
        'maintenance.status': 'Maintenance status',
        'maintenance.active': 'Active',
        'maintenance.inactive': 'Inactive',
        'maintenance.reason': 'Reason',
        'maintenance.enabling': 'Enabling...',
        'maintenance.disabling': 'Disabling...',
        'maintenance.reasonPlaceholder': 'Database update',
        'maintenance.delaySeconds': 'Delay (seconds)',
        'maintenance.estimatedMinutes': 'Duration (minutes)',
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
      expect(
        screen.getByText('harpocrate-backup-2026-01-01-12-00-00.tar.age'),
      ).toBeInTheDocument()
    })
  })

  it('shows maintenance status as inactive', async () => {
    render(<AdminBackupsPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('Inactive')).toBeInTheDocument()
    })
  })
})
