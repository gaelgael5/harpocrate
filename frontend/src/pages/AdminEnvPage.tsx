/**
 * AdminEnvPage — variables d'environnement Harpocrate (LOT_12E + LOT_56).
 *
 * Affichage par thèmes (cluster, auth, crypto, backups, …) avec préfixe
 * HARPOCRATE_ masqué pour la lisibilité. Génération d'une paire AGE pour
 * les backups via un modal dédié.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
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
  Card,
  Group,
  Button,
  Modal,
  CopyButton,
  Tooltip,
  ActionIcon,
  Divider,
  ScrollArea,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import { fetchEnvConfig, generateAgeKeypair, type AgeKeypair } from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'

// ─── Mapping variable → thème ────────────────────────────────────────────────
//
// Les variables sont stockées avec le préfixe HARPOCRATE_ côté backend.
// Pour le mapping on travaille SANS le préfixe (plus court à lire ici),
// puis on l'enlève également pour l'affichage UI.

interface ThemeDef {
  id: string
  i18nKey: string  // admin.env.theme.<i18nKey>
  /** Variables (sans préfixe HARPOCRATE_) qui appartiennent à ce thème. */
  vars: readonly string[]
}

const THEMES: readonly ThemeDef[] = [
  {
    id: 'core',
    i18nKey: 'core',
    vars: ['DB_DSN', 'PUBLIC_URL', 'LOG_LEVEL', 'INSTANCE_ID', 'APPS_FILE'],
  },
  {
    id: 'auth',
    i18nKey: 'auth',
    vars: [
      'KEYCLOAK_URL',
      'KEYCLOAK_REALM',
      'KEYCLOAK_CLIENT_ID',
      'ADMIN_ROLE_NAME',
      'ADMIN_LOCAL_ENABLED',
      'ADMIN_LOCAL_USERNAME',
      'ADMIN_LOCAL_PASSWORD',
      'ADMIN_LOCAL_EMAIL',
      'ADMIN_LOCAL_DISPLAY_NAME',
    ],
  },
  {
    id: 'crypto',
    i18nKey: 'crypto',
    vars: [
      'HMAC_KEY',
      'KDF_MEMORY_KB',
      'KDF_ITERATIONS',
      'KDF_PARALLELISM',
      'RSA_KEY_SIZE_MIN',
      'PASSPHRASE_LENGTH_MIN',
    ],
  },
  {
    id: 'backups',
    i18nKey: 'backups',
    vars: [
      'AGE_PUBLIC_KEY',
      'BACKUP_LOCAL_PATH',
      'BACKUP_UPLOAD_MAX_BYTES',
    ],
  },
  {
    id: 'cluster',
    i18nKey: 'cluster',
    vars: ['REPLICATION_STRATEGY', 'PATRONI_API_URLS', 'POSTGRES_REPLICA_DSN'],
  },
  {
    id: 'sync',
    i18nKey: 'sync',
    vars: [
      'SYNC_ENABLED',
      'SYNC_CLUSTER_ID',
      'SYNC_MQTT_HOST',
      'SYNC_MQTT_PORT',
      'SYNC_MQTT_USERNAME',
      'SYNC_MQTT_PASSWORD',
      'SYNC_LOG_RETENTION_DAYS',
    ],
  },
  {
    id: 'governance',
    i18nKey: 'governance',
    vars: [
      'QUARANTINE_INACTIVITY_DAYS',
      'QUARANTINE_DURATION_DAYS',
      'AUDIT_RETENTION_DAYS',
      'WALLET_KEY_CACHE_TTL_SECONDS',
      'API_KEY_VALIDATION_CACHE_TTL_SECONDS',
    ],
  },
  {
    id: 'devmode',
    i18nKey: 'devmode',
    vars: ['DEV_MODE', 'DEV_MODE_LABEL'],
  },
]

const PREFIX = 'HARPOCRATE_'

function stripPrefix(name: string): string {
  return name.startsWith(PREFIX) ? name.slice(PREFIX.length) : name
}

/** Range les entrées env par thème. Retourne aussi les "orphelins" non mappés. */
function organizeByTheme(
  envEntries: ReadonlyArray<[string, string]>,
): { themed: Map<string, [string, string][]>; orphans: [string, string][] } {
  const themed = new Map<string, [string, string][]>()
  const knownVars = new Set<string>()
  for (const t of THEMES) {
    themed.set(t.id, [])
    for (const v of t.vars) knownVars.add(v)
  }
  const orphans: [string, string][] = []
  for (const [fullName, value] of envEntries) {
    const short = stripPrefix(fullName)
    if (knownVars.has(short)) {
      const theme = THEMES.find((t) => t.vars.includes(short))
      if (theme) {
        themed.get(theme.id)!.push([fullName, value])
      }
    } else {
      orphans.push([fullName, value])
    }
  }
  return { themed, orphans }
}

// ─── Modal résultat génération AGE ───────────────────────────────────────────

