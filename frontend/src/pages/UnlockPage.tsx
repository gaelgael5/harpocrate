/**
 * Unlock page — derives pass_key from passphrase and decrypts RSA + sym_key.
 *
 * Flow:
 * 1. GET /v1/me/crypto → salt, encrypted blobs, kdf_params
 * 2. User enters passphrase
 * 3. Derive pass_key via Argon2id
 * 4. Decrypt rsa_priv + sym_key with AES-GCM
 * 5. Store in RAM, redirect to /
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Center,
  Stack,
  Title,
  Text,
  Button,
  PasswordInput,
  Alert,
  Loader,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { notifications } from '@mantine/notifications'

import { api, ApiError } from '@/lib/api-client'
import { getUserManager } from '@/lib/oidc'
import { useSessionStore } from '@/stores/session'
import { deriveKey } from '@/crypto/argon2'
import { aesGcmDecrypt } from '@/crypto/aes-gcm'
import { fromBase64 } from '@/crypto/helpers'
import { useCryptoStore } from '@/stores/crypto'
import { CryptoResponseSchema } from '@/schemas/auth'

type PageState = 'check-auth' | 'ready' | 'unlocking'

export function UnlockPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const setUnlocked = useCryptoStore((s) => s.setUnlocked)
  const isUnlocked = useCryptoStore((s) => s.isUnlocked)

  const [pageState, setPageState] = useState<PageState>('check-auth')
  const [passphrase, setPassphrase] = useState('')
  const [error, setError] = useState<string | null>(null)

  // If already unlocked, redirect immediately
  useEffect(() => {
    if (isUnlocked) {
      navigate('/', { replace: true })
    }
  }, [isUnlocked, navigate])

  useEffect(() => {
    async function checkAuth() {
      try {
        const mgr = getUserManager()
        const user = await mgr.getUser()
        // Accepte OIDC OU local-admin (les deux sont des sessions valides).
        const localToken = useSessionStore.getState().localAdminToken
        const authenticated = (user && !user.expired) || !!localToken
        if (!authenticated) {
          navigate('/login', { replace: true })
          return
        }
        setPageState('ready')
      } catch {
        navigate('/login', { replace: true })
      }
    }
    void checkAuth()
  }, [navigate])

  async function handleUnlock() {
    if (!passphrase) return
    setPageState('unlocking')
    setError(null)

    try {
      // 1. Fetch crypto blobs
      const raw = await api.get<unknown>('/me/crypto')
      const crypto = CryptoResponseSchema.parse(raw)

      // 2. Decode blobs
      const saltPassphrase = fromBase64(crypto.salt_passphrase)
      const encRsaPriv = fromBase64(crypto.encrypted_rsa_private_key)
      const encSymByPass = fromBase64(crypto.encrypted_sym_key_by_pass)
      const rsaPub = fromBase64(crypto.rsa_public_key)

      // 3. Derive pass_key
      const passKey = await deriveKey(passphrase, saltPassphrase, {
        memory_kb: crypto.kdf_params.memory_kb,
        iterations: crypto.kdf_params.iterations,
        parallelism: crypto.kdf_params.parallelism,
      })

      // 4. Decrypt rsa_priv and sym_key
      let rsaPriv: Uint8Array
      let symKey: Uint8Array
      try {
        rsaPriv = await aesGcmDecrypt(encRsaPriv, passKey)
        symKey = await aesGcmDecrypt(encSymByPass, passKey)
      } catch {
        // AES-GCM decryption failure = wrong passphrase (authentication tag mismatch)
        setError(t('unlock.wrongPassphrase'))
        setPageState('ready')
        return
      }

      // 5. Store in RAM
      setUnlocked(rsaPriv, symKey, rsaPub)

      notifications.show({
        color: 'green',
        message: t('auth.unlockSuccess'),
      })

      navigate('/', { replace: true })
    } catch (err) {
      let msg = t('errors.serverError')
      if (err instanceof ApiError) {
        if (err.isFirstLogin) {
          navigate('/first-login', { replace: true })
          return
        }
        if (err.isUnauthorized) {
          navigate('/login', { replace: true })
          return
        }
        msg = err.message
      }
      setError(msg)
      setPageState('ready')
    }
  }

  if (pageState === 'check-auth') {
    return (
      <Center h="100vh">
        <Loader size="xl" />
      </Center>
    )
  }

  return (
    <Center h="100vh">
      <Stack w={400} gap="xl">
        <Stack align="center" gap="xs">
          <Title order={2}>{t('unlock.title')}</Title>
          <Text c="dimmed">{t('unlock.subtitle')}</Text>
        </Stack>

        {error && (
          <Alert color="red" title={t('common.error')}>
            {error}
          </Alert>
        )}

        <PasswordInput
          label={t('unlock.passphraseLabel')}
          value={passphrase}
          onChange={(e) => setPassphrase(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handleUnlock()
          }}
          autoComplete="current-password"
          autoFocus
          disabled={pageState === 'unlocking'}
        />

        <Button
          onClick={() => void handleUnlock()}
          loading={pageState === 'unlocking'}
          // loading
          disabled={!passphrase}
        >
          {t('unlock.unlockButton')}
        </Button>
      </Stack>
    </Center>
  )
}
