/**
 * Page côté standby (B) — saisie de l'URL master + code 4 chiffres.
 * Au succès, redirige vers /admin/pairing/{session_id} (wizard, Task 4.5).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import {
  Stack, Title, Text, TextInput, PinInput, Group, Button, Card,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'

import { acceptPairing } from '@/lib/adminApi'
import { ApiError } from '@/lib/api-client'

export function BecomeStandbyPage() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const [masterUrl, setMasterUrl] = useState('')
  const [code, setCode] = useState('')

  const mut = useMutation({
    mutationFn: () => acceptPairing(masterUrl, code),
    onSuccess: (r) => nav(`/admin/pairing/${r.session_id}`),
    onError: (e) => notifications.show({
      color: 'red',
      title: t('common.error'),
      message: e instanceof ApiError ? e.message : String(e),
    }),
  })

  return (
    <Stack maw={600} mx="auto" mt="xl">
      <Title order={2}>
        {t('admin.replication.pairing.becomeStandby.title')}
      </Title>
      <Text c="dimmed">
        {t('admin.replication.pairing.becomeStandby.subtitle')}
      </Text>
      <Card withBorder>
        <Stack>
          <TextInput
            label={t('admin.replication.pairing.becomeStandby.masterUrl')}
            placeholder="https://harpo-1.example/"
            value={masterUrl}
            onChange={(e) => setMasterUrl(e.currentTarget.value)}
          />
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              {t('admin.replication.pairing.becomeStandby.code')}
            </Text>
            <PinInput length={4} type="number" value={code} onChange={setCode} />
          </Stack>
          <Group justify="flex-end">
            <Button
              loading={mut.isPending}
              disabled={!masterUrl || code.length !== 4}
              onClick={() => mut.mutate()}
            >
              {t('admin.replication.pairing.becomeStandby.submit')}
            </Button>
          </Group>
        </Stack>
      </Card>
    </Stack>
  )
}
