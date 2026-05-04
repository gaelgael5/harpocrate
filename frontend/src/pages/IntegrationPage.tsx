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
  SimpleGrid,
  ThemeIcon,
  Box,
  Container,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import { api } from '@/lib/api-client'
import { useSessionStore } from '@/stores/session'

// ─── Schema ──────────────────────────────────────────────────────────────────

const ArtifactSchema = z.object({
  key: z.string(),
  filename: z.string(),
  media_type: z.string(),
  url: z.string(),
  available: z.enum(['true', 'false']),
})

const ManifestSchema = z.object({
  artifacts: z.array(ArtifactSchema),
})

type Artifact = z.infer<typeof ArtifactSchema>

// ─── Helpers ─────────────────────────────────────────────────────────────────

const ARTIFACT_META: Record<string, { label: string; icon: string; tech: string }> = {
  'python-wheel': { label: 'Python wheel (.whl)', icon: '🐍', tech: 'python' },
  'python-sdist': { label: 'Python sdist (.tar.gz)', icon: '🐍', tech: 'python' },
  'cli-bash':     { label: 'CLI Bash (.tar.gz)',   icon: '🖥️',  tech: 'bash'   },
}

function downloadUrl(artifact: Artifact): string {
  return artifact.url
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const { t } = useTranslation()
  const available = artifact.available === 'true'
  const meta = ARTIFACT_META[artifact.key]

  return (
    <Card withBorder p="md" radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text size="xl">{meta?.icon ?? '📦'}</Text>
          <Text fw={600}>{meta?.label ?? artifact.filename}</Text>
        </Group>
        <Badge color={available ? 'green' : 'gray'} variant="light">
          {available ? t('integration.available') : t('integration.unavailable')}
        </Badge>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        {artifact.filename}
      </Text>
      <Button
        component="a"
        href={downloadUrl(artifact)}
        download
        disabled={!available}
        variant="light"
        size="sm"
        fullWidth
      >
        {t('integration.download')}
      </Button>
    </Card>
  )
}

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

// ─── Public nav ──────────────────────────────────────────────────────────────

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

// ─── Page ────────────────────────────────────────────────────────────────────

export function IntegrationPage() {
  const { t } = useTranslation()
  const user = useSessionStore((s) => s.user)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['sdk-manifest'],
    queryFn: async () => {
      const raw = await api.get<unknown>('/sdk/manifest')
      return ManifestSchema.parse(raw)
    },
  })

  const artifacts = data?.artifacts ?? []

  return (
    <Box style={{ background: 'var(--mantine-color-body)', minHeight: '100vh' }}>
      <PublicNav isAuthenticated={!!user} />
    <Container size="lg" py="xl">
    <Stack gap="xl" maw={860}>
      <div>
        <Title order={2} mb="xs">
          {t('integration.title')}
        </Title>
        <Text c="dimmed">{t('integration.subtitle')}</Text>
      </div>

      <Alert color="blue" variant="light" title={t('integration.apiKeyNote.title')}>
        {t('integration.apiKeyNote.body')}
      </Alert>

      {/* Downloads */}
      <div>
        <Title order={3} mb="md">
          {t('integration.downloads')}
        </Title>
        {isLoading && <Text c="dimmed">{t('common.loading')}</Text>}
        {isError && <Text c="red">{t('common.error')}</Text>}
        {!isLoading && !isError && (
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            {artifacts.map((a) => (
              <ArtifactCard key={a.key} artifact={a} />
            ))}
          </SimpleGrid>
        )}
      </div>

      <Divider />

      {/* Python SDK */}
      <Stack gap="sm">
        <Group gap="xs">
          <ThemeIcon variant="light" color="blue" size="lg" radius="md">
            🐍
          </ThemeIcon>
          <Title order={3}>{t('integration.python.title')}</Title>
        </Group>
        <Text c="dimmed">{t('integration.python.desc')}</Text>

        <Text fw={500} mt="xs">{t('integration.python.install')}</Text>
        <CodeBlock>
          {`# Depuis le wheel téléchargé
pip install harpocrate-0.2.0-py3-none-any.whl

# Ou directement depuis le vault (remplacer l'URL)
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

# Lister les secrets
secrets = client.secrets.list()

# Peupler un placeholder
client.secrets.populate("DATABASE_PASSWORD")

# Peupler tous les placeholders d'un coup
results = client.secrets.populate_all()`}
        </CodeBlock>

        <Text fw={500} mt="xs">{t('integration.python.env')}</Text>
        <CodeBlock>
          {`export HARPOCRATE_TOKEN="hrpv_1_..."
export HARPOCRATE_URL="https://vault.yoops.org"

python -c "from harpocrate import VaultClient; c = VaultClient(); print(c.secrets.get('MY_SECRET'))"`}
        </CodeBlock>
      </Stack>

      <Divider />

      {/* CLI Bash */}
      <Stack gap="sm">
        <Group gap="xs">
          <ThemeIcon variant="light" color="gray" size="lg" radius="md">
            🖥️
          </ThemeIcon>
          <Title order={3}>{t('integration.bash.title')}</Title>
        </Group>
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

# Peupler tous les placeholders
harpocrate-cli populate-all

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

      <Divider />

      {/* API reference link */}
      <Group>
        <Text c="dimmed">{t('integration.apiDocsHint')}</Text>
        <Link to="/integration/api-docs" style={{ color: '#1e40af', textDecoration: 'none', fontWeight: 500 }}>
          {t('integration.apiDocsLink')} →
        </Link>
      </Group>
    </Stack>
    </Container>
    </Box>
  )
}
