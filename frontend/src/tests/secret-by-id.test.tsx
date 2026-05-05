/**
 * Smoke test : SecretDetailPage appelle bien GET /by-id/{sid} (et pas l'ancienne URL).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'

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
      <MantineProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={['/wallets/wid-1/secrets/sid-42']}>
            <Routes>
              <Route path="/wallets/:walletId/secrets/:secretId" element={<SecretDetailPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </MantineProvider>,
    )

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/wallets/wid-1/secrets/by-id/sid-42')
    })
  })
})
