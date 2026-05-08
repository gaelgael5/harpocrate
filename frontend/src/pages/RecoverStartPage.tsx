/**
 * RecoverStartPage — démarre une session de réinitialisation de passphrase
 * (LOT_57). L'utilisateur saisit son email, on POST /v1/auth/recovery/start,
 * et on affiche un message de confirmation invariant (anti-énumération :
 * on ne dit JAMAIS si l'email correspond ou non à un compte).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Center,
  Stack,
  Title,
  Text,
  TextInput,
  Button,
  Alert,
  Box,
  Anchor,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'

type State = 'form' | 'submitting' | 'sent'

export function RecoverStartPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [state, setState] = useState<State>('form')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    if (!email.trim()) return
    setState('submitting')
    setError(null)
    try {
      const r = await fetch('/v1/auth/recovery/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      })
      // Anti-énumération : on affiche toujours le même message tant que l'API
      // n'a pas explicitement levé une erreur de validation côté Pydantic.
      if (r.status === 422 || r.status === 400) {
        setError(t('recover.invalidEmail'))
        setState('form')
        return
      }
      // 202 ou autres → on assume "OK, regardez vos emails".
      setState('sent')
    } catch {
      setError(t('errors.serverError'))
      setState('form')
    }
  }

  if (state === 'sent') {
    return (
      <Center h="100vh" style={{ background: 'var(--mantine-color-body)' }}>
        <Stack w={380} gap="md" align="center">
          <Title order={3}>{t('recover.startSentTitle')}</Title>
          <Text size="sm" ta="center" c="dimmed">
            {t('recover.startSentBody')}
          </Text>
          <Anchor onClick={() => navigate('/login')} style={{ cursor: 'pointer' }}>
            {t('recover.backToLogin')}
          </Anchor>
        </Stack>
      </Center>
    )
  }

  return (
    <Center h="100vh" style={{ background: 'var(--mantine-color-body)' }}>
      <Stack w={380} gap="md">
        <Box ta="center" mb="md">
          <Title order={3}>{t('recover.startTitle')}</Title>
          <Text size="sm" c="dimmed" mt="xs">
            {t('recover.startSubtitle')}
          </Text>
        </Box>

        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}

        <TextInput
          label={t('recover.emailLabel')}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handleSubmit()
          }}
          autoFocus
          disabled={state === 'submitting'}
          data-testid="recover-email"
        />

        <Button
          fullWidth
          color="brand"
          onClick={() => void handleSubmit()}
          loading={state === 'submitting'}
          disabled={!email.trim()}
        >
          {t('recover.submit')}
        </Button>

        <Anchor onClick={() => navigate('/login')} ta="center" style={{ cursor: 'pointer' }}>
          {t('recover.backToLogin')}
        </Anchor>
      </Stack>
    </Center>
  )
}
