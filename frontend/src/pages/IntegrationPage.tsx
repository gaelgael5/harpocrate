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
  Code,
  Alert,
  Box,
  Container,
  Select,
  Anchor,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import { api } from '@/lib/api-client'
import { useSessionStore } from '@/stores/session'
import { LocaleSwitcher } from '@/components/LocaleSwitcher'

// ─── Schema (manifest backend) ───────────────────────────────────────────────

const ArtifactSchema = z.object({
  key: z.string(),
  filename: z.string(),
  media_type: z.string(),
  url: z.string(),
  available: z.enum(['true', 'false']),
})

const VersionedArtifactSchema = z.object({
  key: z.string(),
  language: z.string(),
  kind: z.string(),
  version: z.string(),
  filename: z.string(),
  media_type: z.string(),
  url: z.string(),
  available: z.string(),
  size_bytes: z.number().optional(),
})

const ManifestSchema = z.object({
  artifacts: z.array(ArtifactSchema),
  all_versions: z.array(VersionedArtifactSchema).optional(),
})

type Artifact = z.infer<typeof ArtifactSchema>
type VersionedArtifact = z.infer<typeof VersionedArtifactSchema>

// ─── Catalogue SDK ────────────────────────────────────────────────────────────

type SdkStatus = 'available' | 'planned'

interface SdkCatalogEntry {
  id: string                // identifiant interne (ex: 'python', 'bash')
  label: string             // nom affiché (ex: 'Python', 'CLI Bash')
  icon: string              // emoji ou caractère
  status: SdkStatus         // 'available' ou 'planned' (placeholder UI)
  /**
   * Filtre sur les `language` du manifest pour récupérer les artefacts.
   * Si null → SDK planned, pas de download.
   */
  manifestLanguage: string | null
  /**
   * URL de la doc complète sur le wiki GitHub. Placeholder pour l'instant —
   * sera renseigné quand on publiera la doc dans le wiki du repo.
   */
  wikiUrl: string
}

// Convention wiki : `dev_sdk-{language}` (page FR par défaut, voir
// https://github.com/gaelgael5/harpocrate/wiki). Si une page EN distincte
// existe un jour, transformer `wikiUrl` en `{ fr: string; en: string }` et
// adapter `pickWikiUrl()` en bas du fichier.
const SDK_CATALOG: SdkCatalogEntry[] = [
  {
    id: 'python',
    label: 'Python',
    icon: '🐍',
    status: 'available',
    manifestLanguage: 'python',
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-python',
  },
  {
    id: 'bash',
    label: 'CLI Bash',
    icon: '🖥️',
    status: 'available',
    manifestLanguage: 'bash',
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-bash',
  },
  {
    id: 'typescript',
    label: 'TypeScript',
    icon: '🟦',
    status: 'planned',
    manifestLanguage: null,
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-typescript',
  },
  {
    id: 'javascript',
    label: 'JavaScript',
    icon: '🟨',
    status: 'planned',
    manifestLanguage: null,
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-javascript',
  },
  {
    id: 'go',
    label: 'Go',
    icon: '🦦',
    status: 'planned',
    manifestLanguage: null,
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-go',
  },
  {
    id: 'rust',
    label: 'Rust',
    icon: '🦀',
    status: 'planned',
    manifestLanguage: null,
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-rust',
  },
  {
    id: 'csharp',
    label: 'C#',
    icon: '🟪',
    status: 'planned',
    manifestLanguage: null,
    wikiUrl: 'https://github.com/gaelgael5/harpocrate/wiki/dev_sdk-csharp',
  },
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function CodeBlock({ children }: { children: string }) {
  return (
    <Box
      style={(theme) => ({
        background: theme.colors.dark[8],
        borderRadius: theme.radius.sm,
        padding: '12px 16px',
        overflowX: 'auto',
      })}
    >
      <Code color="transparent" style={{ color: '#e8e8e8', whiteSpace: 'pre', display: 'block' }}>
        {children}
      </Code>
    </Box>
  )
}

function PublicNav({ isAuthenticated }: { isAuthenticated: boolean }) {
  return (
    <Box
      component="nav"
      style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'rgba(248,247,244,0.95)', backdropFilter: 'blur(8px)',
        borderBottom: '1px solid rgba(30,64,175,0.1)',
        padding: '0 5vw', height: 52,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}
    >
      <Link to="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Box style={{
          width: 28, height: 28, background: '#1e40af', borderRadius: 6,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: "'JetBrains Mono', monospace", fontSize: '0.6rem',
          color: '#fff', letterSpacing: '-0.04em', flexShrink: 0,
        }}>
          Hp
        </Box>
        <Text style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontSize: '1rem', color: '#0a0a0a' }}>
          Harpocrate
        </Text>
      </Link>

      <Group gap="md">
        <Link to="/integration/api-docs" style={{
          textDecoration: 'none', fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.68rem', color: 'rgba(10,10,10,0.55)', letterSpacing: '0.04em',
        }}>
          API Docs
        </Link>
        <Link to={isAuthenticated ? '/wallets' : '/login'} style={{
          textDecoration: 'none', fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.68rem', color: '#1e40af', letterSpacing: '0.04em',
        }}>
          {isAuthenticated ? '← Dashboard' : 'Open vault →'}
        </Link>
      </Group>
    </Box>
  )
}

