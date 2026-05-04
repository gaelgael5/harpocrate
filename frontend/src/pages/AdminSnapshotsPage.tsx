import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Card,
  Group,
  Badge,
  Text,
  Button,
  NumberInput,
  Switch,
  SimpleGrid,
  Table,
  Select,
  Loader,
  Center,
  Modal,
  Divider,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'

import {
  fetchSnapshotPolicy,
  updateSnapshotPolicy,
  triggerSnapshot,
  fetchSnapshotHistory,
} from '@/lib/adminApi'
import type { SnapshotPolicy } from '@/schemas/admin'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function PolicyModal({
  policy,
  opened,
  onClose,
}: {
  policy: SnapshotPolicy
  opened: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const [intervalMinutes, setIntervalMinutes] = useState<number | string>(policy.interval_minutes)
  const [hourly, setHourly] = useState<number | string>(policy.retention.hourly)
  const [daily, setDaily] = useState<number | string>(policy.retention.daily)
  const [weekly, setWeekly] = useState<number | string>(policy.retention.weekly)
  const [monthly, setMonthly] = useState<number | string>(policy.retention.monthly)
  const [yearly, setYearly] = useState<number | string>(policy.retention.yearly)
  const [pushRemote, setPushRemote] = useState(policy.push_remote_after_snapshot)
  const [skipNoChange, setSkipNoChange] = useState(policy.skip_if_no_change)

  const n = (v: number | string, def: number): number =>
    typeof v === 'number' ? v : def

  const mut = useMutation({
    mutationFn: () =>
      updateSnapshotPolicy({
        interval_minutes: n(intervalMinutes, 0),
        retention: {
          hourly: n(hourly, 24),
          daily: n(daily, 7),
          weekly: n(weekly, 4),
          monthly: n(monthly, 12),
          yearly: n(yearly, 5),
        },
        push_remote_after_snapshot: pushRemote,
        remote_destinations_to_push: policy.remote_destinations_to_push,
        skip_if_no_change: skipNoChange,
      }),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('snapshots.policySaved') })
      void qc.invalidateQueries({ queryKey: ['snapshot-policy'] })
      onClose()
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  return (
    <Modal opened={opened} onClose={onClose} title={t('snapshots.editPolicy')} size="lg">
      <Stack>
        <NumberInput
          label={t('snapshots.intervalMinutes')}
          description={t('snapshots.intervalHint')}
          value={intervalMinutes}
          onChange={setIntervalMinutes}
          min={0}
        />
        <Text fw={500}>{t('snapshots.retention')}</Text>
        <SimpleGrid cols={5}>
          <NumberInput label={t('snapshots.hourly')} value={hourly} onChange={setHourly} min={0} />
          <NumberInput label={t('snapshots.daily')} value={daily} onChange={setDaily} min={0} />
          <NumberInput label={t('snapshots.weekly')} value={weekly} onChange={setWeekly} min={0} />
          <NumberInput label={t('snapshots.monthly')} value={monthly} onChange={setMonthly} min={0} />
          <NumberInput label={t('snapshots.yearly')} value={yearly} onChange={setYearly} min={0} />
        </SimpleGrid>
        <Switch
          label={t('snapshots.pushRemote')}
          checked={pushRemote}
          onChange={(e) => setPushRemote(e.currentTarget.checked)}
        />
        <Switch
          label={t('snapshots.skipNoChange')}
          checked={skipNoChange}
          onChange={(e) => setSkipNoChange(e.currentTarget.checked)}
        />
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>{t('common.cancel')}</Button>
          <Button loading={mut.isPending} onClick={() => mut.mutate()}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

export function AdminSnapshotsPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [tierFilter, setTierFilter] = useState<string | null>(null)
  const [editOpened, setEditOpened] = useState(false)

  const { data: policy, isLoading: policyLoading } = useQuery({
    queryKey: ['snapshot-policy'],
    queryFn: fetchSnapshotPolicy,
  })

  const { data: history, isLoading: histLoading } = useQuery({
    queryKey: ['snapshot-history', tierFilter],
    queryFn: () => fetchSnapshotHistory({ tier: tierFilter ?? undefined, limit: 100 }),
  })

  const triggerMut = useMutation({
    mutationFn: (force: boolean) => triggerSnapshot({ force, description: 'Manual snapshot' }),
    onSuccess: (result) => {
      if (result.skipped) {
        notifications.show({ color: 'yellow', message: t('snapshots.skippedNoChange') })
      } else {
        notifications.show({ color: 'green', message: t('snapshots.triggerSuccess') })
        void qc.invalidateQueries({ queryKey: ['snapshot-history'] })
      }
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  const isActive = (policy?.interval_minutes ?? 0) > 0

  if (policyLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }

  return (
    <Stack>
      <Title order={2}>{t('snapshots.title')}</Title>

      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Title order={4}>{t('snapshots.status')}</Title>
            <Badge color={isActive ? 'green' : 'gray'}>
              {isActive ? t('snapshots.active') : t('snapshots.disabled')}
            </Badge>
          </Group>
          {policy && (
            <Text size="sm" c="dimmed">
              {isActive
                ? t('snapshots.intervalDesc', { minutes: policy.interval_minutes })
                : t('snapshots.disabledDesc')}
            </Text>
          )}
          <Button variant="outline" w="fit-content" onClick={() => setEditOpened(true)}>
            {t('snapshots.editPolicy')}
          </Button>
        </Stack>
      </Card>

      {policy && (
        <Card withBorder>
          <Stack>
            <Title order={4}>{t('snapshots.retentionTitle')}</Title>
            <SimpleGrid cols={5}>
              {(['hourly', 'daily', 'weekly', 'monthly', 'yearly'] as const).map((tier) => (
                <Stack key={tier} gap={2} align="center">
                  <Text size="xs" c="dimmed">{t(`snapshots.${tier}`)}</Text>
                  <Text fw={700}>{policy.retention[tier]}</Text>
                </Stack>
              ))}
            </SimpleGrid>
          </Stack>
        </Card>
      )}

      <Card withBorder>
        <Stack>
          <Title order={4}>{t('snapshots.manual')}</Title>
          <Group>
            <Button
              loading={triggerMut.isPending}
              onClick={() => triggerMut.mutate(false)}
            >
              {t('snapshots.trigger')}
            </Button>
            <Button
              variant="outline"
              color="orange"
              loading={triggerMut.isPending}
              onClick={() => triggerMut.mutate(true)}
            >
              {t('snapshots.triggerForce')}
            </Button>
          </Group>
        </Stack>
      </Card>

      <Divider />

      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t('snapshots.historyTitle')}</Title>
          <Select
            placeholder={t('snapshots.allTiers')}
            clearable
            data={['hourly', 'daily', 'weekly', 'monthly', 'yearly']}
            value={tierFilter}
            onChange={setTierFilter}
            w={160}
          />
        </Group>

        {histLoading ? (
          <Center><Loader size="sm" /></Center>
        ) : (history?.snapshots.length ?? 0) === 0 ? (
          <Text c="dimmed">{t('snapshots.noSnapshots')}</Text>
        ) : (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('snapshots.colCreated')}</Table.Th>
                <Table.Th>{t('snapshots.colTier')}</Table.Th>
                <Table.Th>{t('snapshots.colSize')}</Table.Th>
                <Table.Th>{t('snapshots.colDescription')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {history?.snapshots.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>
                    <Text size="xs">{dayjs(s.created_at).format('YYYY-MM-DD HH:mm')}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={
                      s.tier === 'yearly' ? 'violet'
                      : s.tier === 'monthly' ? 'brand'
                      : s.tier === 'weekly' ? 'teal'
                      : s.tier === 'daily' ? 'green'
                      : 'gray'
                    }>
                      {s.tier ?? '—'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatBytes(s.size_bytes)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">{s.description ?? '—'}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>

      {policy && (
        <PolicyModal
          policy={policy}
          opened={editOpened}
          onClose={() => setEditOpened(false)}
        />
      )}
    </Stack>
  )
}
