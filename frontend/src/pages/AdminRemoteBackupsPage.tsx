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
  Switch,
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
//
// Form unifié pour les 3 kinds (sftp / s3 / ftps). Les champs non-pertinents
// sont simplement masqués selon le kind sélectionné.

type Kind = 'sftp' | 's3' | 'ftps'

type S3Provider = 'aws' | 'r2' | 'b2' | 'scaleway' | 'ovh' | 'custom'

interface FormValues {
  name: string
  kind: Kind
  // SFTP + FTPS shared
  host: string
  port: number | string
  remote_path: string
  username: string
  password: string
  // SFTP only
  host_key_fingerprint: string
  auth_method: 'password' | 'private_key'
  private_key: string
  private_key_passphrase: string
  // FTPS only
  use_tls: boolean
  // S3 only
  s3_provider: S3Provider
  s3_r2_account_id: string  // pour R2 uniquement, sert à construire l'endpoint
  s3_bucket: string
  s3_region: string
  s3_endpoint_url: string  // édité directement uniquement si provider=custom
  s3_prefix: string
  s3_path_style: boolean   // édité directement uniquement si provider=custom
  s3_access_key_id: string
  s3_secret_access_key: string
}

const DEFAULT_FORM: FormValues = {
  name: '',
  kind: 'sftp',
  host: '',
  port: 22,
  remote_path: '/',
  username: '',
  password: '',
  host_key_fingerprint: '',
  auth_method: 'password',
  private_key: '',
  private_key_passphrase: '',
  use_tls: true,
  s3_provider: 'aws',
  s3_r2_account_id: '',
  s3_bucket: '',
  s3_region: 'us-east-1',
  s3_endpoint_url: '',
  s3_prefix: '',
  s3_path_style: false,
  s3_access_key_id: '',
  s3_secret_access_key: '',
}

// ─── Mapping providers S3 → endpoint + path-style ────────────────────────────

interface S3ProviderSpec {
  label: string
  /** true si l'utilisateur doit saisir l'endpoint à la main (custom uniquement). */
  endpointEditable: boolean
  /** Construit l'URL d'endpoint à partir des inputs utilisateur. Vide pour AWS. */
  buildEndpoint: (region: string, accountId: string) => string
  defaultRegion: string
  regionPlaceholder: string
  pathStyle: boolean
  /** true si on doit afficher le champ Account ID (R2 uniquement). */
  needsAccountId: boolean
}

const S3_PROVIDERS: Record<S3Provider, S3ProviderSpec> = {
  aws: {
    label: 'AWS S3',
    endpointEditable: false,
    buildEndpoint: () => '',  // AWS utilise l'endpoint par défaut du SDK
    defaultRegion: 'us-east-1',
    regionPlaceholder: 'ex: eu-west-3, us-east-1, ap-southeast-1',
    pathStyle: false,
    needsAccountId: false,
  },
  r2: {
    label: 'Cloudflare R2',
    endpointEditable: false,
    buildEndpoint: (_region, accountId) =>
      accountId.trim() ? `https://${accountId.trim()}.r2.cloudflarestorage.com` : '',
    defaultRegion: 'auto',
    regionPlaceholder: 'auto',
    pathStyle: true,
    needsAccountId: true,
  },
  b2: {
    label: 'Backblaze B2',
    endpointEditable: false,
    buildEndpoint: (region) =>
      region.trim() ? `https://s3.${region.trim()}.backblazeb2.com` : '',
    defaultRegion: 'eu-central-003',
    regionPlaceholder: 'ex: us-west-001, eu-central-003',
    pathStyle: true,
    needsAccountId: false,
  },
  scaleway: {
    label: 'Scaleway Object Storage',
    endpointEditable: false,
    buildEndpoint: (region) =>
      region.trim() ? `https://s3.${region.trim()}.scw.cloud` : '',
    defaultRegion: 'fr-par',
    regionPlaceholder: 'fr-par, nl-ams, pl-waw',
    pathStyle: false,
    needsAccountId: false,
  },
  ovh: {
    label: 'OVH Object Storage',
    endpointEditable: false,
    buildEndpoint: (region) =>
      region.trim() ? `https://s3.${region.trim()}.io.cloud.ovh.net` : '',
    defaultRegion: 'gra',
    regionPlaceholder: 'gra, sbg, bhs, waw, de',
    pathStyle: false,
    needsAccountId: false,
  },
  custom: {
    label: 'Autre (S3-compatible custom)',
    endpointEditable: true,
    buildEndpoint: () => '',  // saisi à la main
    defaultRegion: 'us-east-1',
    regionPlaceholder: 'région de ton service',
    pathStyle: true,
    needsAccountId: false,
  },
}