// ─── Panneaux par SDK ─────────────────────────────────────────────────────────

interface SdkPanelProps {
  sdk: SdkCatalogEntry
  artifacts: VersionedArtifact[]    // artefacts du manifest pour ce SDK (toutes versions, kinds)
  legacyArtifacts: Artifact[]       // pour fallback du download principal
}

function SdkPanel({ sdk, artifacts, legacyArtifacts }: SdkPanelProps) {
  const { t } = useTranslation()

  if (sdk.status === 'planned') {
    return (
      <Card withBorder p="lg" radius="md">
        <Stack gap="md">
          <Group gap="xs">
            <Text size="xl">{sdk.icon}</Text>
            <Title order={3}>{sdk.label}</Title>
            <Badge color="gray" variant="light">
              {t('integration.planned')}
            </Badge>
          </Group>
          <Text c="dimmed">
            {t('integration.plannedDesc', { sdk: sdk.label })}
          </Text>
          <Anchor href={sdk.wikiUrl} target="_blank" rel="noopener noreferrer">
            {t('integration.followProgress')} ↗
          </Anchor>
        </Stack>
      </Card>
    )
  }

  return (
    <Card withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs">
            <Text size="xl">{sdk.icon}</Text>
            <Title order={3}>{sdk.label}</Title>
            <Badge color="green" variant="light">
              {t('integration.available')}
            </Badge>
          </Group>
        </Group>

        <SdkDownloads artifacts={artifacts} legacyArtifacts={legacyArtifacts} sdk={sdk} />

        {sdk.id === 'python' && <PythonContent />}
        {sdk.id === 'bash' && <BashContent />}

        <Divider />

        <Anchor href={sdk.wikiUrl} target="_blank" rel="noopener noreferrer">
          {t('integration.fullDocs', { sdk: sdk.label })} ↗
        </Anchor>
      </Stack>
    </Card>
  )
}

function SdkDownloads({
  artifacts,
  legacyArtifacts,
  sdk,
}: {
  artifacts: VersionedArtifact[]
  legacyArtifacts: Artifact[]
  sdk: SdkCatalogEntry
}) {
  const { t } = useTranslation()

  // Pour chaque kind présent dans les artefacts (wheel, sdist, cli...), on
  // affiche un bouton qui pointe sur la version la plus récente disponible.
  const latestByKind = useMemo(() => {
    const map = new Map<string, VersionedArtifact>()
    for (const a of artifacts) {
      const existing = map.get(a.kind)
      if (!existing || compareVersions(a.version, existing.version) > 0) {
        map.set(a.kind, a)
      }
    }
    return Array.from(map.values()).sort((x, y) => x.kind.localeCompare(y.kind))
  }, [artifacts])

  if (latestByKind.length === 0) {
    // Fallback : si le manifest backend ne renvoie pas all_versions (vieux backend),
    // on retombe sur la liste legacy filtrée par language hardcodé.
    const fallback = legacyArtifacts.filter((a) => {
      if (sdk.id === 'python') return a.key.startsWith('python-')
      if (sdk.id === 'bash') return a.key.startsWith('cli-')
      return false
    })
    if (fallback.length === 0) {
      return (
        <Text c="dimmed" size="sm">
          {t('integration.noArtifact')}
        </Text>
      )
    }
    return (
      <Group gap="xs">
        {fallback.map((a) => (
          <Button
            key={a.key}
            component="a"
            href={a.url}
            download
            disabled={a.available !== 'true'}
            variant="light"
            size="sm"
          >
            {t('integration.download')} {a.filename}
          </Button>
        ))}
      </Group>
    )
  }

  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">
        {t('integration.latestVersion')}{' '}
        <Code>{latestByKind[0]?.version ?? '?'}</Code>
      </Text>
      <Group gap="xs">
        {latestByKind.map((a) => (
          <Button
            key={a.key}
            component="a"
            href={a.url}
            download
            variant="light"
            size="sm"
          >
            {labelForKind(a.kind)} ({a.filename})
          </Button>
        ))}
      </Group>
    </Stack>
  )
}

function labelForKind(kind: string): string {
  switch (kind) {
    case 'wheel': return 'Wheel (.whl)'
    case 'sdist': return 'Source (.tar.gz)'
    case 'cli':   return 'CLI archive (.tar.gz)'
    default:      return kind
  }
}

/** Compare deux versions semver-like (0.4.0 > 0.10.0 → false, correct natural sort). */
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

// ─── Contenu spécifique par SDK (les 3 blocs de code conservés) ──────────────

