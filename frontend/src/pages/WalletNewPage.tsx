/**
 * Create new wallet page.
 *
 * Generates a random wallet_key, encrypts it with user's RSA public key,
 * then POSTs to /v1/wallets.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { rsaOaepEncrypt } from '@/crypto/rsa-oaep'
import { randomBytes, toBase64 } from '@/crypto/helpers'
import { useCryptoStore } from '@/stores/crypto'
import { WalletCreateResponseSchema } from '@/schemas/wallets'

interface FormValues {
  name: string
  description: string
  tags: string
}

export function WalletNewPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const rsaPublicKey = useCryptoStore((s) => s.rsaPublicKey)
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey)

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    initialValues: {
      name: '',
      description: '',
      tags: '',
    },
    validate: {
      name: (v) =>
        v.trim().length === 0
          ? t('common.required')
          : v.trim().length > 255
            ? 'Max 255 characters'
            : null,
    },
  })

  async function handleSubmit(values: FormValues) {
    if (!rsaPublicKey) {
      setSubmitError(t('errors.cryptoRequired'))
      return
    }

    setIsSubmitting(true)
    setSubmitError(null)

    try {
      // Generate wallet_key (32 bytes random)
      const walletKey = randomBytes(32)

      // Encrypt wallet_key with owner's RSA public key
      const encWalletKey = await rsaOaepEncrypt(walletKey, rsaPublicKey)

      const tags = values.tags
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter((t) => t.length > 0)

      const body = {
        name: values.name.trim(),
        description: values.description.trim() || null,
        tags,
        encrypted_wallet_key_for_owner: toBase64(encWalletKey),
      }

      const resp = await api.post<unknown>('/wallets', body)
      const { wallet_id: walletId } = WalletCreateResponseSchema.parse(resp)

      // Cache wallet_key in RAM
      cacheWalletKey(walletId, walletKey)

      await queryClient.invalidateQueries({ queryKey: ['wallets'] })

      notifications.show({
        color: 'green',
        message: t('wallets.created'),
      })

      navigate(`/wallets/${walletId}`, { replace: true })
    } catch (err) {
      let msg = t('errors.serverError')
      if (err instanceof ApiError) msg = err.message
      setSubmitError(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Stack maw={600}>
      <Title order={2}>{t('wallets.createTitle')}</Title>

      {submitError && (
        <Alert color="red" title={t('common.error')}>
          {submitError}
        </Alert>
      )}

      <form onSubmit={form.onSubmit((v) => void handleSubmit(v))}>
        <Stack>
          <TextInput
            label={t('wallets.name')}
            placeholder={t('wallets.namePlaceholder')}
            required
            {...form.getInputProps('name')}
          />
          <Textarea
            label={t('wallets.description')}
            placeholder={t('wallets.descriptionPlaceholder')}
            {...form.getInputProps('description')}
          />
          <TextInput
            label={t('wallets.tags')}
            placeholder={t('wallets.tagsPlaceholder')}
            description="Comma-separated"
            {...form.getInputProps('tags')}
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
