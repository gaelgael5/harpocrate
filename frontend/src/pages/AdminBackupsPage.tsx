import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Table,
  Text,
  Button,
  Group,
  Badge,
  Loader,
  Center,
  Alert,
  Modal,
  TextInput,
  Textarea,
  NumberInput,
  Switch,
  Divider,
  Card,
  Menu,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'

import {
  fetchBackups,
  fetchMaintenanceStatus,
  createBackup,
  deleteBackup,
  restoreBackup,
  enableMaintenance,
  disableMaintenance,
  backupDownloadUrl,
  fetchS3Backups,
  pushBackupToS3,
  pullBackupFromS3,
  fetchRemoteBackupConnections,
  pushBackupToRemote,
} from '@/lib/adminApi'
import type { Backup } from '@/schemas/admin'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function RestoreModal({
  backup,
  opened,
  onClose,
}: {
  backup: Backup
  opened: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const stem = backup.filename.replace(/\.tar\.age$/, '')
  const expected = `RESTORE ${stem}`

  const [ageKey, setAgeKey] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [autoMaint, setAutoMaint] = useState(true)

  const mutation = useMutation({
    mutationFn: () =>
      restoreBackup(backup.id, {
        age_private_key: ageKey,
        confirmation,
        auto_enable_maintenance: autoMaint,
      }),
    onSuccess: (result) => {
      notifications.show({
        color: 'green',
        message: t('admin.backups.restoreSuccess', { epoch: result.session_epoch_new }),
      })
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
      onClose()
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('admin.backups.restoreError')
      notifications.show({ color: 'red', message: msg })
    },
  })

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('admin.backups.restoreTitle', { filename: backup.filename })}
      size="lg"
    >
      <Stack>
        <Alert color="red" title="⚠️">
          {t('admin.backups.restoreWarning')}
        </Alert>
        <TextInput
          label={t('admin.backups.agePrivateKey')}
          placeholder={t('admin.backups.agePrivateKeyPlaceholder')}
          value={ageKey}
          onChange={(e) => setAgeKey(e.currentTarget.value)}
        />
        <TextInput
          label={t('admin.backups.confirmationLabel', { expected })}
          placeholder={expected}
          value={confirmation}
          onChange={(e) => setConfirmation(e.currentTarget.value)}
        />
        <Switch
          label={t('admin.backups.autoMaintenance')}
          checked={autoMaint}
          onChange={(e) => setAutoMaint(e.currentTarget.checked)}
        />
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            loading={mutation.isPending}
            disabled={confirmation !== expected || !ageKey}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? t('admin.backups.restoring') : t('admin.backups.restore')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

function MaintenancePanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['maintenance-status'],
    queryFn: fetchMaintenanceStatus,
    refetchInterval: 15_000,
  })

  const [reason, setReason] = useState('')
  const [delay, setDelay] = useState<number | string>(0)
  const [duration, setDuration] = useState<number | string>(30)

  const enableMut = useMutation({
    mutationFn: () =>
      enableMaintenance({
        reason,
        delay_seconds: typeof delay === 'number' ? delay : 0,
        estimated_duration_minutes: typeof duration === 'number' ? duration : 30,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['maintenance-status'] }),
  })

  const disableMut = useMutation({
    mutationFn: disableMaintenance,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['maintenance-status'] }),
  })

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t('maintenance.status')}</Title>
          <Badge color={status?.active ? 'orange' : 'green'}>
            {status?.active ? t('maintenance.active') : t('maintenance.inactive')}
          </Badge>
        </Group>

        {status?.active ? (
          <Button
            color="green"
            loading={disableMut.isPending}
            onClick={() => disableMut.mutate()}
          >
            {disableMut.isPending ? t('maintenance.disabling') : t('maintenance.disable')}
          </Button>
        ) : (
          <Stack>
            <TextInput
              label={t('maintenance.reason')}
              placeholder={t('maintenance.reasonPlaceholder')}
              value={reason}
              onChange={(e) => setReason(e.currentTarget.value)}
            />
            <Group grow>
              <NumberInput
                label={t('maintenance.delaySeconds')}
                value={delay}
                onChange={setDelay}
                min={0}
              />
              <NumberInput
                label={t('maintenance.estimatedMinutes')}
                value={duration}
                onChange={setDuration}
                min={1}
              />
            </Group>
            <Button
              color="orange"
              loading={enableMut.isPending}
              disabled={!reason}
              onClick={() => enableMut.mutate()}
            >
              {enableMut.isPending ? t('maintenance.enabling') : t('maintenance.enable')}
            </Button>
          </Stack>
        )}
      </Stack>
    </Card>
  )
}

