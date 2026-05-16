/**
 * Stepper Mantine + carte de la commande active + boutons OK/Retour.
 *
 * Composant CONTRÔLÉ : le parent passe `currentIdx`, `onDone`, `onBack`.
 */
import { useState } from 'react'
import { Stack, Stepper, Card, Code, Text, Group, Button } from '@mantine/core'
import { useTranslation } from 'react-i18next'

import type { PairingStep } from '@/schemas/pairing'

interface Props {
  steps: PairingStep[]
  currentIdx: number
  onDone: (idx: number) => void
  onBack: (idx: number) => void
  busy?: boolean
}

export function PairingStepsList({
  steps, currentIdx, onDone, onBack, busy,
}: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const total = steps.length
  const done = currentIdx >= total
  const active = done ? null : steps[currentIdx]

  async function copyCmd() {
    if (!active) return
    try {
      await navigator.clipboard.writeText(active.command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable (HTTP non-secure context). User can select manually.
    }
  }

  return (
    <Stack>
      <Stepper active={currentIdx} size="sm" iconSize={20}>
        {steps.map((s) => <Stepper.Step key={s.idx} label={s.title} />)}
        <Stepper.Completed>
          <Text mt="md" fw={500}>
            {t('admin.replication.pairing.wizard.completed')}
          </Text>
        </Stepper.Completed>
      </Stepper>

      {active && (
        <Card withBorder>
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              {t('admin.replication.pairing.wizard.stepProgress', {
                current: currentIdx + 1,
                total,
              })}
            </Text>
            <Text fw={600}>{active.title}</Text>
            {active.hint && (
              <Text size="sm" c="dimmed">{active.hint}</Text>
            )}
            <Text size="sm" fw={500} mt="xs">
              {t('admin.replication.pairing.wizard.command')}
            </Text>
            <Group align="flex-start" wrap="nowrap">
              <Code
                block
                style={{
                  flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                }}
              >
                {active.command}
              </Code>
              <Button size="xs" variant="light" onClick={() => void copyCmd()}>
                {copied
                  ? t('admin.replication.pairing.wizard.copied')
                  : t('admin.replication.pairing.wizard.copy')}
              </Button>
            </Group>
            <Group justify="space-between" mt="md">
              <Button
                variant="default"
                onClick={() => onBack(currentIdx)}
                disabled={currentIdx === 0 || busy}
              >
                {t('admin.replication.pairing.wizard.back')}
              </Button>
              <Button onClick={() => onDone(currentIdx)} loading={busy}>
                {t('admin.replication.pairing.wizard.markDone')}
              </Button>
            </Group>
          </Stack>
        </Card>
      )}
    </Stack>
  )
}
