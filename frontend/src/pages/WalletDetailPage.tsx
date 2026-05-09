/**
 * Wallet detail page — lists secrets with virtual directory navigation.
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  Breadcrumbs,
  Anchor,
  SimpleGrid,
  ActionIcon,
  Tooltip,
} from '@mantine/core'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'

import { api, ApiError } from '@/lib/api-client'
import { invalidateWalletQueries } from '@/lib/walletQueries'
import { fetchWalletEnvironments } from '@/lib/walletEnvironmentsApi'
import { FolderTree } from '@/components/FolderTree'
import { exportWallet } from '@/lib/exportImportApi'
import { WalletItemSchema } from '@/schemas/wallets'
import { type SecretListItem } from '@/schemas/secrets'
import { useSessionStore } from '@/stores/session'

// ─── Schemas ─────────────────────────────────────────────────────────────────

const FolderSchema = z.object({
  name: z.string(),
  full_path: z.string(),
  secrets_count: z.number(),
  subfolders_count: z.number(),
})

const TreeDataSchema = z.object({
  path: z.string(),
  secrets_at_this_level_count: z.number(),
  folders: z.array(FolderSchema),
})

const PathSecretSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  is_placeholder: z.boolean(),
  generation_version: z.number(),
  tags: z.array(z.string()),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
})

const PathSecretsResponseSchema = z.object({
  secrets: z.array(PathSecretSchema),
  next_cursor: z.string().nullable(),
})

type Folder = z.infer<typeof FolderSchema>
type PathSecret = z.infer<typeof PathSecretSchema>

// ─── Sub-components ───────────────────────────────────────────────────────────

function PathBreadcrumb({
  path,
  onNavigate,
}: {
  path: string
  onNavigate: (p: string) => void
}) {
  const { t } = useTranslation()
  const segments = path === '/' ? [] : path.split('/').filter(Boolean)

  return (
    <Breadcrumbs>
      <Anchor onClick={() => onNavigate('/')} style={{ cursor: 'pointer' }}>
        {t('secrets.paths.root')}
      </Anchor>
      {segments.map((seg, i) => {
        const fullPath = '/' + segments.slice(0, i + 1).join('/') + '/'
        const isLast = i === segments.length - 1
        return isLast ? (
          <Text key={fullPath}>{seg}</Text>
        ) : (
          <Anchor key={fullPath} onClick={() => onNavigate(fullPath)} style={{ cursor: 'pointer' }}>
            {seg}
          </Anchor>
        )
      })}
    </Breadcrumbs>
  )
}

function FolderCard({
  folder,
  onClick,
  onDelete,
}: {
  folder: Folder
  onClick: () => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" style={{ cursor: 'pointer', flex: 1 }} onClick={onClick}>
          <Text>📁</Text>
          <Stack gap={0}>
            <Text size="sm" fw={500}>{folder.name}</Text>
            <Text size="xs" c="dimmed">
              {t('secrets.paths.secretsCount', { count: folder.secrets_count })}
            </Text>
          </Stack>
        </Group>
        <Tooltip label={t('secrets.paths.deleteFolder')}>
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            aria-label="delete-folder"
          >
            🗑
          </ActionIcon>
        </Tooltip>
      </Group>
    </Card>
  )
}

function SecretCard({ secret, walletId }: { secret: SecretListItem | PathSecret; walletId: string }) {
  const navigate = useNavigate()

  return (
    <Card
      withBorder
      padding="sm"
      style={{ cursor: 'pointer' }}
      onClick={() => navigate(`/wallets/${walletId}/secrets/${secret.id}`)}
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

// ─── Page ────────────────────────────────────────────────────────────────────

export function WalletDetailPage() {
  const { t } = useTranslation()
  const { walletId } = useParams<{ walletId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const currentUser = useSessionStore((s) => s.user)
  const [currentPath, setCurrentPath] = useState('/')

  const deleteMutation = useMutation({
    mutationFn: () => api.delete(`/wallets/${walletId ?? ''}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['wallets'] })
      void queryClient.invalidateQueries({ queryKey: ['wallet', walletId] })
      notifications.show({ color: 'green', message: t('wallets.deleteSuccess') })
      navigate('/wallets')
    },
    onError: () => notifications.show({ color: 'red', message: t('wallets.deleteError') }),
  })

  const restoreMutation = useMutation({
    mutationFn: () => api.post(`/wallets/${walletId ?? ''}/restore`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['wallets'] })
      void queryClient.invalidateQueries({ queryKey: ['wallet', walletId] })
      notifications.show({ color: 'green', message: t('wallets.restoreSuccess') })
    },
    onError: () => notifications.show({ color: 'red', message: t('wallets.restoreError') }),
  })

  const deleteFolderMutation = useMutation({
    mutationFn: async (folderPath: string) => {
      // 1. Compter les secrets pour la confirmation
      const countRaw = await api.get<unknown>(
        `/wallets/${walletId ?? ''}/secrets/by-path/count?path=${encodeURIComponent(folderPath)}`,
      )
      const count = (countRaw as { count: number }).count
      return { folderPath, count }
    },
    onSuccess: ({ folderPath, count }) => {
      modals.openConfirmModal({
        title: t('secrets.paths.deleteFolderTitle'),
        children: (
          <Text size="sm">
            {t('secrets.paths.deleteFolderConfirm', { path: folderPath, count })}
          </Text>
        ),
        labels: { confirm: t('secrets.paths.deleteFolder'), cancel: t('common.cancel') },
        confirmProps: { color: 'red' },
        onConfirm: async () => {
          try {
            const r = await api.delete<{ deleted: number }>(
              `/wallets/${walletId ?? ''}/secrets/by-path?path=${encodeURIComponent(folderPath)}`,
            )
            notifications.show({
              color: 'green',
              message: t('secrets.paths.deleteFolderSuccess', { count: r.deleted }),
            })
            if (walletId) await invalidateWalletQueries(queryClient, walletId)
          } catch (err) {
            const msg = err instanceof ApiError ? err.message : String(err)
            notifications.show({ color: 'red', title: t('common.error'), message: msg })
          }
        },
      })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  function handleDelete() {
    modals.openConfirmModal({
      title: t('wallets.deleteConfirmTitle'),
      children: <Text size="sm">{t('wallets.deleteConfirmDesc')}</Text>,
      labels: { confirm: t('wallets.delete'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: () => deleteMutation.mutate(),
    })
  }

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

  // LOT_58 : on charge la liste des envs pour résoudre wallet.environment_id
  // → name (le backend ne renvoie que l'id sur le wallet pour rester atomique).
  const { data: environments } = useQuery({
    queryKey: ['wallet-environments'],
    queryFn: fetchWalletEnvironments,
  })

  const { data: treeData, isLoading: treeLoading } = useQuery({
    queryKey: ['wallet-tree', walletId, currentPath],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId ?? ''}/tree?path=${encodeURIComponent(currentPath)}`
      )
      return TreeDataSchema.parse(raw)
    },
    enabled: !!walletId,
  })

  const { data: pathSecrets, isLoading: pathSecretsLoading } = useQuery({
    queryKey: ['wallet-secrets-path', walletId, currentPath],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId ?? ''}/secrets?path=${encodeURIComponent(currentPath)}`
      )
      return PathSecretsResponseSchema.parse(raw)
    },
    enabled: !!walletId,
  })

  const secretsLoading = treeLoading || pathSecretsLoading

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

  const prefixPath = currentPath === '/' ? '' : currentPath
  const isOwner = wallet.owner_user_id === currentUser?.id
  const isDeleted = !!wallet.deleted_at
  const purgeAt = wallet.deleted_at
    ? new Date(new Date(wallet.deleted_at).getTime() + 24 * 60 * 60 * 1000)
    : null

  return (
    <Stack>
      {/* Bannière corbeille */}
      {isDeleted && (
        <Alert color="red" variant="light" title={t('wallets.pendingDeletion')}>
          <Group justify="space-between" align="center">
            <Text size="sm">
              {purgeAt
                ? t('wallets.purgeAt', { date: purgeAt.toLocaleString() })
                : t('wallets.deletedAt', { date: wallet.deleted_at ? new Date(wallet.deleted_at).toLocaleString() : '' })}
            </Text>
            {isOwner && (
              <Button
                size="xs"
                color="brand"
                loading={restoreMutation.isPending}
                onClick={() => restoreMutation.mutate()}
              >
                {t('wallets.restore')}
              </Button>
            )}
          </Group>
        </Alert>
      )}

      <Group justify="space-between">
        <Stack gap={2}>
          <Group gap="xs" align="baseline">
            <Title order={2}>{wallet.name}</Title>
            {/* LOT_58 : nom de l'env affiché en petit à côté du titre,
                masqué si NULL (= "None" virtuel). */}
            {wallet.environment_id && (
              <Text size="xs" c="dimmed" style={{ fontStyle: 'italic' }}>
                {environments?.find((e) => e.id === wallet.environment_id)?.name ?? ''}
              </Text>
            )}
          </Group>
          {wallet.description && (
            <Text c="dimmed" size="sm">
              {wallet.description}
            </Text>
          )}
          {/* Breadcrumb du chemin courant — affiché en permanence sous le
              titre du coffre pour permettre à l'utilisateur de remonter
              dans l'arborescence en un clic, sans avoir à dérouler l'arbre
              ou scroller jusqu'au panneau central. */}
          <PathBreadcrumb path={currentPath} onNavigate={setCurrentPath} />
        </Stack>
        <Group>
          <Button
            variant="subtle"
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ['wallet', walletId] })
              void queryClient.invalidateQueries({ queryKey: ['wallet-tree', walletId] })
              void queryClient.invalidateQueries({ queryKey: ['wallet-secrets-path', walletId] })
            }}
            title={t('wallets.refreshHint')}
          >
            ↻ {t('wallets.refresh')}
          </Button>
          <Button variant="outline" onClick={() => void handleExport()}>
            {t('wallets.export.button')}
          </Button>
          {!isDeleted && (
            <>
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
              <Button
                onClick={() =>
                  navigate(`/wallets/${walletId ?? ''}/secrets/new`, {
                    state: { prefixPath },
                  })
                }
              >
                {t('secrets.create')}
              </Button>
              {isOwner && (
                <Button
                  color="red"
                  variant="light"
                  loading={deleteMutation.isPending}
                  onClick={handleDelete}
                >
                  {t('wallets.delete')}
                </Button>
              )}
            </>
          )}
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
          <Group align="flex-start" wrap="nowrap" gap="md">
            {/* Sidebar arbre */}
            <Stack
              gap="xs"
              style={{
                borderRight: '1px solid var(--mantine-color-gray-3)',
                paddingRight: 12,
                position: 'sticky',
                top: 12,
                maxHeight: 'calc(100vh - 200px)',
                overflowY: 'auto',
              }}
            >
              <Text fw={600} size="sm">
                {t('secrets.paths.folders')}
              </Text>
              {walletId && (
                <FolderTree
                  walletId={walletId}
                  currentPath={currentPath}
                  onSelect={setCurrentPath}
                />
              )}
            </Stack>

            {/* Contenu central */}
            <Stack gap="md" style={{ flex: 1 }}>
              {secretsLoading ? (
                <Center py="xl">
                  <Loader size="sm" />
                </Center>
              ) : (
                <>
                  {/* Folder grid */}
                  {(treeData?.folders.length ?? 0) > 0 && (
                    <Stack gap="xs">
                      <Text fw={600} size="sm">
                        {t('secrets.paths.folders')}
                      </Text>
                      <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }}>
                        {treeData?.folders.map((folder) => (
                          <FolderCard
                            key={folder.full_path}
                            folder={folder}
                            onClick={() => setCurrentPath(folder.full_path)}
                            onDelete={() => deleteFolderMutation.mutate(folder.full_path)}
                          />
                        ))}
                      </SimpleGrid>
                    </Stack>
                  )}

                  {/* Secrets at current level */}
                  {(pathSecrets?.secrets.length ?? 0) === 0 &&
                  (treeData?.folders.length ?? 0) === 0 ? (
                    <Text c="dimmed">{t('secrets.noSecrets')}</Text>
                  ) : (
                    (pathSecrets?.secrets.length ?? 0) > 0 && (
                      <Stack gap="xs">
                        <Text fw={600} size="sm">
                          {t('secrets.paths.secretsHere')}
                        </Text>
                        {pathSecrets?.secrets.map((s) => (
                          <SecretCard key={s.id} secret={s} walletId={walletId ?? ''} />
                        ))}
                      </Stack>
                    )
                  )}
                </>
              )}
            </Stack>
          </Group>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
