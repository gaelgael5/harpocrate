/**
 * AdminRemoteBackupsPage — gestion des connexions de backup distantes (LOT L2).
 *
 * Permet de créer, lister, modifier, supprimer et tester une connexion vers un
 * serveur SFTP distant. Les credentials sont chiffrés côté serveur (AES-GCM
 * via clef dérivée de HMAC_KEY) et ne sont jamais retournés en clair par l'API.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Text,
  Button,
  Group,
  Table,
  Card,
  Loader,
  Center,
  Alert,
  Modal,
  TextInput,
  PasswordInput,
  Textarea,
  NumberInput,
  Select,
  Badge,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { modals } from '@mantine/modals'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import {
  fetchRemoteBackupConnections,
  createRemoteBackupConnection,
  updateRemoteBackupConnection,
  deleteRemoteBackupConnection,
  testRemoteBackupConnection,
  type RemoteBackupCreatePayload,
} from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'
import type { RemoteBackupConnection } from '@/schemas/admin'

// ─── Form values pour le modal create/edit ────────────────────────────────────

interface SftpFormValues {
  name: string
  host: string
  port: number | string
  remote_path: string
  host_key_fingerprint: string
  username: string
  auth_method: 'password' | 'private_key'
  password: string
  private_key: string
  private_key_passphrase: string
}

const DEFAULT_FORM: SftpFormValues = {
  name: '',
  host: '',
  port: 22,
  remote_path: '/',
  host_key_fingerprint: '',
  username: '',
  auth_method: 'password',
  password: '',
  private_key: '',
  private_key_passphrase: '',
}

function buildPayload(values: SftpFormValues): RemoteBackupCreatePayload {
  const config: Record<string, unknown> = {
    host: values.host.trim(),
    port: typeof values.port === 'number' ? values.port : parseInt(values.port, 10) || 22,
    remote_path: values.remote_path.trim() || '/',
  }
  if (values.host_key_fingerprint.trim()) {
    config.host_key_fingerprint = values.host_key_fingerprint.trim()
  }

  const credentials: Record<string, unknown> = {
    username: values.username.trim(),
    auth_method: values.auth_method,
  }
  if (values.auth_method === 'password') {
    credentials.password = values.password
  } else {
    credentials.private_key = values.private_key
    if (values.private_key_passphrase) {
      credentials.private_key_passphrase = values.private_key_passphrase
    }
  }

  return { name: values.name.trim(), kind: 'sftp', config, credentials }
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function AdminRemoteBackupsPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [editTarget, setEditTarget] = useState<RemoteBackupConnection | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-remote-backups'],
    queryFn: fetchRemoteBackupConnections,
  })

  const createMut = useMutation({
    mutationFn: createRemoteBackupConnection,
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.remoteBackups.createSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-remote-backups'] })
      setModalOpen(false)
      setEditTarget(null)
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  const updateMut = useMutation({
    mutationFn: (args: { id: string; payload: RemoteBackupCreatePayload }) =>
      updateRemoteBackupConnection(args.id, {
        name: args.payload.name,
        config: args.payload.config,
        // credentials sont updated SEULEMENT si l'admin re-saisit (sinon on garde l'existant)
        credentials: args.payload.credentials,
      }),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.remoteBackups.updateSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-remote-backups'] })
      setModalOpen(false)
      setEditTarget(null)
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteRemoteBackupConnection,
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('admin.remoteBackups.deleteSuccess') })
      void qc.invalidateQueries({ queryKey: ['admin-remote-backups'] })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    },
  })

  const testMut = useMutation({
    mutationFn: testRemoteBackupConnection,
    onSuccess: (result) => {
      if (result.ok) {
        notifications.show({ color: 'green', message: t('admin.remoteBackups.testSuccess') })
      } else {
        notifications.show({
          color: 'red',
          title: t('admin.remoteBackups.testFailed'),
          message: result.message,
          autoClose: 8000,
        })
      }
    },
  })

  function openCreate() {
    setEditTarget(null)
    setModalOpen(true)
  }

  function openEdit(conn: RemoteBackupConnection) {
    setEditTarget(conn)
    setModalOpen(true)
  }

  function confirmDelete(conn: RemoteBackupConnection) {
    modals.openConfirmModal({
      title: t('admin.remoteBackups.deleteConfirmTitle'),
      children: (
        <Text size="sm">
          {t('admin.remoteBackups.deleteConfirmDesc', { name: conn.name })}
        </Text>
      ),
      labels: { confirm: t('common.delete'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: () => deleteMut.mutate(conn.id),
    })
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t('admin.remoteBackups.title')}</Title>
        <Button onClick={openCreate}>{t('admin.remoteBackups.addConnection')}</Button>
      </Group>

      <Text c="dimmed" size="sm">
        {t('admin.remoteBackups.subtitle')}
      </Text>

      {isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {error && (
        <Alert color="red">
          {error instanceof ApiError ? error.message : t('common.error')}
        </Alert>
      )}

      {!isLoading && !error && (data?.connections.length ?? 0) === 0 && (
        <Alert color="blue" variant="light">
          {t('admin.remoteBackups.noConnections')}
        </Alert>
      )}

      {!isLoading && !error && (data?.connections.length ?? 0) > 0 && (
        <Card withBorder>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('admin.remoteBackups.colName')}</Table.Th>
                <Table.Th>{t('admin.remoteBackups.colKind')}</Table.Th>
                <Table.Th>{t('admin.remoteBackups.colHost')}</Table.Th>
                <Table.Th>{t('admin.remoteBackups.colPath')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data?.connections.map((c) => (
                <Table.Tr key={c.id}>
                  <Table.Td>
                    <Text fw={500}>{c.name}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light">{c.kind}</Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {String(c.config.host ?? '')}:{String(c.config.port ?? '')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {String(c.config.remote_path ?? '')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <Button
                        size="xs"
                        variant="light"
                        loading={testMut.isPending && testMut.variables === c.id}
                        onClick={() => testMut.mutate(c.id)}
                      >
                        {t('admin.remoteBackups.test')}
                      </Button>
                      <Button size="xs" variant="subtle" onClick={() => openEdit(c)}>
                        {t('common.edit')}
                      </Button>
                      <Button
                        size="xs"
                        variant="subtle"
                        color="red"
                        onClick={() => confirmDelete(c)}
                      >
                        {t('common.delete')}
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      <SftpFormModal
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setEditTarget(null)
        }}
        editTarget={editTarget}
        onSubmit={(payload) => {
          if (editTarget) {
            updateMut.mutate({ id: editTarget.id, payload })
          } else {
            createMut.mutate(payload)
          }
        }}
        submitting={createMut.isPending || updateMut.isPending}
      />
    </Stack>
  )
}

// ─── Modal create/edit ────────────────────────────────────────────────────────

function SftpFormModal({
  opened,
  onClose,
  editTarget,
  onSubmit,
  submitting,
}: {
  opened: boolean
  onClose: () => void
  editTarget: RemoteBackupConnection | null
  onSubmit: (payload: RemoteBackupCreatePayload) => void
  submitting: boolean
}) {
  const { t } = useTranslation()

  const form = useForm<SftpFormValues>({
    initialValues: editTarget
      ? {
          ...DEFAULT_FORM,
          name: editTarget.name,
          host: String(editTarget.config.host ?? ''),
          port: typeof editTarget.config.port === 'number' ? editTarget.config.port : 22,
          remote_path: String(editTarget.config.remote_path ?? '/'),
          host_key_fingerprint: String(editTarget.config.host_key_fingerprint ?? ''),
        }
      : DEFAULT_FORM,
    validate: {
      name: (v) => (!v.trim() ? t('common.required') : null),
      host: (v) => (!v.trim() ? t('common.required') : null),
      username: (v) => (!v.trim() ? t('common.required') : null),
      password: (v, values) =>
        values.auth_method === 'password' && !editTarget && !v
          ? t('common.required')
          : null,
      private_key: (v, values) =>
        values.auth_method === 'private_key' && !editTarget && !v
          ? t('common.required')
          : null,
    },
  })

  function handleSubmit(values: SftpFormValues) {
    onSubmit(buildPayload(values))
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={editTarget ? t('admin.remoteBackups.editTitle') : t('admin.remoteBackups.addTitle')}
      size="lg"
    >
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack gap="sm">
          <TextInput
            label={t('admin.remoteBackups.fieldName')}
            description={t('admin.remoteBackups.fieldNameHint')}
            required
            {...form.getInputProps('name')}
          />
          <Group grow>
            <TextInput
              label={t('admin.remoteBackups.fieldHost')}
              required
              {...form.getInputProps('host')}
            />
            <NumberInput
              label={t('admin.remoteBackups.fieldPort')}
              min={1}
              max={65535}
              {...form.getInputProps('port')}
            />
          </Group>
          <TextInput
            label={t('admin.remoteBackups.fieldRemotePath')}
            description={t('admin.remoteBackups.fieldRemotePathHint')}
            required
            {...form.getInputProps('remote_path')}
          />
          <TextInput
            label={t('admin.remoteBackups.fieldFingerprint')}
            description={t('admin.remoteBackups.fieldFingerprintHint')}
            {...form.getInputProps('host_key_fingerprint')}
          />
          <TextInput
            label={t('admin.remoteBackups.fieldUsername')}
            required
            {...form.getInputProps('username')}
          />
          <Select
            label={t('admin.remoteBackups.fieldAuthMethod')}
            data={[
              { value: 'password', label: t('admin.remoteBackups.authPassword') },
              { value: 'private_key', label: t('admin.remoteBackups.authPrivateKey') },
            ]}
            {...form.getInputProps('auth_method')}
            allowDeselect={false}
          />
          {form.values.auth_method === 'password' ? (
            <PasswordInput
              label={t('admin.remoteBackups.fieldPassword')}
              description={
                editTarget ? t('admin.remoteBackups.passwordEditHint') : undefined
              }
              {...form.getInputProps('password')}
            />
          ) : (
            <>
              <Textarea
                label={t('admin.remoteBackups.fieldPrivateKey')}
                description={
                  editTarget ? t('admin.remoteBackups.privateKeyEditHint') : undefined
                }
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----..."
                rows={6}
                {...form.getInputProps('private_key')}
              />
              <PasswordInput
                label={t('admin.remoteBackups.fieldPrivateKeyPassphrase')}
                {...form.getInputProps('private_key_passphrase')}
              />
            </>
          )}

          <Group justify="flex-end" mt="md">
            <Button variant="subtle" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={submitting}>
              {editTarget ? t('common.save') : t('common.create')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}