function AgeKeyResultModal({
  result,
  onClose,
}: {
  result: AgeKeypair | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  if (!result) return null
  return (
    <Modal opened onClose={onClose} title={t('admin.env.age.modalTitle')} size="lg">
      <Stack>
        <Alert color="orange" title="⚠️">
          {t('admin.env.age.warning')}
        </Alert>

        {result.applied && (
          <Alert color="green" title="✓">
            {t('admin.env.age.appliedNotice')}
          </Alert>
        )}

        <Stack gap={4}>
          <Text fw={600} size="sm">
            {t('admin.env.age.publicKeyLabel')}
          </Text>
          <Text size="xs" c="dimmed">
            {result.applied
              ? t('admin.env.age.publicKeyHintApplied')
              : t('admin.env.age.publicKeyHint')}
          </Text>
          <Group gap="xs" wrap="nowrap" align="center">
            <ScrollArea style={{ flex: 1 }} type="auto">
              <Code block style={{ wordBreak: 'break-all' }}>
                {result.public_key}
              </Code>
            </ScrollArea>
            <CopyButton value={result.public_key}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? t('common.copied') : t('common.copy')}>
                  <ActionIcon variant="light" onClick={copy}>
                    {copied ? '✓' : '📋'}
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
        </Stack>

        <Divider />

        <Stack gap={4}>
          <Text fw={600} size="sm" c="red">
            {t('admin.env.age.privateKeyLabel')}
          </Text>
          <Text size="xs" c="red.7">
            {t('admin.env.age.privateKeyHint')}
          </Text>
          <Group gap="xs" wrap="nowrap" align="center">
            <ScrollArea style={{ flex: 1 }} type="auto">
              <Code block c="red.9" style={{ wordBreak: 'break-all' }}>
                {result.private_key}
              </Code>
            </ScrollArea>
            <CopyButton value={result.private_key}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? t('common.copied') : t('common.copy')}>
                  <ActionIcon variant="light" color="red" onClick={copy}>
                    {copied ? '✓' : '📋'}
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
        </Stack>

        <Group justify="flex-end">
          <Button onClick={onClose}>{t('admin.env.age.savedItDone')}</Button>
        </Group>
      </Stack>
    </Modal>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function AdminEnvPage() {
  const { t } = useTranslation()
  const [ageResult, setAgeResult] = useState<AgeKeypair | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-env'],
    queryFn: fetchEnvConfig,
  })

  const ageKeygenMut = useMutation({
    mutationFn: generateAgeKeypair,
    onSuccess: (kp) => setAgeResult(kp),
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
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

  const sensitiveSet = new Set(data?.sensitive_keys ?? [])
  const entries = Object.entries(data?.env ?? {})
  const { themed, orphans } = organizeByTheme(entries)

  return (
    <Stack>
      <Title order={2}>{t('admin.env.title')}</Title>
      <Text size="sm" c="dimmed">
        {t('admin.env.subtitle')}
      </Text>

      {/* Bouton génération AGE */}
      <Card withBorder>
        <Stack gap="xs">
          <Group justify="space-between">
            <Stack gap={0}>
              <Text fw={600}>{t('admin.env.age.cardTitle')}</Text>
              <Text size="sm" c="dimmed">
                {t('admin.env.age.cardSubtitle')}
              </Text>
            </Stack>
            <Button
              loading={ageKeygenMut.isPending}
              onClick={() => ageKeygenMut.mutate()}
            >
              {t('admin.env.age.generateButton')}
            </Button>
          </Group>
        </Stack>
      </Card>

      {/* Tables par thème */}
      {THEMES.map((theme) => {
        const rows = themed.get(theme.id) ?? []
        if (rows.length === 0) return null
        return (
          <ThemeCard
            key={theme.id}
            title={t(`admin.env.theme.${theme.i18nKey}`)}
            entries={rows}
            sensitiveSet={sensitiveSet}
          />
        )
      })}

      {orphans.length > 0 && (
        <ThemeCard
          title={t('admin.env.theme.other')}
          entries={orphans}
          sensitiveSet={sensitiveSet}
        />
      )}

      <Alert color="blue" variant="light">
        {t('admin.env.editHint')}
      </Alert>

      <AgeKeyResultModal result={ageResult} onClose={() => setAgeResult(null)} />
    </Stack>
  )
}

function ThemeCard({
  title,
  entries,
  sensitiveSet,
}: {
  title: string
  entries: [string, string][]
  sensitiveSet: Set<string>
}) {
  const { t } = useTranslation()
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={4}>{title}</Title>
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: '40%' }}>{t('admin.env.variable')}</Table.Th>
              <Table.Th>{t('admin.env.value')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {entries.map(([key, value]) => {
              const isSecret = sensitiveSet.has(key)
              return (
                <Table.Tr key={key}>
                  <Table.Td>
                    <Code>{stripPrefix(key)}</Code>
                  </Table.Td>
                  <Table.Td>
                    {isSecret ? (
                      <Badge color="gray" variant="outline">
                        {t('admin.env.redacted')}
                      </Badge>
                    ) : (
                      <Code style={{ wordBreak: 'break-all' }}>{String(value)}</Code>
                    )}
                  </Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  )
}
