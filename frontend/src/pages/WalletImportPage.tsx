/**
 * Page d'import d'un wallet à partir d'un fichier JSON d'export — LOT_07.
 *
 * Flux :
 * 1. L'utilisateur sélectionne un fichier .json
 * 2. Le fichier est parsé et validé via WalletExportSchema (Zod)
 * 3. Un aperçu du wallet + liste de secrets est affiché
 * 4. Sur "Confirmer l'import" :
 *    a. Génère une nouvelle wallet_key (32 bytes aléatoires)
 *    b. Chiffre la wallet_key avec la RSA pub de l'utilisateur
 *    c. POST /v1/wallets/import avec le payload enrichi
 *    d. Navigue vers la page du nouveau wallet
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Stack,
  Title,
  FileInput,
  Button,
  Group,
  Text,
  Badge,
  Card,
  Alert,
  Divider,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import { ApiError } from '@/lib/api-client'
import { importWallet } from '@/lib/exportImportApi'
import { WalletExportSchema, type WalletExport } from '@/schemas/exportImport'
import { randomBytes, toBase64 } from '@/crypto/helpers'
import { rsaOaepEncrypt } from '@/crypto/rsa-oaep'
import { useCryptoStore } from '@/stores/crypto'

export function WalletImportPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const rsaPublicKey = useCryptoStore((s) => s.rsaPublicKey)

  const [parseError, setParseError] = useState<string | null>(null)
  const [preview, setPreview] = useState<WalletExport | null>(null)
  const [isImporting, setIsImporting] = useState(false)

  function handleFileChange(file: File | null) {
    setParseError(null)
    setPreview(null)
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result
      if (typeof text !== 'string') {
        setParseError(t('wallets.import.invalidJson'))
        return
      }
      let parsed: unknown
      try {
        parsed = JSON.parse(text)
      } catch {
        setParseError(t('wallets.import.invalidJson'))
        return
      }
      const result = WalletExportSchema.safeParse(parsed)
      if (!result.success) {
        const messages = result.error.errors.map((e) => e.message).join('; ')
        setParseError(`${t('wallets.import.invalidFormat')}: ${messages}`)
        return
      }
      setPreview(result.data)
    }
    reader.readAsText(file)
  }

  async function handleConfirm() {
    if (!preview) return

    if (!rsaPublicKey) {
      notifications.show({
        color: 'red',
        message: t('wallets.import.cryptoRequired'),
      })
      return
    }

    setIsImporting(true)
    try {
      // Génère une nouvelle clé de wallet
      const walletKey = randomBytes(32)
      const encryptedKey = await rsaOaepEncrypt(walletKey, rsaPublicKey)

      const result = await importWallet({
        format_version: '1',
        wallet: preview.wallet,
        secrets: preview.secrets,
        encrypted_wallet_key_for_owner: toBase64(encryptedKey),
      })

      notifications.show({
        color: 'green',
        title: t('wallets.import.success'),
        message: t('wallets.import.successDetail', { count: result.secrets_created }),
      })

      if (result.skipped.length > 0) {
        notifications.show({
          color: 'yellow',
          message: t('wallets.import.skipped', {
            count: result.skipped.length,
            names: result.skipped.join(', '),
          }),
        })
      }

      navigate(`/wallets/${result.wallet_id}`, { replace: true })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err)
      notifications.show({ color: 'red', title: t('common.error'), message: msg })
    } finally {
      setIsImporting(false)
    }
  }

  return (
    <Stack maw={700}>
      <Group justify="space-between">
        <Title order={2}>{t('wallets.import.title')}</Title>
        <Button variant="outline" onClick={() => navigate('/wallets')}>
          {t('common.back')}
        </Button>
      </Group>

      <FileInput
        label={t('wallets.import.fileLabel')}
        placeholder={t('wallets.import.filePlaceholder')}
        accept=".json,application/json"
        onChange={handleFileChange}
      />

      {parseError && (
        <Alert color="red" title={t('common.error')}>
          {parseError}
        </Alert>
      )}

      {preview && (
        <Stack gap="sm">
          <Divider label={t('wallets.import.preview')} labelPosition="center" />

          <Card withBorder p="md">
            <Stack gap="xs">
              <Group gap="sm">
                <Text fw={600} size="lg">
                  {preview.wallet.name}
                </Text>
              </Group>

              {preview.wallet.description && (
                <Text c="dimmed" size="sm">
                  {preview.wallet.description}
                </Text>
              )}

              {preview.wallet.tags.length > 0 && (
                <Group gap="xs">
                  {preview.wallet.tags.map((tag) => (
                    <Badge key={tag} variant="light" size="sm">
                      {tag}
                    </Badge>
                  ))}
                </Group>
              )}
            </Stack>
          </Card>

          <Text fw={500} size="sm">
            {t('wallets.import.secrets', { count: preview.secrets.length })}
          </Text>

          {preview.secrets.length === 0 ? (
            <Text c="dimmed" size="sm">
              {t('wallets.import.noSecrets')}
            </Text>
          ) : (
            <Stack gap="xs">
              {preview.secrets.map((secret) => (
                <Card key={secret.name} withBorder padding="sm">
                  <Group justify="space-between">
                    <Group gap="sm">
                      <Text fw={500} ff="monospace" size="sm">
                        {secret.name}
                      </Text>
                      {secret.is_placeholder ? (
                        <Badge color="orange" size="xs">
                          {t('wallets.import.placeholder')}
                        </Badge>
                      ) : (
                        <Badge color="blue" size="xs">
                          {t('wallets.import.hasValue')}
                        </Badge>
                      )}
                    </Group>
                    {secret.tags.length > 0 && (
                      <Group gap="xs">
                        {secret.tags.map((tag) => (
                          <Badge key={tag} variant="outline" size="xs">
                            {tag}
                          </Badge>
                        ))}
                      </Group>
                    )}
                  </Group>
                  {secret.description && (
                    <Text c="dimmed" size="xs" mt="xs">
                      {secret.description}
                    </Text>
                  )}
                </Card>
              ))}
            </Stack>
          )}

          <Group justify="flex-end" mt="sm">
            <Button
              onClick={() => void handleConfirm()}
              loading={isImporting}
            >
              {t('wallets.import.confirm')}
            </Button>
          </Group>
        </Stack>
      )}
    </Stack>
  )
}
