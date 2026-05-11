/**
 * PostgresInfoPanel — affiche les paramètres Postgres de l'instance courante
 * dans la page Réplication, pour que l'admin puisse facilement copier les
 * bonnes valeurs côté master/standby.
 *
 * Lecture seule. Aucun side-effect côté backend (juste des SHOW / SELECT).
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Code,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { fetchPostgresInfo } from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'
import type { PostgresInfo } from '@/schemas/admin'

// Champs groupés pour l'affichage. Permet d'ajouter une section "Identité"
// vs "Réplication" vs "Paths" sans noyer l'admin dans une grosse table plate.
interface SettingGroup {
  i18nKey: string
  fields: Array<{ key: string; i18nKey: string; warnIf?: (v: string) => boolean }>
}

const SETTING_GROUPS: SettingGroup[] = [
  {
    i18nKey: 'identity',
    fields: [
      { key: 'server_version', i18nKey: 'serverVersion' },
      { key: 'port', i18nKey: 'port' },
      { key: 'listen_addresses', i18nKey: 'listenAddresses' },
    ],
  },
  {
    i18nKey: 'replication',
    fields: [
      {
        key: 'wal_level',
        i18nKey: 'walLevel',
        // Doit être 'replica' ou 'logical' — sinon le standby ne peut pas streamer.
        warnIf: (v) => v !== 'replica' && v !== 'logical',
      },
      {
        key: 'max_wal_senders',
        i18nKey: 'maxWalSenders',
        warnIf: (v) => Number(v) < 1,
      },
      { key: 'max_replication_slots', i18nKey: 'maxReplicationSlots' },
      { key: 'wal_keep_size', i18nKey: 'walKeepSize' },
      { key: 'archive_mode', i18nKey: 'archiveMode' },
    ],
  },
  {
    i18nKey: 'paths',
    fields: [
      { key: 'data_directory', i18nKey: 'dataDirectory' },
      { key: 'config_file', i18nKey: 'configFile' },
      { key: 'hba_file', i18nKey: 'hbaFile' },
    ],
  },
]

function CopyCell({ value }: { value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard API non dispo (HTTP non-secure). L'admin peut sélectionner
      // manuellement le code ci-dessous.
    }
  }

  return (
    <Group gap="xs" wrap="nowrap">
      <Code style={{ fontSize: '0.8rem' }}>{value}</Code>
      <Button size="compact-xs" variant="subtle" onClick={() => void copy()}>
        {copied ? t('common.copied') : t('common.copy')}
      </Button>
    </Group>
  )
}

export function PostgresInfoPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['admin-postgres-info'],
    queryFn: fetchPostgresInfo,
    staleTime: 60_000,
  })

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t('admin.replication.postgresInfo.title')}</Title>
          <Button
            size="xs"
            variant="subtle"
            loading={query.isFetching}
            onClick={() =>
              void qc.invalidateQueries({ queryKey: ['admin-postgres-info'] })
            }
          >
            {t('common.refresh')}
          </Button>
        </Group>

        <Text size="sm" c="dimmed">
          {t('admin.replication.postgresInfo.subtitle')}
        </Text>

        {query.isLoading && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}
        {query.error && (
          <Alert color="red">
            {query.error instanceof ApiError ? query.error.message : t('common.error')}
          </Alert>
        )}

        {query.data && <PostgresInfoTables info={query.data} />}
      </Stack>
    </Card>
  )
}

function PostgresInfoTables({ info }: { info: PostgresInfo }) {
  const { t } = useTranslation()
  return (
    <Stack gap="md">
      {/* Header : version full string + IP serveur */}
      <Group gap="xl">
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            {t('admin.replication.postgresInfo.versionFull')}
          </Text>
          <Code style={{ fontSize: '0.7rem' }}>{info.version}</Code>
        </Stack>
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            {t('admin.replication.postgresInfo.serverAddr')}
          </Text>
          <Code style={{ fontSize: '0.8rem' }}>
            {info.server_addr ?? t('admin.replication.postgresInfo.unixSocket')}
          </Code>
        </Stack>
      </Group>

      {/* Tables groupées */}
      {SETTING_GROUPS.map((group) => (
        <Stack key={group.i18nKey} gap={4}>
          <Title order={5} size="sm">
            {t(`admin.replication.postgresInfo.group.${group.i18nKey}`)}
          </Title>
          <Table withTableBorder withColumnBorders striped>
            <Table.Tbody>
              {group.fields.map((f) => {
                const value = info.settings[f.key] ?? '—'
                const warn = f.warnIf && value !== '—' ? f.warnIf(value) : false
                return (
                  <Table.Tr key={f.key}>
                    <Table.Td style={{ width: '35%' }}>
                      <Stack gap={0}>
                        <Text size="sm" fw={500}>
                          {t(`admin.replication.postgresInfo.field.${f.i18nKey}`)}
                        </Text>
                        <Text size="xs" c="dimmed" ff="monospace">
                          {f.key}
                        </Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Group gap="xs">
                        <CopyCell value={value} />
                        {warn && (
                          <Badge color="orange" size="sm" variant="light">
                            {t('admin.replication.postgresInfo.warnFlag')}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Stack>
      ))}
    </Stack>
  )
}
