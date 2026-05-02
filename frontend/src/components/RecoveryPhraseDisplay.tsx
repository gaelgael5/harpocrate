/**
 * Displays the 24-word BIP-39 recovery phrase in a grid layout.
 * Includes a "Download as text" button.
 */
import { Grid, Text, Paper, Button, Stack, Alert } from '@mantine/core'
import { useTranslation } from 'react-i18next'

interface Props {
  words: string[]
  onConfirmed: () => void
  confirmed: boolean
  onConfirmedChange: (v: boolean) => void
}

export function RecoveryPhraseDisplay({
  words,
  onConfirmed: _onConfirmed,
  confirmed,
  onConfirmedChange,
}: Props) {
  const { t } = useTranslation()

  function downloadText() {
    const text = words
      .map((w, i) => `${String(i + 1).padStart(2, '0')}. ${w}`)
      .join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'harpocrate-recovery.txt'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Stack>
      <Alert color="yellow" title={t('firstLogin.recoveryWarning')}>
        {null}
      </Alert>

      <Paper withBorder p="md">
        <Grid>
          {words.map((word, idx) => (
            <Grid.Col key={idx} span={3}>
              <Text size="sm" ff="monospace">
                <Text component="span" c="dimmed" size="xs">
                  {String(idx + 1).padStart(2, '0')}.{' '}
                </Text>
                {word}
              </Text>
            </Grid.Col>
          ))}
        </Grid>
      </Paper>

      <Button variant="outline" onClick={downloadText}>
        {t('firstLogin.downloadPdf')}
      </Button>

      <Paper withBorder p="sm">
        <label
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
        >
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => onConfirmedChange(e.target.checked)}
          />
          <Text size="sm">{t('firstLogin.recoveryConfirm')}</Text>
        </label>
      </Paper>
    </Stack>
  )
}
