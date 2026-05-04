/**
 * New secret page — creates a manual secret by encrypting the value with wallet_key.
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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

const NAME_RE = /^[A-Za-z0-9_.-]+$/

export function SecretNewPage() {
  const { t } = useTranslation()
  const { walletId } = useParams<{ walletId: string }>()
  const navigate = useNavigate()
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
    initialValues: { name: '', description: '', tags: '', value: '' },
    validate: {
      name: (v) => {
        const stripped = v.trim()
        if (!stripped) return t('common.required')
        if (stripped.length > 256) return 'Max 256 characters'
        if (!NAME_RE.test(stripped)) return t('secrets.nameHint')
        return null
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
            <TypedSecretForm
              schemaData={activeSchema.schema_data}
              schemaUi={activeSchema.schema_ui}
              initialValue={typedFormData}
              onChange={setTypedFormData}
            />
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