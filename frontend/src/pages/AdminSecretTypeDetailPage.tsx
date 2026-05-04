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
  Textarea,
  Switch,
  Table,
  Loader,
  Center,
  Modal,
  Alert,
  Divider,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'

import {
  fetchSecretType,
  addSecretTypeVersion,
  deleteSecretTypeVersion,
  validateJsonSchema,
} from '@/lib/adminApi'
import { JsonEditorMonaco } from '@/components/JsonEditorMonaco'
type SchemaVersionFullLocal = {
  version_uuid: string
  version: number
  schema_data: Record<string, unknown>
  schema_ui: Record<string, unknown>
  notes: string | null
  created_at: string
}

export function AdminSecretTypeDetailPage() {
  const { t } = useTranslation()
  const { typeUuid } = useParams<{ typeUuid: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [newVersionOpen, setNewVersionOpen] = useState(false)
  const [selectedVersion, setSelectedVersion] = useState<SchemaVersionFullLocal | null>(null)
  const [deleteVersionTarget, setDeleteVersionTarget] = useState<SchemaVersionFullLocal | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['secret-type', typeUuid],
    queryFn: () => fetchSecretType(typeUuid!),
    enabled: !!typeUuid,
  })

  const deleteVersionMut = useMutation({
    mutationFn: (versionUuid: string) =>
      deleteSecretTypeVersion(typeUuid!, versionUuid),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('common.delete') + ' OK' })
      void qc.invalidateQueries({ queryKey: ['secret-type', typeUuid] })
      setDeleteVersionTarget(null)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  if (isLoading) {
    return <Center py="xl"><Loader /></Center>
  }

  if (!data) {
    return <Text c="red">Not found</Text>
  }

  const isCurrentVersion = (v: SchemaVersionFullLocal) =>
    data.current_version?.version_uuid === v.version_uuid

  return (
    <Stack>
      <Group>
        <Button variant="subtle" onClick={() => navigate('/admin/secret-types')}>
          ← {t('common.back')}
        </Button>
        <Title order={2}>
          {data.type}/{data.sous_type}
          {data.deprecated_at && (
            <Badge color="orange" ml="xs">{t('secret_types.deprecated')}</Badge>
          )}
        </Title>
      </Group>

      <Card withBorder>
        <Stack gap="xs">
          {data.label && <Text fw={500}>{data.label}</Text>}
          {data.description && <Text c="dimmed">{data.description}</Text>}
          <Text size="xs" c="dimmed">
            {t('secret_types.used', { count: data.used_by_secrets_count })}
          </Text>
        </Stack>
      </Card>

      <Divider />

      <Group justify="space-between">
        <Title order={4}>{t('secret_types.versionsTitle')}</Title>
        <Button onClick={() => setNewVersionOpen(true)}>
          + {t('secret_types.newVersionTitle')}
        </Button>
      </Group>

      {data.all_versions.length === 0 ? (
        <Text c="dimmed">{t('secret_types.noVersions')}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Version</Table.Th>
              <Table.Th>Date</Table.Th>
              <Table.Th>Notes</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.all_versions.map((v) => (
              <Table.Tr
                key={v.version_uuid}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedVersion(v as SchemaVersionFullLocal)}
              >
                <Table.Td>
                  <Group gap="xs">
                    <Badge color="blue">{t('secret_types.versionN', { n: v.version })}</Badge>
                    {isCurrentVersion(v as SchemaVersionFullLocal) && (
                      <Badge color="green" size="xs">{t('secret_types.currentBadge')}</Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{dayjs(v.created_at).format('YYYY-MM-DD HH:mm')}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{v.notes ?? '—'}</Text>
                </Table.Td>
                <Table.Td>
                  {!isCurrentVersion(v as SchemaVersionFullLocal) && (
                    <Button
                      size="xs"
                      color="red"
                      variant="subtle"
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteVersionTarget(v as SchemaVersionFullLocal)
                      }}
                    >
                      🗑
                    </Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {/* View version modal */}
      <Modal
        opened={selectedVersion !== null}
        onClose={() => setSelectedVersion(null)}
        title={selectedVersion ? t('secret_types.viewVersion', { n: selectedVersion.version }) : ''}
        size="xl"
      >
        {selectedVersion && (
          <Stack>
            <Text fw={500}>{t('secret_types.schemaDataLabel')}</Text>
            <JsonEditorMonaco
              value={JSON.stringify(selectedVersion.schema_data, null, 2)}
              readOnly
              height="300px"
            />
            <Text fw={500}>{t('secret_types.schemaUiLabel')}</Text>
            <JsonEditorMonaco
              value={JSON.stringify(selectedVersion.schema_ui, null, 2)}
              readOnly
              height="200px"
            />
            {selectedVersion.notes && (
              <Text size="sm" c="dimmed">{selectedVersion.notes}</Text>
            )}
          </Stack>
        )}
      </Modal>

      {/* New version modal */}
      {newVersionOpen && (
        <NewVersionModal
          typeUuid={typeUuid!}
          previousVersion={data.all_versions[0] as SchemaVersionFullLocal | undefined}
          onClose={() => setNewVersionOpen(false)}
          onSuccess={() => {
            setNewVersionOpen(false)
            void qc.invalidateQueries({ queryKey: ['secret-type', typeUuid] })
          }}
        />
      )}

      {/* Delete version modal */}
      <Modal
        opened={deleteVersionTarget !== null}
        onClose={() => setDeleteVersionTarget(null)}
        title={t('secret_types.deleteVersion')}
      >
        <Stack>
          <Text>{t('secret_types.deleteVersionConfirm')}</Text>
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setDeleteVersionTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              color="red"
              loading={deleteVersionMut.isPending}
              onClick={() =>
                deleteVersionTarget && deleteVersionMut.mutate(deleteVersionTarget.version_uuid)
              }
            >
              {t('common.delete')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}


function NewVersionModal({
  typeUuid,
  previousVersion,
  onClose,
  onSuccess,
}: {
  typeUuid: string
  previousVersion: SchemaVersionFullLocal | undefined
  onClose: () => void
  onSuccess: () => void
}) {
  const { t } = useTranslation()

  const [schemaData, setSchemaData] = useState(
    previousVersion
      ? JSON.stringify(previousVersion.schema_data, null, 2)
      : '{}'
  )
  const [schemaUi, setSchemaUi] = useState(
    previousVersion
      ? JSON.stringify(previousVersion.schema_ui, null, 2)
      : '{}'
  )
  const [notes, setNotes] = useState('')
  const [setAsCurrent, setSetAsCurrent] = useState(true)
  const [validateResult, setValidateResult] = useState<{ valid: boolean; error?: string } | null>(null)

  const validateMut = useMutation({
    mutationFn: async () => {
      const parsed = JSON.parse(schemaData) as Record<string, unknown>
      return validateJsonSchema(parsed)
    },
    onSuccess: (result) => setValidateResult(result),
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      setValidateResult({ valid: false, error: msg })
    },
  })

  const addMut = useMutation({
    mutationFn: async () => {
      const parsedData = JSON.parse(schemaData) as Record<string, unknown>
      const parsedUi = JSON.parse(schemaUi) as Record<string, unknown>
      return addSecretTypeVersion(typeUuid, {
        schema_data: parsedData,
        schema_ui: parsedUi,
        notes: notes || undefined,
        set_as_current: setAsCurrent,
      })
    },
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('secret_types.addVersionSuccess') })
      onSuccess()
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  return (
    <Modal
      opened
      onClose={onClose}
      title={t('secret_types.newVersionTitle')}
      size="xl"
    >
      <Stack>
        {previousVersion && (
          <Text size="xs" c="dimmed">
            {t('secret_types.prefillFromPrevious', { n: previousVersion.version })}
          </Text>
        )}

        <Group justify="space-between">
          <Text fw={500}>{t('secret_types.schemaDataLabel')}</Text>
          <Button
            variant="outline"
            size="xs"
            loading={validateMut.isPending}
            onClick={() => validateMut.mutate()}
          >
            {t('secret_types.validateButton')}
          </Button>
        </Group>
        <JsonEditorMonaco value={schemaData} onChange={setSchemaData} height="300px" />
        {validateResult && (
          <Alert color={validateResult.valid ? 'green' : 'red'}>
            {validateResult.valid
              ? t('secret_types.validSchema')
              : t('secret_types.invalidSchema', { error: validateResult.error })}
          </Alert>
        )}

        <Text fw={500}>{t('secret_types.schemaUiLabel')}</Text>
        <JsonEditorMonaco value={schemaUi} onChange={setSchemaUi} height="200px" />

        <Textarea
          label={t('secret_types.notesLabel')}
          value={notes}
          onChange={(e) => setNotes(e.currentTarget.value)}
          autosize
          minRows={2}
        />

        <Switch
          label={t('secret_types.setAsCurrent')}
          checked={setAsCurrent}
          onChange={(e) => setSetAsCurrent(e.currentTarget.checked)}
        />

        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>{t('common.cancel')}</Button>
          <Button loading={addMut.isPending} onClick={() => addMut.mutate()}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
