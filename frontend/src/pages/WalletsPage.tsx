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
  SimpleGrid,
  Box,
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
      padding="lg"
      style={{
        cursor: 'pointer',
        borderColor: '#dedad2',
        transition: 'box-shadow 0.15s, border-color 0.15s',
      }}
      onClick={() => navigate(`/wallets/${wallet.id}`)}
      onMouseEnter={(e) => {
        const el = e.currentTarget
        el.style.boxShadow = '0 4px 16px rgba(10,10,10,0.09)'
        el.style.borderColor = '#1e40af'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget
        el.style.boxShadow = ''
        el.style.borderColor = '#dedad2'
      }}
    >
      {/* Blue top accent bar */}
      <Box
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: '#1e40af',
          borderRadius: '4px 4px 0 0',
          opacity: 0.7,
        }}
      />

      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Text
            fw={600}
            size="sm"
            style={{ letterSpacing: '0.01em', color: '#0a0a0a' }}
          >
            {wallet.name}
          </Text>
          <Group gap={4}>
            {!wallet.is_owner && (
              <Badge color="brand" variant="light" size="xs">
                {t('wallets.shared')}
              </Badge>
            )}
            {wallet.tags.map((tag) => (
              <Badge key={tag} variant="outline" size="xs" color="gray">
                {tag}
              </Badge>
            ))}
          </Group>
        </Group>

        {wallet.description && (
          <Text c="dimmed" size="xs" lineClamp={2}>
            {wallet.description}
          </Text>
        )}

        <Group gap="lg" mt={4}>
          <Text
            size="xs"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: 'rgba(10,10,10,0.45)' }}
          >
            {t('wallets.secretsCount', { count: wallet.valued_secrets_count })}
          </Text>
          {wallet.placeholder_secrets_count > 0 && (
            <Text size="xs" c="orange">
              {t('wallets.placeholdersCount', { count: wallet.placeholder_secrets_count })}
            </Text>
          )}
          {hasPermission(wallet.my_permissions, PERM_READ) && (
            <Badge size="xs" color="green" variant="dot">
              {t('grants.perm_read')}
            </Badge>
          )}
        </Group>
      </Stack>
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
    return <Center py="xl"><Loader color="brand" /></Center>
  }

  if (error) {
    const msg = error instanceof ApiError ? error.message : t('errors.serverError')
    return <Alert color="red">{msg}</Alert>
  }

  const wallets = data?.wallets ?? []

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={2}>{t('wallets.title')}</Title>
        <Group gap="xs">
          <Button variant="default" onClick={() => navigate('/wallets/import')}>
            {t('wallets.import.button')}
          </Button>
          <Button color="brand" onClick={() => navigate('/wallets/new')}>
            {t('wallets.create')}
          </Button>
        </Group>
      </Group>

      {wallets.length === 0 ? (
        <Text c="dimmed">{t('wallets.noWallets')}</Text>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {wallets.map((w) => <WalletCard key={w.id} wallet={w} />)}
        </SimpleGrid>
      )}
    </Stack>
  )
}
