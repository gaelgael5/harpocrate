/**
 * AdminReplicationPage — état + bascule de la stratégie de réplication (LOT_20).
 *
 * Affiche :
 * - la stratégie active + son état temps réel (interrogation Patroni quand applicable)
 * - la liste des stratégies disponibles
 * - bouton "Activer" pour basculer vers une autre stratégie
 *
 * Les stratégies futures (harpocrate_sync, s3_wal) sont listées mais désactivées
 * tant que leur backend n'est pas implémenté.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Text,
  Card,
  Group,
  Badge,
  Loader,
  Center,
  Alert,
  Table,
  Switch,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import {
  fetchReplicationStrategies,
  fetchReplicationStatus,
  activateReplicationStrategy,
  deactivateReplicationStrategy,
} from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'
import { StreamingNodesPanel } from '@/components/StreamingNodesPanel'
import { PostgresInfoPanel } from '@/components/PostgresInfoPanel'

function StatusBadge({ status }: { status: string }) {
  const color = status === 'ok' ? 'green' : status === 'degraded' ? 'orange' : 'red'
  return <Badge color={color}>{status}</Badge>
}

function NodesTable({ nodes }: { nodes: Array<Record<string, unknown>> }) {
  const { t } = useTranslation()
  if (nodes.length === 0) return null
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={5}>{t('admin.replication.nodes')}</Title>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>URL</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th>Timeline</Table.Th>
              <Table.Th>Lag</Table.Th>
              <Table.Th>Healthy</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {nodes.map((n, i) => (
              <Table.Tr key={i}>
                <Table.Td>
                  <Text size="xs" ff="monospace">
                    {String(n.url ?? '')}
                  </Text>
                </Table.Td>
                <Table.Td>{String(n.role ?? '—')}</Table.Td>
                <Table.Td>{String(n.state ?? '—')}</Table.Td>
                <Table.Td>{String(n.timeline ?? '—')}</Table.Td>
                <Table.Td>{n.lag != null ? String(n.lag) : '—'}</Table.Td>
                <Table.Td>
                  {n.healthy ? (
                    <Badge color="green">✓</Badge>
                  ) : (
                    <Badge color="red">✗</Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  )
}

export function AdminReplicationPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const statusQuery = useQuery({
    queryKey: ['admin-replication-status'],
    queryFn: fetchReplicationStatus,
    refetchInterval: 15_000,
  })

  const strategiesQuery = useQuery({
    queryKey: ['admin-replication-strategies'],
    queryFn: fetchReplicationStrategies,
  })

  // Multi-actives autorisé : Switch indépendant par stratégie. activate/
  // deactivate sont deux endpoints distincts mais on les unifie ici pour
  // simplifier le composant (le résultat n'est pas consommé, juste le
  // succès/erreur compte).
  const toggleMut = useMutation({
    mutationFn: async (args: { id: string; enable: boolean }) => {
      if (args.enable) {
        await activateReplicationStrategy(args.id)
      } else {
        await deactivateReplicationStrategy(args.id)
      }
    },
    onSuccess: (_data, args) => {
      notifications.show({
        color: 'green',
        message: args.enable
          ? t('admin.replication.activateSuccess')
          : t('admin.replication.deactivateSuccess'),
      })
      void qc.invalidateQueries({ queryKey: ['admin-replication-status'] })
      void qc.invalidateQueries({ queryKey: ['admin-replication-strategies'] })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  return (
    <Stack>
      <Title order={2}>{t('admin.replication.title')}</Title>
      <Text c="dimmed" size="sm">
        {t('admin.replication.subtitle')}
      </Text>

      {/* État temps réel */}
      {statusQuery.isLoading && (
        <Center py="md">
          <Loader />
        </Center>
      )}
      {statusQuery.error && (
        <Alert color="red">
          {statusQuery.error instanceof ApiError
            ? statusQuery.error.message
            : t('common.error')}
        </Alert>
      )}
      {statusQuery.data && (
        <Card withBorder>
          <Stack>
            <Group justify="space-between">
              <Title order={4}>{t('admin.replication.activeStrategy')}</Title>
              {statusQuery.data.live && (
                <StatusBadge status={statusQuery.data.live.status} />
              )}
            </Group>
            {statusQuery.data.strategy ? (
              <>
                <Text>
                  <strong>{statusQuery.data.strategy.label}</strong>{' '}
                  <Text span c="dimmed" size="sm">
                    ({statusQuery.data.strategy.type})
                  </Text>
                </Text>
                {statusQuery.data.strategy.description && (
                  <Text size="sm" c="dimmed">
                    {statusQuery.data.strategy.description}
                  </Text>
                )}
                {statusQuery.data.live?.nodes && (
                  <NodesTable nodes={statusQuery.data.live.nodes} />
                )}
              </>
            ) : (
              <Alert color="orange">{t('admin.replication.noActiveStrategy')}</Alert>
            )}
          </Stack>
        </Card>
      )}

      {/* Liste des stratégies — multi-actives, switch indépendant par strat */}
      {strategiesQuery.data && (
        <Card withBorder>
          <Stack>
            <Title order={4}>{t('admin.replication.availableStrategies')}</Title>
            <Text size="sm" c="dimmed">
              {t('admin.replication.multiActiveHint')}
            </Text>
            <Stack gap="md">
              {strategiesQuery.data.strategies.map((s) => (
                <Card key={s.id} withBorder padding="sm">
                  <Group justify="space-between">
                    <Stack gap={4}>
                      <Group gap="xs">
                        <Text fw={600}>{s.label}</Text>
                        <Badge variant="light">{s.type}</Badge>
                        {!s.enabled && (
                          <Badge color="gray">{t('admin.replication.disabled')}</Badge>
                        )}
                      </Group>
                      {s.description && (
                        <Text size="sm" c="dimmed">
                          {s.description}
                        </Text>
                      )}
                    </Stack>
                    <Switch
                      label={
                        s.is_active
                          ? t('admin.replication.active')
                          : t('admin.replication.inactive')
                      }
                      checked={s.is_active}
                      disabled={!s.enabled || toggleMut.isPending}
                      onChange={(e) =>
                        toggleMut.mutate({
                          id: s.id,
                          enable: e.currentTarget.checked,
                        })
                      }
                    />
                  </Group>
                </Card>
              ))}
            </Stack>
          </Stack>
        </Card>
      )}

      {/* Postgres info — paramètres de l'instance courante (master), à
          copier côté standby pour matcher la config de réplication. */}
      <PostgresInfoPanel />

      {/* Streaming async — gestion des standby */}
      <StreamingNodesPanel />
    </Stack>
  )
}
