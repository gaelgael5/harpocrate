/**
 * OAuth2 callback page — processes the OIDC redirect and routes to /login.
 */
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Center, Loader, Text, Stack } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { handleCallback } from '@/lib/oidc'

export function OAuthCallbackPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false

    async function process() {
      try {
        await handleCallback()
        if (!cancelled) {
          // Redirect to /login which will re-probe /me and route appropriately
          navigate('/login', { replace: true })
        }
      } catch (err) {
        if (!cancelled) {
          console.error('OIDC callback error:', err)
          navigate('/login', { replace: true })
        }
      }
    }

    void process()
    return () => {
      cancelled = true
    }
  }, [navigate])

  return (
    <Center h="100vh">
      <Stack align="center">
        <Loader size="xl" />
        <Text>{t('auth.callbackProcessing')}</Text>
      </Stack>
    </Center>
  )
}