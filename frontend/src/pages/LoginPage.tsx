/**
 * Login page — checks /v1/me and routes appropriately:
 * - 401 (no OIDC session): show "Login with Keycloak" button
 * - 404 first_login: redirect to /first-login
 * - 200: redirect to /unlock (or / if already unlocked)
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Center, Stack, Title, Text, Button, Loader } from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '@/lib/api-client'
import { startLogin, getUserManager } from '@/lib/oidc'
import { MeResponseSchema } from '@/schemas/auth'
import { useSessionStore } from '@/stores/session'
import { useCryptoStore } from '@/stores/crypto'

type State = 'loading' | 'show-login' | 'redirecting'

export function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const setUser = useSessionStore((s) => s.setUser)
  const isUnlocked = useCryptoStore((s) => s.isUnlocked)
  const [state, setState] = useState<State>('loading')
  const [loginError, setLoginError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function probe() {
      try {
        // Check if we have a valid OIDC session first
        const mgr = getUserManager()
        const user = await mgr.getUser()

        if (!user || user.expired) {
          if (!cancelled) setState('show-login')
          return
        }

        // We have an OIDC session — check if bootstrapped
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

  if (state === 'loading' || state === 'redirecting') {
    return (
      <Center h="100vh">
        <Loader size="xl" />
      </Center>
    )
  }

  return (
    <Center h="100vh">
      <Stack align="center" gap="xl">
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

        <Button
          size="lg"
          onClick={() => void startLogin()}
        >
          {t('auth.loginWithKeycloak')}
        </Button>
      </Stack>
    </Center>
  )
}
