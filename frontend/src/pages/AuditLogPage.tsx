/**
 * Audit log page — filterable list of audit events.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Table,
  Text,
  Badge,
  Group,
  Select,
  Button,
  Loader,
  Center,
  Alert,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'

import { api, ApiError } from '@/lib/api-client'
import {
  AuditLogResponseSchema,
  AuditLogActionsResponseSchema,
  type AuditLogItem,
} from '@/schemas/audit'

function AuditRow({ event }: { event: AuditLogItem }) {
  const { t } = useTranslation()

  const actorLabel =
    event.actor.type === 'user'
      ? (event.actor.email ?? event.actor.display_name ?? String(event.actor.id))
      : (event.actor.name ?? `api_key:${String(event.actor.id)}`)

  const targetLabel = [
    event.target.wallet_name,
    event.target.secret_id ? `secret:${event.target.secret_id}` : null,
  ]
    .filter(Boolean)
    .join(' / ')

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {dayjs(event.occurred_at).format('YYYY-MM-DD HH:mm:ss')}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" ff="monospace">
          {event.action}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm">{actorLabel}</Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {targetLabel}
        </Text>
      </Table.Td>
      <Table.Td>
        <Badge color={event.success ? 'green' : 'red'} size="sm">
          {event.success ? t('audit.success') : t('audit.failure')}
        </Badge>
      </Table.Td>
    </Table.Tr>
  )
}

export function AuditLogPage() {
  const { t } = useTranslation()
  const [actionFilter, setActionFilter] = useState<string | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)

  const { data: actionsData } = useQuery({
    queryKey: ['audit-actions'],
    queryFn: async () => {
      const raw = await api.get<unknown>('/audit-log/actions')
      return AuditLogActionsResponseSchema.parse(raw)
    },
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['audit-log', actionFilter, cursor],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (actionFilter) params.set('action', actionFilter)
      if (cursor) params.set('cursor', cursor)
      params.set('limit', '50')

      const path = `/audit-log?${params.toString()}`
      const raw = await api.get<unknown>(path)
      return AuditLogResponseSchema.parse(raw)
    },
  })

  const actionOptions = [
    { value: '', label: 'All actions' },
    ...(actionsData?.actions.map((a) => ({ value: a, label: a })) ?? []),
  ]

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }

  if (error) {
    const msg = error instanceof ApiError ? error.message : t('errors.serverError')
    return <Alert color="red">{msg}</Alert>
  }

  return (
    <Stack>
      <Title order={2}>{t('audit.title')}</Title>

      <Group>
        <Select
          placeholder={t('audit.action')}
          data={actionOptions}
          value={actionFilter ?? ''}
          onChange={(v) => {
            setActionFilter(v || null)
            setCursor(null)
          }}
          clearable
          w={300}
        />
        <Button
          variant="subtle"
          onClick={() => {
            setActionFilter(null)
            setCursor(null)
          }}
        >
          Reset
        </Button>
      </Group>

      {data?.events.length === 0 ? (
        <Text c="dimmed">{t('audit.noEvents')}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('audit.date')}</Table.Th>
              <Table.Th>{t('audit.action')}</Table.Th>
              <Table.Th>{t('audit.actor')}</Table.Th>
              <Table.Th>{t('audit.target')}</Table.Th>
              <Table.Th>{t('audit.success')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.events.map((e) => <AuditRow key={e.id} event={e} />)}
          </Table.Tbody>
        </Table>
      )}

      {data?.next_cursor && (
        <Group justify="center">
          <Button
            variant="outline"
            onClick={() => setCursor(data.next_cursor)}
          >
            Load more
          </Button>
        </Group>
      )}
    </Stack>
  )
}