function S3Section() {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const { data: s3Data, error: s3Error } = useQuery({
    queryKey: ['admin-s3-backups'],
    queryFn: fetchS3Backups,
    retry: false,
  })

  const pullMut = useMutation({
    mutationFn: (s3Key: string) => pullBackupFromS3(s3Key),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.backups.s3PullSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
      void qc.invalidateQueries({ queryKey: ['admin-s3-backups'] })
    },
    onError: () => {
      notifications.show({ color: 'red', message: t('admin.backups.s3PullError') })
    },
  })

  return (
    <Card withBorder>
      <Stack>
        <Title order={4}>{t('admin.backups.s3Section')}</Title>
        {s3Error ? (
          <Alert color="orange">{t('admin.backups.s3NotConfigured')}</Alert>
        ) : s3Data?.backups.length === 0 ? (
          <Text c="dimmed">{t('admin.backups.noBackups')}</Text>
        ) : (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('admin.backups.s3Key')}</Table.Th>
                <Table.Th>{t('admin.backups.s3Size')}</Table.Th>
                <Table.Th>{t('admin.backups.s3Date')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {s3Data?.backups.map((item) => (
                <Table.Tr key={item.key}>
                  <Table.Td>
                    <Text size="xs" ff="monospace">
                      {item.key}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatBytes(item.size_bytes)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {dayjs(item.last_modified).format('YYYY-MM-DD HH:mm')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="outline"
                      loading={pullMut.isPending}
                      onClick={() => pullMut.mutate(item.key)}
                    >
                      {pullMut.isPending ? t('admin.backups.s3Pulling') : t('admin.backups.s3Pull')}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  )
}

export function AdminBackupsPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [restoreTarget, setRestoreTarget] = useState<Backup | null>(null)
  const [description, setDescription] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-backups'],
    queryFn: fetchBackups,
  })

  const pushS3Mut = useMutation({
    mutationFn: (id: string) => pushBackupToS3(id),
    onSuccess: (result) => {
      notifications.show({
        color: 'green',
        message: t('admin.backups.pushS3Success', { key: result.s3_key }),
      })
      void qc.invalidateQueries({ queryKey: ['admin-s3-backups'] })
    },
    onError: () => {
      notifications.show({ color: 'red', message: t('admin.backups.pushS3Error') })
    },
  })

  // Connexions backup distantes (LOT L3) — partagé avec AdminRemoteBackupsPage
  const { data: remotesData } = useQuery({
    queryKey: ['admin-remote-backups'],
    queryFn: fetchRemoteBackupConnections,
  })
  const remotes = remotesData?.connections ?? []

  const pushRemoteMut = useMutation({
    mutationFn: (args: { backupId: string; remoteId: string }) =>
      pushBackupToRemote(args.backupId, args.remoteId),
    onSuccess: (result) => {
      notifications.show({
        color: 'green',
        message: t('admin.backups.pushRemoteSuccess', {
          name: result.remote_name,
          size: formatBytes(result.bytes_sent),
        }),
      })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('admin.backups.pushRemoteError')
      notifications.show({ color: 'red', message: msg, autoClose: 8000 })
    },
  })

  const createMut = useMutation({
    mutationFn: () => createBackup({ description: description || undefined }),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.backups.createSuccess') })
      setDescription('')
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteBackup(id),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.backups.deleteSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
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
    return (
      <Alert color="red">{error instanceof Error ? error.message : t('common.error')}</Alert>
    )
  }

  return (
    <Stack>
      <Title order={2}>{t('admin.backups.title')}</Title>

      <MaintenancePanel />

      <Divider />

      <Card withBorder>
        <Stack>
          <Title order={4}>{t('admin.backups.create')}</Title>
          <Textarea
            label={t('admin.backups.descriptionLabel')}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            rows={2}
          />
          <Button
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
            w="fit-content"
          >
            {createMut.isPending ? t('admin.backups.creating') : t('admin.backups.create')}
          </Button>
        </Stack>
      </Card>

      {data?.backups.length === 0 ? (
        <Text c="dimmed">{t('admin.backups.noBackups')}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('admin.backups.filename')}</Table.Th>
              <Table.Th>{t('admin.backups.size')}</Table.Th>
              <Table.Th>{t('admin.backups.date')}</Table.Th>
              <Table.Th>{t('admin.backups.description')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.backups.map((b) => (
              <Table.Tr key={b.id}>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {b.filename}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatBytes(b.size_bytes)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {dayjs(b.created_at).format('YYYY-MM-DD HH:mm')}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {b.description ?? '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <Button
                      component="a"
                      href={backupDownloadUrl(b.id)}
                      download={b.filename}
                      size="xs"
                      variant="outline"
                    >
                      {t('admin.backups.download')}
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      color="brand"
                      loading={pushS3Mut.isPending}
                      onClick={() => pushS3Mut.mutate(b.id)}
                    >
                      {pushS3Mut.isPending ? t('admin.backups.pushingS3') : t('admin.backups.pushS3')}
                    </Button>
                    <Menu position="bottom-end" withinPortal>
                      <Menu.Target>
                        <Button
                          size="xs"
                          variant="outline"
                          color="brand"
                          loading={
                            pushRemoteMut.isPending && pushRemoteMut.variables?.backupId === b.id
                          }
                          disabled={remotes.length === 0}
                          title={
                            remotes.length === 0
                              ? t('admin.backups.pushRemoteEmpty')
                              : undefined
                          }
                        >
                          {t('admin.backups.pushRemote')}
                        </Button>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Label>{t('admin.backups.pushRemotePick')}</Menu.Label>
                        {remotes.map((r) => (
                          <Menu.Item
                            key={r.id}
                            onClick={() =>
                              pushRemoteMut.mutate({ backupId: b.id, remoteId: r.id })
                            }
                          >
                            {r.name}{' '}
                            <Text span c="dimmed" size="xs">
                              ({r.kind})
                            </Text>
                          </Menu.Item>
                        ))}
                      </Menu.Dropdown>
                    </Menu>
                    <Button
                      size="xs"
                      variant="outline"
                      color="orange"
                      onClick={() => setRestoreTarget(b)}
                    >
                      {t('admin.backups.restore')}
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      color="red"
                      loading={deleteMut.isPending}
                      onClick={() => {
                        if (
                          confirm(t('admin.backups.deleteConfirm', { filename: b.filename }))
                        ) {
                          deleteMut.mutate(b.id)
                        }
                      }}
                    >
                      {t('admin.backups.delete')}
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Divider />

      <S3Section />

      {restoreTarget && (
        <RestoreModal
          backup={restoreTarget}
          opened={true}
          onClose={() => setRestoreTarget(null)}
        />
      )}
    </Stack>
  )
}
