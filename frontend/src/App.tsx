/**
 * App root — sets up OIDC, router, and inactivity timeout.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { LoadingOverlay } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import { api } from '@/lib/api-client'
import { initOidc } from '@/lib/oidc'
import { KeycloakConfigSchema } from '@/schemas/auth'
import { useCryptoStore } from '@/stores/crypto'
import { useSessionStore } from '@/stores/session'

import { ProtectedRoute } from '@/components/ProtectedRoute'
import { Layout } from '@/components/Layout'
import { InactivityGuard } from '@/components/InactivityGuard'
import { DevModeBanner } from '@/components/DevModeBanner'
import { InsecureContextGuard } from '@/components/InsecureContextGuard'
import { useDevMode, DEV_BANNER_HEIGHT } from '@/hooks/useDevMode'

import { LoginPage } from '@/pages/LoginPage'
import { OAuthCallbackPage } from '@/pages/OAuthCallbackPage'
import { FirstLoginPage } from '@/pages/FirstLoginPage'
import { UnlockPage } from '@/pages/UnlockPage'
import { WalletsPage } from '@/pages/WalletsPage'
import { WalletDetailPage } from '@/pages/WalletDetailPage'
import { WalletNewPage } from '@/pages/WalletNewPage'
import { SecretDetailPage } from '@/pages/SecretDetailPage'
import { SecretNewPage } from '@/pages/SecretNewPage'
import { GrantsPage } from '@/pages/GrantsPage'
import { ApiKeysPage } from '@/pages/ApiKeysPage'
import { AuditLogPage } from '@/pages/AuditLogPage'
import { AccountPage } from '@/pages/AccountPage'

/** Wrapper qui pousse tout le contenu sous le bandeau dev (s'il est actif). */
function ContentWithBannerOffset({ children }: { children: ReactNode }) {
  const { enabled } = useDevMode()
  return (
    <div style={{ paddingTop: enabled ? DEV_BANNER_HEIGHT : 0, minHeight: '100vh' }}>
      {children}
    </div>
  )
}

export default function App() {
  const { t } = useTranslation()
  const [oidcReady, setOidcReady] = useState(false)
  const lock = useCryptoStore((s) => s.lock)
  const clearUser = useSessionStore((s) => s.clearUser)

  useEffect(() => {
    // Fetch Keycloak config and initialize OIDC
    api
      .get<unknown>('/config/keycloak')
      .then((data) => {
        const config = KeycloakConfigSchema.parse(data)
        initOidc(config)
        setOidcReady(true)
      })
      .catch((err: unknown) => {
        notifications.show({
          color: 'red',
          title: t('common.error'),
          message: String(err),
        })
      })
  }, [t])

  if (!oidcReady) {
    return <LoadingOverlay visible />
  }

  return (
    <BrowserRouter>
      <DevModeBanner />
      <ContentWithBannerOffset>
      <InsecureContextGuard>
      <InactivityGuard
        timeoutMs={15 * 60 * 1000}
        onTimeout={() => {
          lock()
          clearUser()
        }}
      >
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/oauth-callback" element={<OAuthCallbackPage />} />
          <Route path="/first-login" element={<FirstLoginPage />} />
          <Route path="/unlock" element={<UnlockPage />} />

          {/* Protected routes — require OIDC + vault unlocked */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/wallets" replace />} />
            <Route path="/wallets" element={<WalletsPage />} />
            <Route path="/wallets/new" element={<WalletNewPage />} />
            <Route path="/wallets/:walletId" element={<WalletDetailPage />} />
            <Route
              path="/wallets/:walletId/secrets/new"
              element={<SecretNewPage />}
            />
            <Route
              path="/wallets/:walletId/secrets/:secretName"
              element={<SecretDetailPage />}
            />
            <Route
              path="/wallets/:walletId/grants"
              element={<GrantsPage />}
            />
            <Route
              path="/wallets/:walletId/api-keys"
              element={<ApiKeysPage />}
            />
            <Route path="/audit" element={<AuditLogPage />} />
            <Route path="/account" element={<AccountPage />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </InactivityGuard>
      </InsecureContextGuard>
      </ContentWithBannerOffset>
    </BrowserRouter>
  )
}