function PythonContent() {
  const { t } = useTranslation()
  return (
    <Stack gap="sm">
      <Text c="dimmed">{t('integration.python.desc')}</Text>

      <Text fw={500} mt="xs">{t('integration.python.install')}</Text>
      <CodeBlock>
        {`# Depuis le wheel téléchargé
pip install harpocrate-0.4.0-py3-none-any.whl

# Ou directement depuis le vault
pip install https://vault.yoops.org/v1/sdk/python-wheel`}
      </CodeBlock>

      <Text fw={500} mt="xs">{t('integration.python.quickstart')}</Text>
      <CodeBlock>
        {`from harpocrate import VaultClient

client = VaultClient(
    token="hrpv_1_...",           # clé API créée dans l'interface
    base_url="https://vault.yoops.org",
)

# Lire un secret (déchiffrement côté client)
api_key = client.secrets.get("ANTHROPIC_API_KEY")

# Lire un secret avec path (résout l'ID en interne via lookup)
db_pass = client.secrets.get("/users/no_email/database/postgres")

# Lister les secrets
secrets = client.secrets.list()

# Catalogue des types disponibles (P1.5)
types = client.types.list()

# Peupler un placeholder
client.secrets.populate("DATABASE_PASSWORD")`}
      </CodeBlock>

      <Text fw={500} mt="xs">{t('integration.python.env')}</Text>
      <CodeBlock>
        {`export HARPOCRATE_TOKEN="hrpv_1_..."
export HARPOCRATE_URL="https://vault.yoops.org"

python -c "from harpocrate import VaultClient; c = VaultClient(); print(c.secrets.get('MY_SECRET'))"`}
      </CodeBlock>
    </Stack>
  )
}

function BashContent() {
  const { t } = useTranslation()
  return (
    <Stack gap="sm">
      <Text c="dimmed">{t('integration.bash.desc')}</Text>

      <Text fw={500} mt="xs">{t('integration.bash.install')}</Text>
      <CodeBlock>
        {`# Télécharger et extraire
curl -fsSL https://vault.yoops.org/v1/sdk/cli-bash -o harpocrate-cli.tar.gz
tar -xzf harpocrate-cli.tar.gz

# Rendre exécutable et placer dans le PATH
chmod +x harpocrate-cli
sudo mv harpocrate-cli /usr/local/bin/

# Vérifier l'installation
harpocrate-cli --help`}
      </CodeBlock>

      <Text fw={500} mt="xs">{t('integration.bash.quickstart')}</Text>
      <CodeBlock>
        {`export HARPOCRATE_TOKEN="hrpv_1_..."
export HARPOCRATE_URL="https://vault.yoops.org"

# Lister les secrets
harpocrate-cli list

# Lire un secret
harpocrate-cli get ANTHROPIC_API_KEY

# Peupler un placeholder
harpocrate-cli populate DATABASE_PASSWORD

# Utiliser dans un script
DB_PASS=$(harpocrate-cli get DATABASE_PASSWORD)
psql "postgresql://user:\${DB_PASS}@localhost/mydb"`}
      </CodeBlock>

      <Text fw={500} mt="xs">{t('integration.bash.getOrPopulate')}</Text>
      <CodeBlock>
        {`# get-or-populate : lit la valeur, la génère si c'est un placeholder
SECRET=$(harpocrate-cli get-or-populate MY_API_KEY)
echo "Secret prêt : \${SECRET:0:4}..."`}
      </CodeBlock>
    </Stack>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function IntegrationPage() {
  const { t } = useTranslation()
  const user = useSessionStore((s) => s.user)
  const [selectedSdkId, setSelectedSdkId] = useState<string>('python')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['sdk-manifest'],
    queryFn: async () => {
      const raw = await api.get<unknown>('/sdk/manifest')
      return ManifestSchema.parse(raw)
    },
  })

  const legacyArtifacts = data?.artifacts ?? []
  const selectedSdk = SDK_CATALOG.find((s) => s.id === selectedSdkId) ?? SDK_CATALOG[0]!

  const artifactsForSelected = useMemo(() => {
    const all = data?.all_versions ?? []
    return selectedSdk.manifestLanguage
      ? all.filter((a) => a.language === selectedSdk.manifestLanguage)
      : []
  }, [data, selectedSdk])

  const selectData = SDK_CATALOG.map((sdk) => ({
    value: sdk.id,
    label:
      sdk.status === 'planned'
        ? `${sdk.icon} ${sdk.label} — ${t('integration.planned')}`
        : `${sdk.icon} ${sdk.label}`,
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
          <Stack gap="xs">
            <Text fw={500}>{t('integration.chooseSdk')}</Text>
            <Select
              data={selectData}
              value={selectedSdkId}
              onChange={(v) => v && setSelectedSdkId(v)}
              size="md"
              allowDeselect={false}
              searchable={false}
            />
          </Stack>

          {/* Panneau du SDK actif */}
          {isLoading && <Text c="dimmed">{t('common.loading')}</Text>}
          {isError && <Text c="red">{t('common.error')}</Text>}
          {!isLoading && !isError && (
            <SdkPanel
              sdk={selectedSdk}
              artifacts={artifactsForSelected}
              legacyArtifacts={legacyArtifacts}
            />
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
