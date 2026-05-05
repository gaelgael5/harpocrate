import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Stack,
  Title,
  Text,
  Button,
  Badge,
  Card,
  Group,
  Divider,
  Alert,
  Box,
  Container,
  Select,
  Loader,
  Center,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { z } from 'zod'

import { api } from '@/lib/api-client'
import { useSessionStore } from '@/stores/session'
import { LocaleSwitcher } from '@/components/LocaleSwitcher'

// ─── Schema (manifest backend) ───────────────────────────────────────────────

const ArtifactSchema = z.object({
  kind: z.string(),
  version: z.string().nullable().optional(),
  filename: z.string(),
  media_type: z.string(),
  url: z.string(),
  available: z.boolean(),
  size_bytes: z.number().nullable().optional(),
})

const DocSchema = z.object({
  filename: z.string(),
  url: z.string(),
  available: z.boolean(),
})

const SdkSchema = z.object({
  id: z.string(),
  name: z.string(),
  icon: z.string().nullable().optional(),
  status: z.enum(['available', 'planned']),
  artifacts: z.array(ArtifactSchema),
  docs: z.record(z.string(), DocSchema),
})

const ManifestSchema = z.object({
  schema_version: z.string(),
  sdks: z.array(SdkSchema),
})

type Sdk = z.infer<typeof SdkSchema>
type Artifact = z.infer<typeof ArtifactSchema>

// ─── Helpers ─────────────────────────────────────────────────────────────────

function pickDocFilename(sdk: Sdk, lang: string): string | null {
  // Préfère la langue active. Sinon prend la 1ère langue disponible.
  const docs = sdk.docs
  if (docs[lang]) return docs[lang].filename
  const fallbackLang = Object.keys(docs)[0]
  return fallbackLang ? docs[fallbackLang]!.filename : null
}

function labelForKind(kind: string): string {
  switch (kind) {
    case 'wheel':
      return 'Wheel (.whl)'
    case 'sdist':
      return 'Source (.tar.gz)'
    case 'cli':
      return 'CLI archive (.tar.gz)'
    default:
      return kind
  }
}

function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((p) => parseInt(p.replace(/[^\d]/g, ''), 10) || 0)
  const pb = b.split('.').map((p) => parseInt(p.replace(/[^\d]/g, ''), 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const xa = pa[i] ?? 0
    const xb = pb[i] ?? 0
    if (xa !== xb) return xa - xb
  }
  return 0
}

// ─── Public nav ──────────────────────────────────────────────────────────────

function PublicNav({ isAuthenticated }: { isAuthenticated: boolean }) {
  return (
    <Box
      component="nav"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: 'rgba(248,247,244,0.95)',
        backdropFilter: 'blur(8px)',
        borderBottom: '1px solid rgba(30,64,175,0.1)',
        padding: '0 5vw',
        height: 52,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <Link to="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Box
          style={{
            width: 28,
            height: 28,
            background: '#1e40af',
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.6rem',
            color: '#fff',
            letterSpacing: '-0.04em',
            flexShrink: 0,
          }}
        >
          Hp
        </Box>
        <Text
          style={{
            fontFamily: "'Cormorant Garamond', Georgia, serif",
            fontSize: '1rem',
            color: '#0a0a0a',
          }}
        >
          Harpocrate
        </Text>
      </Link>

      <Group gap="md">
        <Link
          to="/integration/api-docs"
          style={{
            textDecoration: 'none',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.68rem',
            color: 'rgba(10,10,10,0.55)',
            letterSpacing: '0.04em',
          }}
        >
          API Docs
        </Link>
        <Link
          to={isAuthenticated ? '/wallets' : '/login'}
          style={{
            textDecoration: 'none',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.68rem',
            color: '#1e40af',
            letterSpacing: '0.04em',
          }}
        >
          {isAuthenticated ? '← Dashboard' : 'Open vault →'}
        </Link>
      </Group>
    </Box>
  )
}

// ─── Markdown doc loader ──────────────────────────────────────────────────────

