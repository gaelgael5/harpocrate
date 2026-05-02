/**
 * Account settings page — displays user info and allows passphrase change.
 */
import { useState } from 'react'
import {
  Stack,
  Title,
  Text,
  Group,
  Button,
  Modal,
  PasswordInput,
  Alert,
  Paper,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '@/lib/api-client'
import { useSessionStore } from '@/stores/session'
import { useCryptoStore } from '@/stores/crypto'
import { deriveKey, DEFAULT_KDF_PARAMS } from '@/crypto/argon2'
import { aesGcmEncrypt } from '@/crypto/aes-gcm'
import { randomBytes, toBase64 } from '@/crypto/helpers'
import { UpdatedAtResponseSchema } from '@/schemas/auth'

export function AccountPage() {
  const { t } = useTranslation()
  const user = useSessionStore((s) => s.user)
  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey)
  const symKey = useCryptoStore((s) => s.symKey)

  const [passphraseModalOpen, { open: openPP, close: closePP }] = useDisclosure()
  const [oldPassphrase, setOldPassphrase] = useState('')
  const [newPassphrase, setNewPassphrase] = useState('')
  const [newPassphraseConfirm, setNewPassphraseConfirm] = useState('')
  const [ppError, setPpError] = useState<string | null>(null)
  const [ppWorking, setPpWorking] = useState(false)

  async function handleChangePassphrase() {
    if (newPassphrase.length < 12) {
      setPpError(t('auth.passphraseTooShort'))
      return
    }
    if (newPassphrase !== newPassphraseConfirm) {
      setPpError(t('auth.passphrasesMustMatch'))
      return
    }
    if (!rsaPrivateKey || !symKey) {
      setPpError(t('errors.cryptoRequired'))
      return
    }

    setPpWorking(true)
    setPpError(null)

    try {
      // Generate new salt
      const newSalt = randomBytes(16)
      const kdfParams = DEFAULT_KDF_PARAMS

      // Derive new pass_key
      const newPassKey = await deriveKey(newPassphrase, newSalt, kdfParams)

      // Re-encrypt rsa_priv and sym_key with new pass_key
      const encRsaPriv = await aesGcmEncrypt(rsaPrivateKey, newPassKey)
      const encSymKey = await aesGcmEncrypt(symKey, newPassKey)

      const resp = await api.put<unknown>('/me/passphrase', {
        new_salt_passphrase: toBase64(newSalt),
        new_encrypted_rsa_private_key: toBase64(encRsaPriv),
        new_encrypted_sym_key_by_pass: toBase64(encSymKey),
        kdf_memory_kb: kdfParams.memory_kb,
        kdf_iterations: kdfParams.iterations,
        kdf_parallelism: kdfParams.parallelism,
      })

      UpdatedAtResponseSchema.parse(resp)

      notifications.show({ color: 'green', message: 'Passphrase changed!' })
      closePP()
      setOldPassphrase('')
      setNewPassphrase('')
      setNewPassphraseConfirm('')
    } catch (err) {
      let msg = t('errors.serverError')
      if (err instanceof ApiError) msg = err.message
      setPpError(msg)
    } finally {
      setPpWorking(false)
    }
  }

  if (!user) return null

  return (
    <Stack>
      <Title order={2}>{t('account.title')}</Title>

      <Paper withBorder p="md">
        <Stack gap="sm">
          <Group>
            <Text fw={500}>{t('account.email')}</Text>
            <Text>{user.email}</Text>
          </Group>
          {user.display_name && (
            <Group>
              <Text fw={500}>{t('account.displayName')}</Text>
              <Text>{user.display_name}</Text>
            </Group>
          )}
          <Group>
            <Text fw={500}>{t('account.rsaKeySize')}</Text>
            <Text>{user.rsa_key_size} bits</Text>
          </Group>
          <Group>
            <Text fw={500}>{t('account.kdfParams')}</Text>
            <Text>
              memory={user.kdf_params.memory_kb}KB iterations=
              {user.kdf_params.iterations} parallelism=
              {user.kdf_params.parallelism}
            </Text>
          </Group>
        </Stack>
      </Paper>

      <Group>
        <Button onClick={openPP}>{t('account.changePassphrase')}</Button>
      </Group>

      <Modal
        opened={passphraseModalOpen}
        onClose={closePP}
        title={t('account.changePassphrase')}
      >
        <Stack>
          {ppError && <Alert color="red">{ppError}</Alert>}
          <PasswordInput
            label={t('account.oldPassphrase')}
            value={oldPassphrase}
            onChange={(e) => setOldPassphrase(e.currentTarget.value)}
            autoComplete="current-password"
          />
          <PasswordInput
            label={t('account.newPassphrase')}
            value={newPassphrase}
            onChange={(e) => setNewPassphrase(e.currentTarget.value)}
            autoComplete="new-password"
          />
          <PasswordInput
            label={t('account.newPassphraseConfirm')}
            value={newPassphraseConfirm}
            onChange={(e) => setNewPassphraseConfirm(e.currentTarget.value)}
            autoComplete="new-password"
          />
          <Button
            onClick={() => void handleChangePassphrase()}
            loading={ppWorking}
          >
            {t('common.save')}
          </Button>
        </Stack>
      </Modal>
    </Stack>
  )
}