/** Détecte le provider S3 depuis un endpoint connu (pour reload d'une connexion existante). */
function detectS3Provider(endpoint: string): S3Provider {
  const e = endpoint.toLowerCase().trim()
  if (!e || e.endsWith('.amazonaws.com')) return 'aws'
  if (e.includes('.r2.cloudflarestorage.com')) return 'r2'
  if (e.includes('.backblazeb2.com')) return 'b2'
  if (e.includes('.scw.cloud')) return 'scaleway'
  if (e.includes('.io.cloud.ovh.net')) return 'ovh'
  return 'custom'
}

/** Extrait l'account_id depuis une endpoint R2 (https://<id>.r2.cloudflarestorage.com). */
function extractR2AccountId(endpoint: string): string {
  const m = endpoint.match(/^https?:\/\/([^.]+)\.r2\.cloudflarestorage\.com\/?$/i)
  return m?.[1] ?? ''
}

function buildPayload(values: FormValues): RemoteBackupCreatePayload {
  const name = values.name.trim()
  if (values.kind === 'sftp') {
    const config: Record<string, unknown> = {
      host: values.host.trim(),
      port: typeof values.port === 'number' ? values.port : parseInt(String(values.port), 10) || 22,
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
    return { name, kind: 'sftp', config, credentials }
  }
  if (values.kind === 'ftps') {
    const config: Record<string, unknown> = {
      host: values.host.trim(),
      port: typeof values.port === 'number' ? values.port : parseInt(String(values.port), 10) || 21,
      remote_path: values.remote_path.trim() || '/',
      use_tls: values.use_tls,
    }
    return {
      name,
      kind: 'ftps',
      config,
      credentials: {
        username: values.username.trim(),
        password: values.password,
      },
    }
  }
  // s3 — l'endpoint et le path-style sont dérivés du provider sélectionné
  const spec = S3_PROVIDERS[values.s3_provider]
  const endpoint = spec.endpointEditable
    ? values.s3_endpoint_url.trim()
    : spec.buildEndpoint(values.s3_region, values.s3_r2_account_id)
  const config: Record<string, unknown> = {
    bucket: values.s3_bucket.trim(),
    region: values.s3_region.trim(),
    path_style: spec.endpointEditable ? values.s3_path_style : spec.pathStyle,
  }
  if (endpoint) {
    config.endpoint_url = endpoint
  }
  if (values.s3_prefix.trim()) {
    config.prefix = values.s3_prefix.trim()
  }
  return {
    name,
    kind: 's3',
    config,
    credentials: {
      access_key_id: values.s3_access_key_id.trim(),
      secret_access_key: values.s3_secret_access_key,
    },
  }
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

      <ConnectionFormModal
        // Force le remount à chaque changement de cible : useForm n'évalue
        // initialValues qu'au premier mount, donc sans `key` le formulaire
        // resterait sur DEFAULT_FORM quand on clique "Modifier" après une
        // ouverture en mode "Créer".
        key={editTarget?.id ?? 'create'}
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

// ─── Modal create/edit (3 kinds) ─────────────────────────────────────────────

function ConnectionFormModal({
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

  const form = useForm<FormValues>({
    initialValues: editTarget
      ? {
          ...DEFAULT_FORM,
          name: editTarget.name,
          kind: editTarget.kind,
          // Champs SFTP/FTPS
          host: String(editTarget.config.host ?? ''),
          port:
            typeof editTarget.config.port === 'number'
              ? editTarget.config.port
              : editTarget.kind === 'ftps'
                ? 21
                : 22,
          remote_path: String(editTarget.config.remote_path ?? '/'),
          host_key_fingerprint: String(editTarget.config.host_key_fingerprint ?? ''),
          use_tls:
            typeof editTarget.config.use_tls === 'boolean'
              ? editTarget.config.use_tls
              : true,
          // Champs S3 — détecte le provider depuis l'endpoint stocké
          s3_provider: detectS3Provider(String(editTarget.config.endpoint_url ?? '')),
          s3_r2_account_id: extractR2AccountId(String(editTarget.config.endpoint_url ?? '')),
          s3_bucket: String(editTarget.config.bucket ?? ''),
          s3_region: String(editTarget.config.region ?? 'us-east-1'),
          s3_endpoint_url: String(editTarget.config.endpoint_url ?? ''),
          s3_prefix: String(editTarget.config.prefix ?? ''),
          s3_path_style: Boolean(editTarget.config.path_style ?? false),
        }
      : DEFAULT_FORM,
    validate: {
      name: (v) => (!v.trim() ? t('common.required') : null),
      host: (v, values) =>
        values.kind !== 's3' && !v.trim() ? t('common.required') : null,
      username: (v, values) =>
        values.kind !== 's3' && !v.trim() ? t('common.required') : null,
      password: (v, values) =>
        values.kind === 'sftp' && values.auth_method === 'password' && !editTarget && !v
          ? t('common.required')
          : values.kind === 'ftps' && !editTarget && !v
            ? t('common.required')
            : null,
      private_key: (v, values) =>
        values.kind === 'sftp' &&
        values.auth_method === 'private_key' &&
        !editTarget &&
        !v
          ? t('common.required')
          : null,
      s3_bucket: (v, values) =>
        values.kind === 's3' && !v.trim() ? t('common.required') : null,
      s3_region: (v, values) =>
        values.kind === 's3' && !v.trim() ? t('common.required') : null,
      s3_access_key_id: (v, values) =>
        values.kind === 's3' && !editTarget && !v.trim() ? t('common.required') : null,
      s3_secret_access_key: (v, values) =>
        values.kind === 's3' && !editTarget && !v ? t('common.required') : null,
      s3_r2_account_id: (v, values) =>
        values.kind === 's3' && values.s3_provider === 'r2' && !v.trim()
          ? t('common.required')
          : null,
    },
  })

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={editTarget ? t('admin.remoteBackups.editTitle') : t('admin.remoteBackups.addTitle')}
      size="lg"
    >
      <form onSubmit={form.onSubmit((v) => onSubmit(buildPayload(v)))}>
        <Stack gap="sm">
          <TextInput
            label={t('admin.remoteBackups.fieldName')}
            description={t('admin.remoteBackups.fieldNameHint')}
            required
            {...form.getInputProps('name')}
          />
          <Select
            label={t('admin.remoteBackups.fieldKind')}
            data={[
              { value: 'sftp', label: 'SFTP (SSH)' },
              { value: 's3', label: 'S3-compatible (AWS / R2 / B2 / Scaleway / OVH)' },
              { value: 'ftps', label: 'FTPS' },
            ]}
            {...form.getInputProps('kind')}
            allowDeselect={false}
            disabled={editTarget !== null}
            description={editTarget ? t('admin.remoteBackups.kindLockedHint') : undefined}
          />

          {form.values.kind === 'sftp' && <SftpFields form={form} editing={editTarget !== null} />}
          {form.values.kind === 'ftps' && <FtpsFields form={form} editing={editTarget !== null} />}
          {form.values.kind === 's3' && <S3Fields form={form} editing={editTarget !== null} />}

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

function SftpFields({
  form,
  editing,
}: {
  form: ReturnType<typeof useForm<FormValues>>
  editing: boolean
}) {
  const { t } = useTranslation()
  return (
    <>
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
          description={editing ? t('admin.remoteBackups.passwordEditHint') : undefined}
          {...form.getInputProps('password')}
        />
      ) : (
        <>
          <Textarea
            label={t('admin.remoteBackups.fieldPrivateKey')}
            description={editing ? t('admin.remoteBackups.privateKeyEditHint') : undefined}
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
    </>
  )
}

function FtpsFields({
  form,
  editing,
}: {
  form: ReturnType<typeof useForm<FormValues>>
  editing: boolean
}) {
  const { t } = useTranslation()
  return (
    <>
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
      <Switch
        label={t('admin.remoteBackups.fieldUseTls')}
        description={t('admin.remoteBackups.fieldUseTlsHint')}
        {...form.getInputProps('use_tls', { type: 'checkbox' })}
      />
      <TextInput
        label={t('admin.remoteBackups.fieldUsername')}
        required
        {...form.getInputProps('username')}
      />
      <PasswordInput
        label={t('admin.remoteBackups.fieldPassword')}
        description={editing ? t('admin.remoteBackups.passwordEditHint') : undefined}
        {...form.getInputProps('password')}
      />
    </>
  )
}

function S3Fields({
  form,
  editing,
}: {
  form: ReturnType<typeof useForm<FormValues>>
  editing: boolean
}) {
  const { t } = useTranslation()
  const provider: S3Provider = form.values.s3_provider
  const spec = S3_PROVIDERS[provider]

  return (
    <>
      <Select
        label={t('admin.remoteBackups.fieldS3Provider')}
        description={t('admin.remoteBackups.fieldS3ProviderHint')}
        data={Object.entries(S3_PROVIDERS).map(([value, s]) => ({
          value,
          label: s.label,
        }))}
        allowDeselect={false}
        {...form.getInputProps('s3_provider')}
        onChange={(v) => {
          if (!v) return
          const next = v as S3Provider
          const nextSpec = S3_PROVIDERS[next]
          form.setFieldValue('s3_provider', next)
          // Préfille la région avec le défaut du provider sélectionné
          // sauf si l'utilisateur a déjà saisi quelque chose de pertinent
          form.setFieldValue('s3_region', nextSpec.defaultRegion)
        }}
      />

      {spec.needsAccountId && (
        <TextInput
          label={t('admin.remoteBackups.fieldS3R2AccountId')}
          description={t('admin.remoteBackups.fieldS3R2AccountIdHint')}
          placeholder="abc123def456..."
          required
          {...form.getInputProps('s3_r2_account_id')}
        />
      )}

      <TextInput
        label={t('admin.remoteBackups.fieldS3Bucket')}
        required
        {...form.getInputProps('s3_bucket')}
      />

      <Group grow>
        <TextInput
          label={t('admin.remoteBackups.fieldS3Region')}
          placeholder={spec.regionPlaceholder}
          required
          {...form.getInputProps('s3_region')}
        />
        <TextInput
          label={t('admin.remoteBackups.fieldS3Prefix')}
          description={t('admin.remoteBackups.fieldS3PrefixHint')}
          {...form.getInputProps('s3_prefix')}
        />
      </Group>

      {spec.endpointEditable && (
        <>
          <TextInput
            label={t('admin.remoteBackups.fieldS3Endpoint')}
            description={t('admin.remoteBackups.fieldS3EndpointHint')}
            placeholder="https://s3.example.com"
            required
            {...form.getInputProps('s3_endpoint_url')}
          />
          <Switch
            label={t('admin.remoteBackups.fieldS3PathStyle')}
            description={t('admin.remoteBackups.fieldS3PathStyleHint')}
            {...form.getInputProps('s3_path_style', { type: 'checkbox' })}
          />
        </>
      )}

      <TextInput
        label={t('admin.remoteBackups.fieldS3AccessKeyId')}
        required
        {...form.getInputProps('s3_access_key_id')}
      />
      <PasswordInput
        label={t('admin.remoteBackups.fieldS3SecretAccessKey')}
        description={editing ? t('admin.remoteBackups.passwordEditHint') : undefined}
        {...form.getInputProps('s3_secret_access_key')}
      />
    </>
  )
}
