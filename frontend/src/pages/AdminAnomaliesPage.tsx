/**
 * AdminAnomaliesPage — supervision des anomalies de gouvernance + sessions
 * de recovery (LOT_57). Vue unique pour réagir aux alertes "5+ sessions
 * échouées sur 24h" levées par le service recovery.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Text,
  Table,
  Badge,
  Loader,
  Center,
  Alert,
  Card,
  Group,
  Button,
  Tabs,
  Code,
  Switch,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { notifications } from '@mantine/notifications'

import { api, ApiError } from '@/lib/api-client'

interface AnomalyRow {
  id: number
  user_id: string
  detected_at: string
  severity: 'info' | 'warning' | 'critical'
  anomaly_type: string
  metadata: Record<string, unknown> | null
  acknowledged_at: string | null
  acknowledged_by_user_id: string | null
}

interface NotificationEvent {
  event_type: 'sent' | 'delivery' | 'open' | 'click' | 'failed'
  received_at: string
}

interface RecoverySession {
  id: string
  user_id: string | null
  email: string
  created_at: string
  expires_at: string
  status: 'pending' | 'consumed' | 'failed' | 'expired'
  attempts: number
  ip_started: string | null
  ip_consumed: string | null
  consumed_at: string | null
  novu_transaction_id: string | null
  latest_event: NotificationEvent | null
}

const EVENT_COLOR: Record<NotificationEvent['event_type'], string> = {
  sent: 'blue',
  delivery: 'cyan',
  open: 'green',
  click: 'teal',
  failed: 'red',
}

const SEVERITY_COLOR: Record<AnomalyRow['severity'], string> = {
  info: 'blue',
  warning: 'orange',
  critical: 'red',
}

const STATUS_COLOR: Record<RecoverySession['status'], string> = {
  pending: 'blue',
  consumed: 'green',
  failed: 'red',
  expired: 'gray',
}

export function AdminAnomaliesPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [onlyUnack, setOnlyUnack] = useState(true)

  const anomalies = useQuery({
    queryKey: ['admin-anomalies', onlyUnack],
    queryFn: () =>
      api.get<{ anomalies: AnomalyRow[] }>(
        `/admin/anomalies?only_unacknowledged=${onlyUnack}`,
      ),
  })

  const sessions = useQuery({
    queryKey: ['admin-recovery-sessions'],
    queryFn: () =>
      api.get<{ sessions: RecoverySession[] }>('/admin/recovery-sessions?limit=100'),
  })

  const ackMut = useMutation({
    mutationFn: (id: number) =>
      api.post<{ acknowledged: boolean }>(`/admin/anomalies/${id}/ack`, {}),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.anomalies.ackOk') })
      void qc.invalidateQueries({ queryKey: ['admin-anomalies'] })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  return (
    <Stack>
      <Title order={2}>{t('admin.anomalies.title')}</Title>
      <Text c="dimmed" size="sm">
        {t('admin.anomalies.subtitle')}
      </Text>

      <Tabs defaultValue="anomalies">
        <Tabs.List>
          <Tabs.Tab value="anomalies">{t('admin.anomalies.tabAnomalies')}</Tabs.Tab>
          <Tabs.Tab value="sessions">{t('admin.anomalies.tabSessions')}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="anomalies" pt="md">
          <Card withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Switch
                  label={t('admin.anomalies.onlyUnack')}
                  checked={onlyUnack}
                  onChange={(e) => setOnlyUnack(e.currentTarget.checked)}
                />
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => void qc.invalidateQueries({ queryKey: ['admin-anomalies'] })}
                >
                  {t('common.refresh')}
                </Button>
              </Group>

              {anomalies.isLoading ? (
                <Center py="xl">
                  <Loader />
                </Center>
              ) : anomalies.error ? (
                <Alert color="red">{String(anomalies.error)}</Alert>
              ) : (anomalies.data?.anomalies.length ?? 0) === 0 ? (
                <Text c="dimmed" ta="center" py="md">
                  {t('admin.anomalies.empty')}
                </Text>
              ) : (
                <Table highlightOnHover>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('admin.anomalies.fieldDetectedAt')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.fieldSeverity')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.fieldType')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.fieldUser')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.fieldMetadata')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.fieldAck')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {anomalies.data?.anomalies.map((a) => (
                      <Table.Tr key={a.id}>
                        <Table.Td>
                          <Text size="xs">{new Date(a.detected_at).toLocaleString()}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Badge color={SEVERITY_COLOR[a.severity]} variant="light">
                            {a.severity}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Code>{a.anomaly_type}</Code>
                        </Table.Td>
                        <Table.Td>
                          <Code style={{ fontSize: '0.7rem' }}>{a.user_id.slice(0, 8)}</Code>
                        </Table.Td>
                        <Table.Td>
                          <Code style={{ fontSize: '0.7rem', wordBreak: 'break-all' }}>
                            {JSON.stringify(a.metadata)}
                          </Code>
                        </Table.Td>
                        <Table.Td>
                          {a.acknowledged_at ? (
                            <Badge color="green" variant="outline">
                              {new Date(a.acknowledged_at).toLocaleString()}
                            </Badge>
                          ) : (
                            <Button
                              size="xs"
                              variant="light"
                              loading={ackMut.isPending}
                              onClick={() => ackMut.mutate(a.id)}
                            >
                              {t('admin.anomalies.ack')}
                            </Button>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
            </Stack>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="sessions" pt="md">
          <Card withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Text size="sm" c="dimmed">
                  {t('admin.anomalies.sessionsHint')}
                </Text>
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => void qc.invalidateQueries({ queryKey: ['admin-recovery-sessions'] })}
                >
                  {t('common.refresh')}
                </Button>
              </Group>

              {sessions.isLoading ? (
                <Center py="xl">
                  <Loader />
                </Center>
              ) : sessions.error ? (
                <Alert color="red">{String(sessions.error)}</Alert>
              ) : (sessions.data?.sessions.length ?? 0) === 0 ? (
                <Text c="dimmed" ta="center" py="md">
                  {t('admin.anomalies.sessionsEmpty')}
                </Text>
              ) : (
                <Table highlightOnHover>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('admin.anomalies.sessionsCreated')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.sessionsEmail')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.sessionsStatus')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.sessionsAttempts')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.sessionsIpStarted')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.sessionsLatestEvent')}</Table.Th>
                      <Table.Th>{t('admin.anomalies.sessionsNovuTx')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {sessions.data?.sessions.map((s) => (
                      <Table.Tr key={s.id}>
                        <Table.Td>
                          <Text size="xs">{new Date(s.created_at).toLocaleString()}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">{s.email}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Badge color={STATUS_COLOR[s.status]} variant="light">
                            {s.status}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">{s.attempts}/3</Text>
                        </Table.Td>
                        <Table.Td>
                          <Code style={{ fontSize: '0.7rem' }}>{s.ip_started ?? '—'}</Code>
                        </Table.Td>
                        <Table.Td>
                          {s.latest_event ? (
                            <Badge
                              color={EVENT_COLOR[s.latest_event.event_type]}
                              variant="light"
                              title={new Date(s.latest_event.received_at).toLocaleString()}
                            >
                              {s.latest_event.event_type}
                            </Badge>
                          ) : (
                            <Text size="xs" c="dimmed">
                              —
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Code style={{ fontSize: '0.7rem', wordBreak: 'break-all' }}>
                            {s.novu_transaction_id ?? '—'}
                          </Code>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
            </Stack>
          </Card>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
