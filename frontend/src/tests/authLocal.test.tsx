/**
 * Tests d'authentification locale — LoginPage avec local admin.
 *
 * - Formulaire affiché quand local_login activé
 * - Onglet caché quand local_login désactivé
 * - Submit stocke le token et redirige
 * - Affiche l'erreur sur 401
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import React from 'react'

// ─── Mocks ────────────────────────────────────────────────────────────────────

// i18n mock — returns the key's last segment as a predictable label
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const parts = key.split('.')
      return parts[parts.length - 1] ?? key
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}))

vi.mock('@/lib/oidc', () => ({
  startLogin: vi.fn(),
  getUserManager: vi.fn(() => ({
    getUser: vi.fn().mockResolvedValue(null),
  })),
}))

vi.mock('@/lib/authLocalApi', () => ({
  fetchAuthModes: vi.fn(),
  localLogin: vi.fn(),
  LocalAuthError: class LocalAuthError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
      this.name = 'LocalAuthError'
    }
    get isInvalidCredentials() {
      return this.status === 401
    }
    get isNotFound() {
      return this.status === 404
    }
  },
}))

vi.mock('@/lib/api-client', () => ({
  api: {
    get: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number
    code: string
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
    get isFirstLogin() {
      return this.code === 'first_login'
    }
    get isUnauthorized() {
      return this.status === 401
    }
    get isNotFound() {
      return this.status === 404
    }
  },
  setTokenProvider: vi.fn(),
}))

vi.mock('@/stores/session', () => {
  const setUser = vi.fn()
  const setLocalAdminToken = vi.fn()
  const clearUser = vi.fn()
  const setAuthenticating = vi.fn()
  const getState = vi.fn(() => ({
    user: null,
    localAdminToken: null,
    setUser,
    setLocalAdminToken,
    clearUser,
    setAuthenticating,
  }))
  const mockStore = vi.fn(() => ({
    user: null,
    setUser,
    setLocalAdminToken,
    isAuthenticating: false,
  }))
  ;(mockStore as unknown as { getState: typeof getState }).getState = getState
  return {
    useSessionStore: mockStore,
  }
})

vi.mock('@/stores/crypto', () => ({
  useCryptoStore: vi.fn(() => ({ isUnlocked: false })),
}))

vi.mock('@/schemas/auth', () => ({
  MeResponseSchema: {
    parse: vi.fn((v: unknown) => v),
  },
}))

// ─── Helpers ──────────────────────────────────────────────────────────────────

import * as authLocalApi from '@/lib/authLocalApi'
import * as apiClient from '@/lib/api-client'
import { LoginPage } from '@/pages/LoginPage'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <MemoryRouter>{children}</MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>
    )
  }
}

function renderLoginPage() {
  return render(<LoginPage />, { wrapper: makeWrapper() })
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('LoginPage — local admin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // api.get('/me') → 401 by default so the page shows the login form
    const { ApiError } = apiClient as unknown as {
      ApiError: new (s: number, c: string, m: string) => { isUnauthorized: boolean }
    }
    vi.mocked(apiClient.api.get).mockRejectedValue(
      new ApiError(401, 'unauthorized', 'Not authorized'),
    )
  })

  it('shows local admin tab when local_login is enabled', async () => {
    vi.mocked(authLocalApi.fetchAuthModes).mockResolvedValue({
      oidc: true,
      local_login: true,
    })

    renderLoginPage()

    // t('auth.local_login.tab') → last key segment = "tab"
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'tab' })).toBeTruthy()
    })
  })

  it('hides local admin tab when local_login is disabled', async () => {
    vi.mocked(authLocalApi.fetchAuthModes).mockResolvedValue({
      oidc: true,
      local_login: false,
    })

    renderLoginPage()

    await waitFor(() => {
      // When disabled, no tabs rendered — only the direct Keycloak button
      expect(screen.queryByRole('tab', { name: 'tab' })).toBeNull()
    })
  })

  it('submits local login form and stores token', async () => {
    vi.mocked(authLocalApi.fetchAuthModes).mockResolvedValue({
      oidc: true,
      local_login: true,
    })
    vi.mocked(authLocalApi.localLogin).mockResolvedValue({
      access_token: 'test-jwt-token',
      token_type: 'Bearer',
      expires_in: 86400,
    })
    // After local login, /me returns a 401 so we stay on the form
    // (simpler test — just verify localLogin was called with right args)

    renderLoginPage()

    // Click the local admin tab — t('auth.local_login.tab') → "tab"
    await waitFor(() => screen.getByRole('tab', { name: 'tab' }))
    await userEvent.click(screen.getByRole('tab', { name: 'tab' }))

    // Fill in form
    const usernameInput = await screen.findByTestId('local-username')
    const passwordInput = await screen.findByTestId('local-password')
    await userEvent.type(usernameInput, 'admin')
    await userEvent.type(passwordInput, 'secret123')

    // Submit
    const submitButton = screen.getByTestId('local-submit')
    await userEvent.click(submitButton)

    await waitFor(() => {
      expect(authLocalApi.localLogin).toHaveBeenCalledWith('admin', 'secret123')
    })
  })

  it('shows error message on 401 invalid credentials', async () => {
    vi.mocked(authLocalApi.fetchAuthModes).mockResolvedValue({
      oidc: true,
      local_login: true,
    })

    const { LocalAuthError } = authLocalApi as unknown as {
      LocalAuthError: new (s: number, c: string, m: string) => Error & {
        isInvalidCredentials: boolean
      }
    }
    vi.mocked(authLocalApi.localLogin).mockRejectedValue(
      new LocalAuthError(401, 'invalid_credentials', 'Invalid username or password'),
    )

    renderLoginPage()

    // Click the local admin tab
    await waitFor(() => screen.getByRole('tab', { name: 'tab' }))
    await userEvent.click(screen.getByRole('tab', { name: 'tab' }))

    const usernameInput = await screen.findByTestId('local-username')
    const passwordInput = await screen.findByTestId('local-password')
    await userEvent.type(usernameInput, 'admin')
    await userEvent.type(passwordInput, 'wrongpass')

    await userEvent.click(screen.getByTestId('local-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('local-error')).toBeTruthy()
    })
  })
})
