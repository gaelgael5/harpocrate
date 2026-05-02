/**
 * Modal one-shot d'affichage du token d'API key.
 *
 * Le token n'est jamais re-montré après fermeture de ce modal.
 * L'utilisateur doit confirmer qu'il a sauvegardé le token avant de pouvoir fermer.
 */
import { useState } from 'react'
import {
  Modal,
  Code,
  Button,
  Group,
  Stack,
  Alert,
  Checkbox,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

interface Props {
  token: string | null
  onClose: () => void
}

export function ApiKeyTokenModal({ token, onClose }: Props) {
  const { t } = useTranslation()
  const [confirmed, setConfirmed] = useState(false)
  const [copied, setCopied] = useState(false)

  const isOpen = token !== null

  async function handleCopy() {
    if (!token) return
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
      notifications.show({
        color: 'green',
        message: t('common.copied'),
      })
    } catch {
      notifications.show({
        color: 'red',
        message: t('errors.network'),
      })
    }
  }

  function handleClose() {
    if (!confirmed && !copied) return
    setConfirmed(false)
    setCopied(false)
    onClose()
  }

  const canClose = confirmed || copied

  return (
    <Modal
      opened={isOpen}
      onClose={handleClose}
      title={t('apiKeys.tokenOneShot')}
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={false}
    >
      <Stack gap="md">
        <Alert color="orange" title={t('apiKeys.tokenWarning')}>
          {t('apiKeys.tokenWarningDetail')}
        </Alert>

        <Code
          block
          style={{
            wordBreak: 'break-all',
            fontSize: '0.85rem',
            fontFamily: 'monospace',
            padding: '1rem',
          }}
        >
          {token ?? ''}
        </Code>

        <Button
          variant="filled"
          onClick={() => void handleCopy()}
          fullWidth
        >
          {copied ? t('common.copied') : t('common.copy')}
        </Button>

        <Checkbox
          label={t('apiKeys.tokenSavedConfirm')}
          checked={confirmed}
          onChange={(e) => setConfirmed(e.currentTarget.checked)}
        />

        <Group justify="flex-end">
          <Button
            variant="outline"
            disabled={!canClose}
            onClick={handleClose}
          >
            {t('common.close')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
