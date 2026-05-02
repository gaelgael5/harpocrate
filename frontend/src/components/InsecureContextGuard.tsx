/**
 * Bloque l'app si on est dans un contexte non-securise (HTTP plain hors localhost).
 * Sans secure context, window.crypto.subtle est undefined et toute la crypto
 * navigateur (RSA, AES-GCM, Argon2 via WebCrypto) plante avec
 * "Cannot read properties of undefined (reading 'generateKey')".
 *
 * Affiche un ecran d'avertissement avec un bouton qui bascule vers HTTPS
 * (port 8443 par convention si on est sur 8080, sinon meme port en https).
 */
import { useTranslation } from 'react-i18next'
import { Alert, Button, Code, Container, Stack, Text, Title } from '@mantine/core'

function isInsecureContext(): boolean {
  if (typeof window === 'undefined') return false
  if (window.isSecureContext) return false
  // localhost / 127.0.0.1 / ::1 sont consideres secure meme en HTTP
  const local = ['localhost', '127.0.0.1', '::1', '[::1]']
  if (local.includes(window.location.hostname)) return false
  return window.location.protocol === 'http:'
}

function buildHttpsUrl(): string {
  const { hostname, port, pathname, search } = window.location
  // Convention: 8080 -> 8443, 80 ou vide -> 443, sinon meme port en https
  let httpsPort = port
  if (port === '8080') httpsPort = '8443'
  else if (!port || port === '80') httpsPort = '443'
  const portPart = httpsPort && httpsPort !== '443' ? `:${httpsPort}` : ''
  return `https://${hostname}${portPart}${pathname}${search}`
}

interface Props {
  children: React.ReactNode
}

export function InsecureContextGuard({ children }: Props) {
  const { t } = useTranslation()

  if (!isInsecureContext()) return <>{children}</>

  const httpsUrl = buildHttpsUrl()

  return (
    <Container size="sm" py="xl">
      <Stack gap="md">
        <Title order={2} c="red">
          {t('insecureContext.title')}
        </Title>

        <Alert color="red" title={t('insecureContext.crypto_disabled')}>
          {t('insecureContext.message')}
        </Alert>

        <Text size="sm">{t('insecureContext.why')}</Text>

        <Stack gap="xs">
          <Text size="sm" fw={600}>
            {t('insecureContext.solution')}
          </Text>
          <Button component="a" href={httpsUrl} size="md" color="blue">
            {t('insecureContext.switch_button')}
          </Button>
          <Code block>{httpsUrl}</Code>
        </Stack>

        <Text size="xs" c="dimmed">
          {t('insecureContext.cert_warning')}
        </Text>
      </Stack>
    </Container>
  )
}
