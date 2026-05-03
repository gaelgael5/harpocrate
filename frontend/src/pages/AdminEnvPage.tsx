import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Text,
  Table,
  Badge,
  Loader,
  Center,
  Alert,
  Code,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { fetchEnvConfig } from '@/lib/adminApi'

export function AdminEnvPage() {
  const { t } = useTranslation()

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-env'],
    queryFn: fetchEnvConfig,
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

  const sensitiveSet = new Set(data?.sensitive_keys ?? [])
  const entries = Object.entries(data?.env ?? {}).sort(([a], [b]) => a.localeCompare(b))

  return (
    <Stack>
      <Title order={2}>{t('admin.env.title')}</Title>
      <Text size="sm" c="dimmed">
        {t('admin.env.subtitle')}
      </Text>

      {data?.sensitive_keys && data.sensitive_keys.length > 0 && (
        <Alert color="blue" variant="light">
          {t('admin.env.sensitiveNote', { keys: data.sensitive_keys.join(', ') })}
        </Alert>
      )}

      <Table highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('admin.env.variable')}</Table.Th>
            <Table.Th>{t('admin.env.value')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map(([key, value]) => {
            const isSecret = sensitiveSet.has(key)
            return (
              <Table.Tr key={key}>
                <Table.Td>
                  <Code>{key}</Code>
                </Table.Td>
                <Table.Td>
                  {isSecret ? (
                    <Badge color="gray" variant="outline">
                      {t('admin.env.redacted')}
                    </Badge>
                  ) : (
                    <Code>{String(value)}</Code>
                  )}
                </Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
