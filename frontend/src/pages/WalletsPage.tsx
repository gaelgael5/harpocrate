/**
 * Wallet list page — shows all wallets accessible to the current user.
 */
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Button,
  Card,
  Text,
  Group,
  Badge,
  Loader,
  Center,
  Alert,
} from '@mantine/core'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '@/lib/api-client'
import { WalletListResponseSchema, type WalletItem } from '@/schemas/wallets'
import { hasPermission, PERM_READ } from '@/schemas/grants'

function WalletCard({ wallet }: { wallet: WalletItem }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <Card
      withBorder
      padding="md"
      style={{ cursor: 'pointer' }}
      onClick={() => navigate(`/wallets/${wallet.id}`)}
    >
      <Group justify="space-between" mb="xs">
        <Text fw={600}>{wallet.name}</Text>
        <Group gap="xs">
          {!wallet.is_owner && (
            <Badge color="blue" variant="outline" size="sm">
              {t('wallets.shared')}
            </Badge>
          )}
          {wallet.tags.map((tag) => (
            <Badge key={tag} variant="light" size="sm">
              {tag}
            </Badge>
          ))}
        </Group>
      </Group>

      {wallet.description && (
        <Text c="dimmed" size="sm" mb="xs">
          {wallet.description}
        </Text>
      )}

      <Group gap="md">
        <Text size="xs" c="dimmed">
          {t('wallets.secretsCount', { count: wallet.valued_secrets_count })}
        </Text>
        {wallet.placeholder_secrets_count > 0 && (
          <Text size="xs" c="orange">
            {t('wallets.placeholdersCount', {
              count: wallet.placeholder_secrets_count,
            })}
          </Text>
        )}
        {hasPermission(wallet.my_permissions, PERM_READ) && (
          <Badge size="xs" color="green" variant="dot">
            {t('grants.perm_read')}
          </Badge>
        )}
      </Group>
    </Card>
  )
}

export function WalletsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const { data, isLoading, error } = useQuery({
    queryKey: ['wallets'],
    queryFn: async () => {
      const raw = await api.get<unknown>('/wallets')
      return WalletListResponseSchema.parse(raw)
    },
  })

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }

  if (error) {
    const msg =
      error instanceof ApiError ? error.message : t('errors.serverError')
    return <Alert color="red">{msg}</Alert>
  }

  const wallets = data?.wallets ?? []

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t('wallets.title')}</Title>
        <Group>
          <Button variant="outline" onClick={() => navigate('/wallets/import')}>
            {t('wallets.import.button')}
          </Button>
          <Button onClick={() => navigate('/wallets/new')}>
            {t('wallets.create')}
          </Button>
        </Group>
      </Group>

      {wallets.length === 0 ? (
        <Text c="dimmed">{t('wallets.noWallets')}</Text>
      ) : (
        wallets.map((w) => <WalletCard key={w.id} wallet={w} />)
      )}
    </Stack>
  )
}
