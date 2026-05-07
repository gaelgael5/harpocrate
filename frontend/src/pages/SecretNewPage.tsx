/**
 * New secret page — creates a manual secret by encrypting the value with wallet_key.
 */
import { useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  Stack,
  Title,
  TextInput,
  Textarea,
  Button,
  Alert,
  Group,
  Select,
  Text,
  Divider,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { useQueryClient, useQuery } from '@tanstack/react-query'

import { api, ApiError } from '@/lib/api-client'
import { aesGcmEncrypt } from '@/crypto/aes-gcm'
import { rsaOaepDecrypt } from '@/crypto/rsa-oaep'
import { fromBase64, toBase64, textToBytes } from '@/crypto/helpers'
import {
  generateSshEd25519Keypair,
  generateWireguardKeypair,
} from '@/crypto/keypair-gen'
import { useCryptoStore } from '@/stores/crypto'
import { SecretCreateResponseSchema } from '@/schemas/secrets'
import { MyGrantResponseSchema } from '@/schemas/grants'
import { TypedSecretForm } from '@/components/TypedSecretForm'
import { fetchSecretTypes, fetchSecretType } from '@/lib/adminApi'

interface FormValues {
  name: string
  description: string
  tags: string
  value: string
}

// Aligné sur backend/app/services/secret_paths.py:validate_secret_name
// - sans '/' : [A-Za-z0-9_.-]+
// - avec '/' : segments [a-zA-Z0-9@._-]+, optionnellement '/'-préfixé, pas de '/' final, pas de '//'
const NAME_RE_ROOT = /^[A-Za-z0-9_.-]+$/
const NAME_RE_PATH = /^\/?([a-zA-Z0-9@._-]+\/)*[a-zA-Z0-9@._-]+$/

function validateSecretName(name: string): string | null {
  const stripped = name.trim()
  if (!stripped) return 'common.required'
  if (stripped.length > 256) return 'Max 256 characters'
  if (!stripped.includes('/')) {
    return NAME_RE_ROOT.test(stripped) ? null : 'secrets.nameHint'
  }
  if (stripped.endsWith('/')) return 'secrets.nameTrailingSlash'
  if (stripped.includes('//')) return 'secrets.nameDoubleSlash'
  return NAME_RE_PATH.test(stripped) ? null : 'secrets.namePathHint'
}

export function SecretNewPage() {
  const { t } = useTranslation()
  const { walletId } = useParams<{ walletId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const prefixPath = (location.state as { prefixPath?: string } | null)?.prefixPath ?? ''
  const queryClient = useQueryClient()
  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey)
  const getCachedKey = useCryptoStore((s) => s.getWalletKey)
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey)

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [selectedTypeUuid, setSelectedTypeUuid] = useState<string | null>(null)
  const [selectedVersionUuid, setSelectedVersionUuid] = useState<string | null>(null)
  const [typedFormData, setTypedFormData] = useState<object>({})

  const { data: typesData } = useQuery({
    queryKey: ['secret-types-public'],
    queryFn: () => fetchSecretTypes(),
  })

  const { data: selectedTypeDetail } = useQuery({
    queryKey: ['secret-type-public', selectedTypeUuid],
    queryFn: () => fetchSecretType(selectedTypeUuid!),
    enabled: !!selectedTypeUuid,
  })

  const form = useForm<FormValues>({
    initialValues: { name: prefixPath, description: '', tags: '', value: '' },
    validate: {
      name: (v) => {
        const errKey = validateSecretName(v)
        return errKey ? t(errKey) : null
      },
      value: (v) =>
        !selectedTypeUuid && !v.trim() ? t('common.required') : null,
    },
  })

  async function getWalletKey(): Promise<Uint8Array> {
    const cached = getCachedKey(walletId ?? '')
    if (cached) return cached
    if (!rsaPrivateKey) throw new Error(t('errors.cryptoRequired'))

    // Fetch my grant to get encrypted_wallet_key
    const raw = await api.get<unknown>(`/wallets/${walletId ?? ''}/my-grant`)
    const grant = MyGrantResponseSchema.parse(raw)
    const encKey = fromBase64(grant.encrypted_wallet_key)
    const key = await rsaOaepDecrypt(encKey, rsaPrivateKey)
    cacheWalletKey(walletId ?? '', key)
    return key
  }

  async function handleSubmit(values: FormValues) {
    if (!rsaPrivateKey) {
      setSubmitError(t('errors.cryptoRequired'))
      return
    }

    setIsSubmitting(true)
    setSubmitError(null)

    try {
      const walletKey = await getWalletKey()

      // Encrypt the value — typed form uses JSON, plain textarea uses raw text
      const rawValue =
        selectedTypeUuid && selectedVersionUuid
          ? JSON.stringify(typedFormData)
          : values.value
      const plainBytes = textToBytes(rawValue)
      const encValue = await aesGcmEncrypt(plainBytes, walletKey)

      const tags = values.tags
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter((t) => t.length > 0)

      const body: Record<string, unknown> = {
        name: values.name.trim(),
        description: values.description.trim() || null,
        tags,
        encrypted_value: toBase64(encValue),
      }

      if (selectedTypeUuid && selectedVersionUuid) {
        body.type_uuid = selectedTypeUuid
        body.schema_version_uuid = selectedVersionUuid
      }

      const resp = await api.post<unknown>(
        `/wallets/${walletId ?? ''}/secrets`,
        body,
      )
      SecretCreateResponseSchema.parse(resp)

      await queryClient.invalidateQueries({ queryKey: ['secrets', walletId] })
      await queryClient.invalidateQueries({ queryKey: ['wallets'] })

      notifications.show({
        color: 'green',
        message: 'Secret created',
      })

      navigate(`/wallets/${walletId ?? ''}`, { replace: true })
    } catch (err) {
      let msg = t('errors.serverError')
      if (err instanceof ApiError) msg = err.message
      else if (err instanceof Error) msg = err.message
      setSubmitError(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  const typeOptions =
    typesData?.types
      .filter((tp) => !tp.deprecated_at)
      .map((tp) => ({
        value: tp.type_uuid,
        label: tp.label ?? `${tp.type}/${tp.sous_type}`,
      })) ?? []

  const versionOptions =
    selectedTypeDetail?.all_versions.map((v) => ({
      value: v.version_uuid,
      label: `v${v.version}${v.notes ? ` — ${v.notes}` : ''}`,
    })) ?? []

  const activeSchema = selectedTypeDetail?.all_versions.find(
    (v) => v.version_uuid === selectedVersionUuid,
  )

  // Sous-type courant — sert à proposer la génération côté navigateur pour
  // les types qui le permettent (LOT certificats, étape 2-3).
  const currentSousType = selectedTypeDetail?.sous_type ?? null
  const supportsClientGen =
    currentSousType === 'wireguard_peer' || currentSousType === 'ssh_user'

  async function handleGenerateKeypair() {
    try {
      if (currentSousType === 'wireguard_peer') {
        const kp = await generateWireguardKeypair()
        setTypedFormData({
          ...(typedFormData as Record<string, unknown>),
          private_key: kp.privateKey,
          public_key: kp.publicKey,
        })
        notifications.show({
          color: 'green',
          message: t('secrets.generate.wireguardSuccess'),
        })
      } else if (currentSousType === 'ssh_user') {
        const existingComment =
          ((typedFormData as Record<string, unknown>).comment as string) ?? ''
        const kp = await generateSshEd25519Keypair(existingComment)
        setTypedFormData({
          ...(typedFormData as Record<string, unknown>),
          key_type: 'ed25519',
          private_key: kp.privateKey,
          public_key: kp.publicKey,
          fingerprint: kp.fingerprint,
        })
        notifications.show({
          color: 'green',
          message: t('secrets.generate.sshSuccess'),
        })
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      notifications.show({
        color: 'red',
        title: t('secrets.generate.failed'),
        message: msg,
        autoClose: 8000,
      })
    }
  }

  return (
    <Stack maw={600}>
      <Title order={2}>{t('secrets.create')}</Title>

      {submitError && (
        <Alert color="red" title={t('common.error')}>
          {submitError}
        </Alert>
      )}

      <form onSubmit={form.onSubmit((v) => void handleSubmit(v))}>
        <Stack>
          <TextInput
            label={t('secrets.name')}
            placeholder={t('secrets.namePlaceholder')}
            description={t('secrets.nameHint')}
            required
            {...form.getInputProps('name')}
          />
          <Textarea
            label={t('secrets.description')}
            {...form.getInputProps('description')}
          />
          <TextInput
            label={t('wallets.tags')}
            placeholder="prod, api, database"
            description="Comma-separated"
            {...form.getInputProps('tags')}
          />

          <Divider label={t('secrets.typeSection')} labelPosition="left" />
          <Text size="sm" c="dimmed">
            {t('secrets.typeOptional')}
          </Text>
          <Select
            label={t('secrets.type')}
            placeholder={t('secrets.typeSelectPlaceholder')}
            data={typeOptions}
            value={selectedTypeUuid}
            clearable
            onChange={(v) => {
              setSelectedTypeUuid(v)
              setSelectedVersionUuid(null)
              setTypedFormData({})
            }}
          />
          {selectedTypeUuid && (
            <Select
              label={t('secrets.schemaVersion')}
              data={versionOptions}
              value={selectedVersionUuid}
              onChange={(v) => {
                setSelectedVersionUuid(v)
                setTypedFormData({})
              }}
            />
          )}

          <Divider />

          {activeSchema ? (
            <Stack>
              {supportsClientGen && (
                <Alert color="blue" variant="light">
                  <Stack gap="xs">
                    <Text size="sm">{t('secrets.generate.hint')}</Text>
                    <Group>
                      <Button
                        variant="filled"
                        size="sm"
                        onClick={() => void handleGenerateKeypair()}
                      >
                        {currentSousType === 'wireguard_peer'
                          ? t('secrets.generate.wireguardButton')
                          : t('secrets.generate.sshButton')}
                      </Button>
                    </Group>
                  </Stack>
                </Alert>
              )}
              <TypedSecretForm
                schemaData={activeSchema.schema_data}
                schemaUi={activeSchema.schema_ui}
                initialValue={typedFormData}
                onChange={setTypedFormData}
              />
            </Stack>
          ) : (
            <Textarea
              label={t('secrets.value')}
              placeholder="Secret value..."
              required={!selectedTypeUuid}
              minRows={4}
              {...form.getInputProps('value')}
            />
          )}

          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => navigate(-1)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={isSubmitting}>
              {t('common.create')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Stack>
  )
}