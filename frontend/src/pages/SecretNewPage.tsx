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
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '@/lib/api-client'
import { aesGcmEncrypt } from '@/crypto/aes-gcm'
import { rsaOaepDecrypt } from '@/crypto/rsa-oaep'
import { fromBase64, toBase64, textToBytes } from '@/crypto/helpers'
import { useCryptoStore } from '@/stores/crypto'
import { SecretCreateResponseSchema } from '@/schemas/secrets'
import { MyGrantResponseSchema } from '@/schemas/grants'

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
      value: (v) => (!v.trim() ? t('common.required') : null),
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

      // Encrypt the value
      const plainBytes = textToBytes(values.value)
      const encValue = await aesGcmEncrypt(plainBytes, walletKey)

      const tags = values.tags
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter((t) => t.length > 0)

      const body = {
        name: values.name.trim(),
        description: values.description.trim() || null,
        tags,
        encrypted_value: toBase64(encValue),
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
          <Textarea
            label={t('secrets.value')}
            placeholder="Secret value..."
            required
            minRows={4}
            {...form.getInputProps('value')}
          />
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
