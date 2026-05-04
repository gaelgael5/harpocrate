import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Group,
  Badge,
  Text,
  Button,
  TextInput,
  Switch,
  Table,
  Loader,
  Center,
  Modal,
  ActionIcon,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  fetchSecretTypes,
  deleteSecretType,
} from '@/lib/adminApi'
import type { SecretTypeListItem } from '@/schemas/admin'

export function AdminSecretTypesPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [includeDeprecated, setIncludeDeprecated] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SecretTypeListItem | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['secret-types', search, includeDeprecated],
    queryFn: () => fetchSecretTypes({ q: search || undefined, include_deprecated: includeDeprecated }),
  })

  const deleteMut = useMutation({
    mutationFn: (typeUuid: string) => deleteSecretType(typeUuid),
    onSuccess: () => {
      notifications.show({ color: 'green', message: t('common.delete') + ' OK' })
      void qc.invalidateQueries({ queryKey: ['secret-types'] })
      setDeleteTarget(null)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      notifications.show({ color: 'red', message: msg })
    },
  })

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t('secret_types.title')}</Title>
        <Button onClick={() => navigate('/admin/secret-types/new')}>
          {t('secret_types.newButton')}
        </Button>
      </Group>

      <Group>
        <TextInput
          placeholder={t('secret_types.search')}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Switch
          label={t('secret_types.deprecated')}
          checked={includeDeprecated}
          onChange={(e) => setIncludeDeprecated(e.currentTarget.checked)}
        />
      </Group>

      {isLoading ? (
        <Center py="xl"><Loader /></Center>
      ) : (data?.types.length ?? 0) === 0 ? (
        <Text c="dimmed">{t('secret_types.noTypes')}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Type</Table.Th>
              <Table.Th>Sous-type</Table.Th>
              <Table.Th>Label</Table.Th>
              <Table.Th>Version</Table.Th>
              <Table.Th>Usage</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.types.map((st) => (
              <Table.Tr
                key={st.type_uuid}
                style={{ cursor: 'pointer', opacity: st.deprecated_at ? 0.6 : 1 }}
                onClick={() => navigate(`/admin/secret-types/${st.type_uuid}`)}
              >
                <Table.Td>
                  <Text size="sm" fw={500}>{st.type}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{st.sous_type}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{st.label ?? '—'}</Text>
                </Table.Td>
                <Table.Td>
                  {st.current_version ? (
                    <Badge color="brand" size="sm">
                      {t('secret_types.currentVersion', { version: st.current_version.version })}
                    </Badge>
                  ) : (
                    <Text size="xs" c="dimmed">—</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {t('secret_types.used', { count: st.used_by_secrets_count })}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Tooltip label={t('secret_types.deleteType')}>
                    <ActionIcon
                      color="red"
                      variant="subtle"
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteTarget(st)
                      }}
                    >
                      🗑
                    </ActionIcon>
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('secret_types.deleteType')}
      >
        <Stack>
          <Text>{t('secret_types.deleteTypeConfirm')}</Text>
          {deleteTarget && (
            <Text fw={700}>{deleteTarget.type}/{deleteTarget.sous_type}</Text>
          )}
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              color="red"
              loading={deleteMut.isPending}
              onClick={() => deleteTarget && deleteMut.mutate(deleteTarget.type_uuid)}
            >
              {t('common.delete')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
