/**
 * ScheduledBackupsPanel — bloc "Sauvegardes planifiées" pour AdminBackupsPage.
 *
 * Affiche la liste des plannings (cron), avec création/édition/run-now.
 * Chaque planning peut être local-only (remote_id=null) ou pousser vers
 * UNE connexion remote configurée (remote_id non-null).
 *
 * Un trigger DB stamps `remote_id_disconnected_at` quand un remote est
 * supprimé : on affiche alors une bannière orange sur le planning concerné
 * pour avertir l'admin que le push n'aura plus lieu.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import dayjs from 'dayjs'
import { useTranslation } from 'react-i18next'

import {
  createScheduledBackup,
  deleteScheduledBackup,
  fetchRemoteBackupConnections,
  fetchScheduledBackups,
  runScheduledBackupNow,
  updateScheduledBackup,
  validateCronExpression,
  type ScheduledBackupCreatePayload,
  type ScheduledBackupPatchPayload,
} from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'
import type { ScheduledBackup } from '@/schemas/admin'

const MISS_THRESHOLD_OPTIONS = [5, 10, 20, 30, 60] as const

interface CronPreset {
  label: string
  expression: string
}

// Les 4 presets sont des points de départ. L'admin peut éditer librement
// ensuite, le champ est libre.
const CRON_PRESETS: CronPreset[] = [
  { label: 'daily02', expression: '0 2 * * *' },
  { label: 'weekly', expression: '0 3 * * 0' },
  { label: 'monthly', expression: '0 4 1 * *' },
  { label: 'hourly', expression: '0 * * * *' },
]

export function ScheduledBackupsPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [editTarget, setEditTarget] = useState<ScheduledBackup | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-scheduled-backups'],
    queryFn: fetchScheduledBackups,
  })

  const deleteMut = useMutation({
    mutationFn: deleteScheduledBackup,
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.scheduledBackups.deleteSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-scheduled-backups'] })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  const toggleMut = useMutation({
    mutationFn: (args: { id: string; enabled: boolean }) =>
      updateScheduledBackup(args.id, { enabled: args.enabled }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin-scheduled-backups'] })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  const runNowMut = useMutation({
    mutationFn: runScheduledBackupNow,
    onSuccess: (result) => {
      if (result.status === 'ok') {
        notifications.show({
          color: 'green',
          message: t('admin.scheduledBackups.runNowSuccess'),
        })
      } else {
        notifications.show({
          color: 'red',
          title: t('admin.scheduledBackups.runNowFailed'),
          message: result.error ?? t('common.error'),
          autoClose: 8000,
        })
      }
      void qc.invalidateQueries({ queryKey: ['admin-scheduled-backups'] })
      // L'écran "Fichiers" doit aussi se rafraîchir si un backup vient d'être créé.
      void qc.invalidateQueries({ queryKey: ['admin-backups'] })
    },
  })

  function confirmDelete(s: ScheduledBackup) {
    modals.openConfirmModal({
      title: t('admin.scheduledBackups.deleteConfirmTitle'),
      children: (
        <Text size="sm">
          {t('admin.scheduledBackups.deleteConfirmDesc', { name: s.name })}
        </Text>
      ),
      labels: { confirm: t('common.delete'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: () => deleteMut.mutate(s.id),
    })
  }

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t('admin.scheduledBackups.title')}</Title>
          <Button
            size="xs"
            onClick={() => {
              setEditTarget(null)
              setModalOpen(true)
            }}
          >
            {t('admin.scheduledBackups.add')}
          </Button>
        </Group>

        <Text c="dimmed" size="sm">
          {t('admin.scheduledBackups.subtitle')}
        </Text>

        {isLoading && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}
        {error && (
          <Alert color="red">
            {error instanceof ApiError ? error.message : t('common.error')}
          </Alert>
        )}

        {!isLoading && !error && (data?.schedules.length ?? 0) === 0 && (
          <Alert color="blue" variant="light">
            {t('admin.scheduledBackups.empty')}
          </Alert>
        )}

        {!isLoading && !error && (data?.schedules.length ?? 0) > 0 && (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('admin.scheduledBackups.colName')}</Table.Th>
                <Table.Th>{t('admin.scheduledBackups.colCron')}</Table.Th>
                <Table.Th>{t('admin.scheduledBackups.colTarget')}</Table.Th>
                <Table.Th>{t('admin.scheduledBackups.colNextRun')}</Table.Th>
                <Table.Th>{t('admin.scheduledBackups.colLastRun')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data?.schedules.map((s) => (
                <ScheduleRow
                  key={s.id}
                  schedule={s}
                  onEdit={() => {
                    setEditTarget(s)
                    setModalOpen(true)
                  }}
                  onToggle={(enabled) => toggleMut.mutate({ id: s.id, enabled })}
                  onRunNow={() => runNowMut.mutate(s.id)}
                  onDelete={() => confirmDelete(s)}
                  runningId={runNowMut.isPending ? runNowMut.variables : null}
                />
              ))}
            </Table.Tbody>
          </Table>
        )}

        <ScheduleFormModal
          key={editTarget?.id ?? 'create'}
          opened={modalOpen}
          onClose={() => {
            setModalOpen(false)
            setEditTarget(null)
          }}
          editTarget={editTarget}
          onSaved={() => {
            setModalOpen(false)
            setEditTarget(null)
            void qc.invalidateQueries({ queryKey: ['admin-scheduled-backups'] })
          }}
        />
      </Stack>
    </Card>
  )
}

function ScheduleRow({
  schedule,
  onEdit,
  onToggle,
  onRunNow,
  onDelete,
  runningId,
}: {
  schedule: ScheduledBackup
  onEdit: () => void
  onToggle: (enabled: boolean) => void
  onRunNow: () => void
  onDelete: () => void
  runningId: string | null | undefined
}) {
  const { t } = useTranslation()
  const target =
    schedule.remote_id_disconnected_at !== null && schedule.remote_id === null
      ? t('admin.scheduledBackups.targetDisconnected')
      : schedule.remote_id === null
        ? t('admin.scheduledBackups.targetLocal')
        : `→ ${schedule.remote_id.substring(0, 8)}…`
  const nextRun = dayjs(schedule.next_run_at).format('YYYY-MM-DD HH:mm')
  const lastRunLabel = (() => {
    if (!schedule.last_run_at) return t('admin.scheduledBackups.lastRunNever')
    const ts = dayjs(schedule.last_run_at).format('YYYY-MM-DD HH:mm')
    if (schedule.last_run_status === 'ok') return `✓ ${ts}`
    return `✗ ${ts}`
  })()

  return (
    <>
      <Table.Tr>
        <Table.Td>
          <Stack gap={0}>
            <Group gap="xs">
              <Text fw={500}>{schedule.name}</Text>
              {!schedule.enabled && (
                <Badge size="xs" color="gray">
                  {t('admin.scheduledBackups.disabled')}
                </Badge>
              )}
            </Group>
            {schedule.description && (
              <Text size="xs" c="dimmed">
                {schedule.description}
              </Text>
            )}
          </Stack>
        </Table.Td>
        <Table.Td>
          <Text size="sm" ff="monospace">
            {schedule.cron_expression}
          </Text>
        </Table.Td>
        <Table.Td>
          <Text size="sm">{target}</Text>
        </Table.Td>
        <Table.Td>
          <Text size="xs" c="dimmed">
            {nextRun}
          </Text>
        </Table.Td>
        <Table.Td>
          <Text
            size="xs"
            c={schedule.last_run_status === 'failed' ? 'red' : 'dimmed'}
            title={schedule.last_run_error ?? undefined}
          >
            {lastRunLabel}
          </Text>
        </Table.Td>
        <Table.Td>
          <Group gap="xs" justify="flex-end">
            <Switch
              checked={schedule.enabled}
              onChange={(e) => onToggle(e.currentTarget.checked)}
              size="sm"
            />
            <Button
              size="xs"
              variant="light"
              loading={runningId === schedule.id}
              onClick={onRunNow}
            >
              {t('admin.scheduledBackups.runNow')}
            </Button>
            <Button size="xs" variant="subtle" onClick={onEdit}>
              {t('common.edit')}
            </Button>
            <Button size="xs" variant="subtle" color="red" onClick={onDelete}>
              {t('common.delete')}
            </Button>
          </Group>
        </Table.Td>
      </Table.Tr>
      {schedule.remote_id_disconnected_at !== null && schedule.remote_id === null && (
        <Table.Tr>
          <Table.Td colSpan={6}>
            <Alert color="orange" variant="light">
              {t('admin.scheduledBackups.remoteDisconnectedWarning', {
                date: dayjs(schedule.remote_id_disconnected_at).format('YYYY-MM-DD HH:mm'),
              })}
            </Alert>
          </Table.Td>
        </Table.Tr>
      )}
    </>
  )
}

interface FormValues {
  name: string
  cron_expression: string
  remote_id: string | null
  miss_threshold_minutes: number
  description: string
  enabled: boolean
}

function ScheduleFormModal({
  opened,
  onClose,
  editTarget,
  onSaved,
}: {
  opened: boolean
  onClose: () => void
  editTarget: ScheduledBackup | null
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const isEditing = editTarget !== null

  const form = useForm<FormValues>({
    initialValues: editTarget
      ? {
          name: editTarget.name,
          cron_expression: editTarget.cron_expression,
          remote_id: editTarget.remote_id,
          miss_threshold_minutes: editTarget.miss_threshold_minutes,
          description: editTarget.description ?? '',
          enabled: editTarget.enabled,
        }
      : {
          name: '',
          cron_expression: '0 2 * * *',
          remote_id: null,
          miss_threshold_minutes: 5,
          description: '',
          enabled: true,
        },
    validate: {
      name: (v) => (!v.trim() ? t('common.required') : null),
      cron_expression: (v) => (!v.trim() ? t('common.required') : null),
    },
  })

  // Liste des connexions remote candidates (filtrée sur celles avec remote_path_full).
  const { data: remotes } = useQuery({
    queryKey: ['admin-remote-backups'],
    queryFn: fetchRemoteBackupConnections,
  })

  const remoteOptions = useMemo(() => {
    const items = (remotes?.connections ?? []).filter((c) => {
      // Filtre : seules les connexions avec un path "full" configuré peuvent
      // recevoir un push manuel/programmé.
      const cfg = c.config
      const hasFull =
        c.kind === 's3'
          ? Boolean(String(cfg.prefix_full ?? '').trim())
          : Boolean(String(cfg.remote_path_full ?? '').trim())
      return hasFull
    })
    return [
      { value: '', label: t('admin.scheduledBackups.targetLocal') },
      ...items.map((c) => ({
        value: c.id,
        label: `${c.name} (${c.kind})`,
      })),
    ]
  }, [remotes, t])

  // Validation cron en live (debounced) pour le preview des 3 prochaines occurrences.
  const [cronPreview, setCronPreview] = useState<{ valid: boolean; lines: string[]; error: string | null }>({
    valid: true,
    lines: [],
    error: null,
  })
  useEffect(() => {
    const expr = form.values.cron_expression.trim()
    if (!expr) {
      setCronPreview({ valid: false, lines: [], error: null })
      return
    }
    const handle = setTimeout(async () => {
      try {
        const r = await validateCronExpression(expr)
        setCronPreview({
          valid: r.valid,
          lines: r.next_3_occurrences.map((iso) => dayjs(iso).format('YYYY-MM-DD HH:mm')),
          error: r.error,
        })
      } catch {
        // Réseau / 4xx — on n'altère pas le UX (l'admin verra l'erreur au submit)
      }
    }, 400)
    return () => clearTimeout(handle)
  }, [form.values.cron_expression])

  const createMut = useMutation({
    mutationFn: createScheduledBackup,
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.scheduledBackups.createSuccess') })
      onSaved()
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  const updateMut = useMutation({
    mutationFn: (args: { id: string; payload: ScheduledBackupPatchPayload }) =>
      updateScheduledBackup(args.id, args.payload),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.scheduledBackups.updateSuccess') })
      onSaved()
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  function handleSubmit(values: FormValues) {
    const remoteIdNormalized = values.remote_id || null
    if (isEditing && editTarget) {
      const payload: ScheduledBackupPatchPayload = {
        name: values.name.trim(),
        cron_expression: values.cron_expression.trim(),
        remote_id: remoteIdNormalized,
        // set_remote_id=true : on envoie explicitement le remote_id (même si null,
        // pour pouvoir effacer un lien existant).
        set_remote_id: true,
        miss_threshold_minutes: values.miss_threshold_minutes,
        description: values.description.trim() || null,
        set_description: true,
        enabled: values.enabled,
      }
      updateMut.mutate({ id: editTarget.id, payload })
    } else {
      const payload: ScheduledBackupCreatePayload = {
        name: values.name.trim(),
        cron_expression: values.cron_expression.trim(),
        remote_id: remoteIdNormalized,
        miss_threshold_minutes: values.miss_threshold_minutes,
        description: values.description.trim() || null,
        enabled: values.enabled,
      }
      createMut.mutate(payload)
    }
  }

  const submitting = createMut.isPending || updateMut.isPending

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEditing ? t('admin.scheduledBackups.editTitle') : t('admin.scheduledBackups.addTitle')}
      size="lg"
    >
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack gap="sm">
          <TextInput
            label={t('admin.scheduledBackups.fieldName')}
            required
            {...form.getInputProps('name')}
          />

          <Stack gap={4}>
            <TextInput
              label={t('admin.scheduledBackups.fieldCron')}
              description={t('admin.scheduledBackups.fieldCronHint')}
              required
              {...form.getInputProps('cron_expression')}
            />
            <Group gap="xs">
              {CRON_PRESETS.map((p) => (
                <Button
                  key={p.label}
                  size="xs"
                  variant="subtle"
                  onClick={() => form.setFieldValue('cron_expression', p.expression)}
                >
                  {t(`admin.scheduledBackups.preset.${p.label}`)}
                </Button>
              ))}
            </Group>
            {/* Preview live des 3 prochaines occurrences */}
            {cronPreview.error ? (
              <Alert color="orange" variant="light" py={6}>
                <Text size="xs">{cronPreview.error}</Text>
              </Alert>
            ) : cronPreview.lines.length > 0 ? (
              <Alert color="blue" variant="light" py={6}>
                <Text size="xs" fw={500}>
                  {t('admin.scheduledBackups.next3')}
                </Text>
                {cronPreview.lines.map((line) => (
                  <Text size="xs" ff="monospace" key={line}>
                    {line}
                  </Text>
                ))}
              </Alert>
            ) : null}
          </Stack>

          <Select
            label={t('admin.scheduledBackups.fieldTarget')}
            description={t('admin.scheduledBackups.fieldTargetHint')}
            data={remoteOptions}
            value={form.values.remote_id ?? ''}
            onChange={(v) => form.setFieldValue('remote_id', v || null)}
            allowDeselect={false}
          />

          <Select
            label={t('admin.scheduledBackups.fieldMissThreshold')}
            description={t('admin.scheduledBackups.fieldMissThresholdHint')}
            data={MISS_THRESHOLD_OPTIONS.map((m) => ({
              value: String(m),
              label: t('admin.scheduledBackups.minutes', { count: m }),
            }))}
            value={String(form.values.miss_threshold_minutes)}
            onChange={(v) => form.setFieldValue('miss_threshold_minutes', Number(v) || 5)}
            allowDeselect={false}
          />

          <Textarea
            label={t('admin.scheduledBackups.fieldDescription')}
            rows={2}
            {...form.getInputProps('description')}
          />

          <Switch
            label={t('admin.scheduledBackups.fieldEnabled')}
            {...form.getInputProps('enabled', { type: 'checkbox' })}
          />

          <Group justify="flex-end" mt="md">
            <Button variant="subtle" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={submitting}>
              {isEditing ? t('common.save') : t('common.create')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}
