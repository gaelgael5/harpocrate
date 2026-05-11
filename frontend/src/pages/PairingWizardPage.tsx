/**
 * Page wizard côté standby (B) — 2 colonnes :
 * - SSHTerminal pour que l'admin se connecte à sa machine
 * - PairingStepsList pour copier-coller les commandes pas à pas
 *
 * Polling toutes les 3s pour synchroniser le curseur si une autre tab a
 * avancé (rare, mais évite les surprises).
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Stack, Grid, Title, Text, Card, Loader, Center, Alert, Group, Button,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { SSHTerminal } from '@/components/SSHTerminal'
import { PairingStepsList } from '@/components/PairingStepsList'
import {
  getPairingSteps, markStepDone, markStepBack,
} from '@/lib/adminApi'

export function PairingWizardPage() {
  const { t } = useTranslation()
  const { sessionId } = useParams<{ sessionId: string }>()
  const nav = useNavigate()
  const qc = useQueryClient()

  const stepsQuery = useQuery({
    queryKey: ['pairing-steps', sessionId],
    queryFn: () => getPairingSteps(sessionId!),
    enabled: !!sessionId,
    refetchInterval: 3000,
  })

  const doneMut = useMutation({
    mutationFn: (idx: number) => markStepDone(sessionId!, idx),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['pairing-steps', sessionId] }),
  })
  const backMut = useMutation({
    mutationFn: (idx: number) => markStepBack(sessionId!, idx),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['pairing-steps', sessionId] }),
  })

  if (stepsQuery.isLoading) {
    return (
      <Center mt="xl"><Loader /></Center>
    )
  }
  if (stepsQuery.error || !stepsQuery.data) {
    return (
      <Alert color="red">{String(stepsQuery.error ?? 'no_data')}</Alert>
    )
  }
  const data = stepsQuery.data

  return (
    <Stack>
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>
            {t('admin.replication.pairing.wizard.title')}
          </Title>
          <Text c="dimmed" size="sm">
            {t('admin.replication.pairing.wizard.subtitleA')}
            {' '}
            {t('admin.replication.pairing.wizard.subtitleB')}
          </Text>
        </Stack>
        <Button
          variant="subtle"
          color="gray"
          onClick={() => nav('/admin/replication')}
        >
          {t('admin.replication.pairing.wizard.abort')}
        </Button>
      </Group>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <SSHTerminal />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card withBorder>
            <PairingStepsList
              steps={data.steps}
              currentIdx={data.current_step_idx}
              onDone={(i) => doneMut.mutate(i)}
              onBack={(i) => backMut.mutate(i)}
              busy={doneMut.isPending || backMut.isPending}
            />
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  )
}
