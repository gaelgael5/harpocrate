/**
 * Wallet detail page — lists secrets, shows tabs for grants and settings.
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Button,
  Text,
  Group,
  Badge,
  Tabs,
  Card,
  Loader,
  Center,
  Alert,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '@/lib/api-client'
import { exportWallet } from '@/lib/exportImportApi'
import { WalletItemSchema } from '@/schemas/wallets'
import { SecretListResponseSchema, type SecretListItem } from '@/schemas/secrets'

function SecretRow({ secret, walletId }: { secret: SecretListItem; walletId: string }) {
  const navigate = useNavigate()

  return (
    <Card
      withBorder
      padding="sm"
      style={{ cursor: 'pointer' }}
      onClick={() => navigate(`/wallets/${walletId}/secrets/${secret.name}`)}
    >
      <Group justify="space-between">
        <Group gap="sm">
          <Text fw={500} ff="monospace">
            {secret.name}
          </Text>
          {secret.is_placeholder ? (
            <Badge color="orange" size="sm">placeholder</Badge>
          ) : (
            <Badge color="green" size="sm">v{secret.generation_version}</Badge>
          )}
        </Group>
        <Group gap="xs">
          {secret.tags.map((tag) => (
            <Badge key={tag} variant="light" size="xs">
              {tag}
            </Badge>
          ))}
        </Group>
      </Group>
      {secret.description && (
        <Text c="dimmed" size="sm" mt="xs">
          {secret.description}
        </Text>
      )}
    </Card>
  )
}

export function WalletDetailPage() {
  const { t } = useTranslation()
  const { walletId } = useParams<{ walletId: string }>()
  const navigate = useNavigate()

  async function handleExport() {
    if (!walletId) return
    try {
      const data = await exportWallet(walletId)
      const json = JSON.stringify(data, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const safeName = (data.wallet.name ?? 'wallet').replace(/[^A-Za-z0-9_-]/g, '_')
      const date = new Date().toISOString().slice(0, 10)
      a.download = `vault-${safeName}-${date}.json`
      a.click()
      URL.revokeObjectURL(url)
      notifications.show({ color: 'green', message: t('wallets.export.success') })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    }
  }

  const { data: wallet, isLoading: walletLoading, error: walletError } = useQuery({
    queryKey: ['wallet', walletId],
    queryFn: async () => {
      const raw = await api.get<unknown>(`/wallets/${walletId ?? ''}`)
      return WalletItemSchema.parse(raw)
    },
    enabled: !!walletId,
  })

  const { data: secrets, isLoading: secretsLoading } = useQuery({
    queryKey: ['secrets', walletId],
    queryFn: async () => {
      const raw = await api.get<unknown>(`/wallets/${walletId ?? ''}/secrets`)
      return SecretListResponseSchema.parse(raw)
    },
    enabled: !!walletId,
  })

  if (walletLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }

  if (walletError) {
    const msg = walletError instanceof ApiError ? walletError.message : t('errors.serverError')
    return <Alert color="red">{msg}</Alert>
  }

  if (!wallet) return null

  return (
    <Stack>
      <Group justify="space-between">
        <Stack gap={2}>
          <Title order={2}>{wallet.name}</Title>
          {wallet.description && (
            <Text c="dimmed" size="sm">
              {wallet.description}
            </Text>
          )}
        </Stack>
        <Group>
          <Button variant="outline" onClick={() => void handleExport()}>
            {t('wallets.export.button')}
          </Button>
          <Button
            variant="outline"
            onClick={() => navigate(`/wallets/${walletId ?? ''}/grants`)}
          >
            {t('grants.title')}
          </Button>
          <Button
            variant="outline"
            onClick={() => navigate(`/wallets/${walletId ?? ''}/api-keys`)}
          >
            {t('apiKeys.apiKeysButton')}
          </Button>
          <Button onClick={() => navigate(`/wallets/${walletId ?? ''}/secrets/new`)}>
            {t('secrets.create')}
          </Button>
        </Group>
      </Group>

      <Group gap="xs">
        {wallet.tags.map((tag) => (
          <Badge key={tag} variant="light">
            {tag}
          </Badge>
        ))}
      </Group>

      <Tabs defaultValue="secrets">
        <Tabs.List>
          <Tabs.Tab value="secrets">{t('secrets.title')}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="secrets" pt="md">
          {secretsLoading ? (
            <Center py="xl">
              <Loader size="sm" />
            </Center>
          ) : secrets?.secrets.length === 0 ? (
            <Text c="dimmed">{t('secrets.noSecrets')}</Text>
          ) : (
            <Stack gap="xs">
              {secrets?.secrets.map((s) => (
                <SecretRow key={s.id} secret={s} walletId={walletId ?? ''} />
              ))}
            </Stack>
          )}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
