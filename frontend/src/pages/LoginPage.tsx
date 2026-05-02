/**
 * Login page — checks /v1/me and routes appropriately:
 * - 401 (no session): show login tabs (Keycloak + Local admin if enabled)
 * - 404 first_login: redirect to /first-login
 * - 200: redirect to /unlock (or / if already unlocked)
 *
 * The "Local admin" tab is shown only when GET /v1/config/auth-modes
 * returns local_login=true.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Center,
  Stack,
  Title,
  Text,
  Button,
  Loader,
  Tabs,
  TextInput,
  PasswordInput,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { api, ApiError, setTokenProvider } from '@/lib/api-client'
import { startLogin, getUserManager } from '@/lib/oidc'
import { localLogin, LocalAuthError } from '@/lib/authLocalApi'
import { useLocalLoginAvailable } from '@/hooks/useLocalLoginAvailable'
import { MeResponseSchema } from '@/schemas/auth'
import { useSessionStore } from '@/stores/session'
import { useCryptoStore } from '@/stores/crypto'

type State = 'loading' | 'show-login' | 'redirecting'

export function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const setUser = useSessionStore((s) => s.setUser)
  const setLocalAdminToken = useSessionStore((s) => s.setLocalAdminToken)
  const isUnlocked = useCryptoStore((s) => s.isUnlocked)

  const [state, setState] = useState<State>('loading')
  const [loginError, setLoginError] = useState<string | null>(null)

  // Local admin form state
  const [localUsername, setLocalUsername] = useState('')
  const [localPassword, setLocalPassword] = useState('')
  const [localSubmitting, setLocalSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const { localLoginAvailable } = useLocalLoginAvailable()

  // ─── Probe existing session ────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false

    async function probe() {
      try {
        // Check if we have a valid OIDC session first
        const mgr = getUserManager()
        const user = await mgr.getUser()

        if (!user || user.expired) {
          // Check for local admin token
          const localToken = useSessionStore.getState().localAdminToken
          if (!localToken) {
            if (!cancelled) setState('show-login')
            return
          }
        }

        // We have a session — check if bootstrapped
        const me = await api.get<unknown>('/me')
        const parsed = MeResponseSchema.parse(me)
        setUser({
          id: parsed.id,
          keycloak_sub: parsed.keycloak_sub,
          email: parsed.email,
          display_name: parsed.display_name,
          has_bootstrap: parsed.has_bootstrap,
          rsa_key_size: parsed.rsa_key_size,
          kdf_params: parsed.kdf_params,
        })

        if (!cancelled) {
          setState('redirecting')
          navigate(isUnlocked ? '/' : '/unlock', { replace: true })
        }
      } catch (err) {
        if (cancelled) return

        if (err instanceof ApiError) {
          if (err.isFirstLogin) {
            setState('redirecting')
            navigate('/first-login', { replace: true })
            return
          }
          if (err.isUnauthorized) {
            setState('show-login')
            return
          }
        }
        setState('show-login')
        setLoginError(String(err))
      }
    }

    void probe()
    return () => {
      cancelled = true
    }
  }, [navigate, setUser, isUnlocked])

  // ─── Local admin submit ────────────────────────────────────────────────────

  async function handleLocalSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLocalError(null)
    setLocalSubmitting(true)

    try {
      const resp = await localLogin(localUsername, localPassword)

      // Store token and wire it into the token provider
      setLocalAdminToken(resp.access_token)
      setTokenProvider(async () => resp.access_token)

      // Check /me to determine next route
      const me = await api.get<unknown>('/me')
      const parsed = MeResponseSchema.parse(me)
      setUser({
        id: parsed.id,
        keycloak_sub: parsed.keycloak_sub,
        email: parsed.email,
        display_name: parsed.display_name,
        has_bootstrap: parsed.has_bootstrap,
        rsa_key_size: parsed.rsa_key_size,
        kdf_params: parsed.kdf_params,
      })
      navigate(isUnlocked ? '/' : '/unlock', { replace: true })
    } catch (err) {
      if (err instanceof LocalAuthError && err.isInvalidCredentials) {
        setLocalError(t('auth.local_login.invalid_credentials'))
      } else if (err instanceof ApiError && err.isFirstLogin) {
        navigate('/first-login', { replace: true })
      } else {
        setLocalError(String(err))
      }
    } finally {
      setLocalSubmitting(false)
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  if (state === 'loading' || state === 'redirecting') {
    return (
      <Center h="100vh">
        <Loader size="xl" />
      </Center>
    )
  }

  return (
    <Center h="100vh">
      <Stack align="center" gap="xl" w={360}>
        <Stack align="center" gap="xs">
          <Title order={1}>Harpocrate</Title>
          <Text c="dimmed" size="lg">
            {t('unlock.subtitle')}
          </Text>
        </Stack>

        {loginError && (
          <Text c="red" size="sm">
            {loginError}
          </Text>
        )}

        {localLoginAvailable ? (
          <Tabs defaultValue="keycloak" w="100%">
            <Tabs.List>
              <Tabs.Tab value="keycloak">Keycloak</Tabs.Tab>
              <Tabs.Tab value="local">{t('auth.local_login.tab')}</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="keycloak" pt="md">
              <Stack align="center">
                <Button size="lg" fullWidth onClick={() => void startLogin()}>
                  {t('auth.loginWithKeycloak')}
                </Button>
              </Stack>
            </Tabs.Panel>

            <Tabs.Panel value="local" pt="md">
              <form onSubmit={(e) => void handleLocalSubmit(e)}>
                <Stack gap="sm">
                  <TextInput
                    label={t('auth.local_login.username')}
                    value={localUsername}
                    onChange={(e) => setLocalUsername(e.currentTarget.value)}
                    required
                    data-testid="local-username"
                  />
                  <PasswordInput
                    label={t('auth.local_login.password')}
                    value={localPassword}
                    onChange={(e) => setLocalPassword(e.currentTarget.value)}
                    required
                    data-testid="local-password"
                  />
                  {localError && (
                    <Text c="red" size="sm" data-testid="local-error">
                      {localError}
                    </Text>
                  )}
                  <Button
                    type="submit"
                    fullWidth
                    loading={localSubmitting}
                    data-testid="local-submit"
                  >
                    {t('auth.local_login.submit')}
                  </Button>
                </Stack>
              </form>
            </Tabs.Panel>
          </Tabs>
        ) : (
          <Button size="lg" onClick={() => void startLogin()}>
            {t('auth.loginWithKeycloak')}
          </Button>
        )}
      </Stack>
    </Center>
  )
}