function MarkdownDoc({ filename }: { filename: string }) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useQuery({
    queryKey: ['sdk-doc', filename],
    queryFn: async () => {
      // Endpoint backend renvoie le markdown en text/plain.
      const resp = await fetch(`/v1/sdk/doc/${filename}`)
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      return resp.text()
    },
    retry: false,
  })

  if (isLoading) {
    return (
      <Center py="md">
        <Loader size="sm" />
      </Center>
    )
  }
  if (error) {
    return (
      <Alert color="orange" title={t('integration.docNotAvailable') || 'Documentation indisponible'}>
        {(error as Error).message}
      </Alert>
    )
  }
  if (!data) return null

  return (
    <Box
      className="markdown-doc"
      style={{
        fontSize: '0.95rem',
        lineHeight: 1.6,
      }}
    >
      <ReactMarkdown>{data}</ReactMarkdown>
    </Box>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SdkPanel({ sdk, lang }: { sdk: Sdk; lang: string }) {
  const { t } = useTranslation()

  if (sdk.status === 'planned') {
    return (
      <Card withBorder p="lg" radius="md">
        <Stack gap="md">
          <Group gap="xs">
            {sdk.icon && <Text size="xl">{sdk.icon}</Text>}
            <Title order={3}>{sdk.name}</Title>
            <Badge color="gray" variant="light">
              {t('integration.planned')}
            </Badge>
          </Group>
          <Text c="dimmed">{t('integration.plannedDesc', { sdk: sdk.name })}</Text>
        </Stack>
      </Card>
    )
  }

  const latestByKind = (() => {
    const map = new Map<string, Artifact>()
    for (const a of sdk.artifacts) {
      const existing = map.get(a.kind)
      if (
        !existing ||
        compareVersions(String(a.version ?? '0'), String(existing.version ?? '0')) > 0
      ) {
        map.set(a.kind, a)
      }
    }
    return Array.from(map.values()).sort((x, y) => x.kind.localeCompare(y.kind))
  })()

  const headlineVersion = latestByKind[0]?.version ?? '?'
  const docFilename = pickDocFilename(sdk, lang)

  return (
    <Card withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs">
            {sdk.icon && <Text size="xl">{sdk.icon}</Text>}
            <Title order={3}>{sdk.name}</Title>
            <Badge color="green" variant="light">
              {t('integration.available')}
            </Badge>
          </Group>
        </Group>

        {/* Downloads */}
        {latestByKind.length > 0 ? (
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              {t('integration.latestVersion')} <strong>{headlineVersion}</strong>
            </Text>
            <Group gap="xs">
              {latestByKind.map((a) => (
                <Button
                  key={a.filename}
                  component="a"
                  href={a.url}
                  download
                  variant="light"
                  size="sm"
                  disabled={!a.available}
                  title={!a.available ? t('integration.artifactMissing') : a.filename}
                >
                  {labelForKind(a.kind)}
                </Button>
              ))}
            </Group>
          </Stack>
        ) : (
          <Text c="dimmed" size="sm">
            {t('integration.noArtifact')}
          </Text>
        )}

        <Divider />

        {/* Documentation markdown */}
        {docFilename ? (
          <MarkdownDoc filename={docFilename} />
        ) : (
          <Text c="dimmed" size="sm">
            {t('integration.docNotAvailable')}
          </Text>
        )}
      </Stack>
    </Card>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function IntegrationPage() {
  const { t, i18n } = useTranslation()
  const user = useSessionStore((s) => s.user)
  const [selectedSdkId, setSelectedSdkId] = useState<string>('python')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['sdk-manifest'],
    queryFn: async () => {
      const raw = await api.get<unknown>('/sdk/manifest')
      return ManifestSchema.parse(raw)
    },
  })

  const sdks: Sdk[] = useMemo(() => data?.sdks ?? [], [data])
  const selectedSdk = sdks.find((s) => s.id === selectedSdkId) ?? sdks[0]
  const lang = (i18n.language ?? 'fr').slice(0, 2)

  const selectData = sdks.map((sdk) => ({
    value: sdk.id,
    label:
      sdk.status === 'planned'
        ? `${sdk.icon ?? ''} ${sdk.name} — ${t('integration.planned')}`.trim()
        : `${sdk.icon ?? ''} ${sdk.name}`.trim(),
  }))

  return (
    <Box style={{ background: 'var(--mantine-color-body)', minHeight: '100vh' }}>
      <PublicNav isAuthenticated={!!user} />
      <Container size="lg" py="xl">
        <Stack gap="xl" maw={860}>
          {/* Header — titre + sélecteur de langue */}
          <Group justify="space-between" align="flex-start">
            <div>
              <Title order={2} mb="xs">
                {t('integration.title')}
              </Title>
              <Text c="dimmed">{t('integration.subtitle')}</Text>
            </div>
            <LocaleSwitcher />
          </Group>

          <Alert color="blue" variant="light" title={t('integration.apiKeyNote.title')}>
            {t('integration.apiKeyNote.body')}
          </Alert>

          {/* Sélecteur de SDK */}
          {!isLoading && !isError && sdks.length > 0 && (
            <Stack gap="xs">
              <Text fw={500}>{t('integration.chooseSdk')}</Text>
              <Select
                data={selectData}
                value={selectedSdk?.id ?? null}
                onChange={(v) => v && setSelectedSdkId(v)}
                size="md"
                allowDeselect={false}
                searchable={false}
              />
            </Stack>
          )}

          {/* Panneau du SDK actif */}
          {isLoading && (
            <Center py="xl">
              <Loader />
            </Center>
          )}
          {isError && <Text c="red">{t('common.error')}</Text>}
          {!isLoading && !isError && selectedSdk && (
            <SdkPanel sdk={selectedSdk} lang={lang} />
          )}
          {!isLoading && !isError && sdks.length === 0 && (
            <Alert color="gray">
              {t('integration.emptyManifest') ||
                'Aucun SDK déclaré. Vérifier que releases/index.json est bien déployé.'}
            </Alert>
          )}

          <Divider />

          {/* API reference link */}
          <Group>
            <Text c="dimmed">{t('integration.apiDocsHint')}</Text>
            <Link
              to="/integration/api-docs"
              style={{ color: '#1e40af', textDecoration: 'none', fontWeight: 500 }}
            >
              {t('integration.apiDocsLink')} →
            </Link>
          </Group>
        </Stack>
      </Container>
    </Box>
  )
}
