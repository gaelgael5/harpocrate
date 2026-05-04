import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Stack,
  Title,
  TextInput,
  Textarea,
  Button,
  Group,
  Text,
  Alert,
  Card,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { createSecretType, validateJsonSchema } from '@/lib/adminApi'
import { JsonEditorMonaco } from '@/components/JsonEditorMonaco'

const DEFAULT_SCHEMA = JSON.stringify(
  {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    type: 'object',
    properties: {},
    required: [],
  },
  null,
  2
)

const DEFAULT_UI = '{}'

export function AdminSecretTypeCreatePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [type, setType] = useState('')
  const [sousType, setSousType] = useState('')
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [notes, setNotes] = useState('')
  const [schemaData, setSchemaData] = useState(DEFAULT_SCHEMA)
  const [schemaUi, setSchemaUi] = useState(DEFAULT_UI)
  const [validateResult, setValidateResult] = useState<{ valid: boolean; error?: string } | null>(null)

  const validateMut = useMutation({
    mutationFn: async () => {
      const parsed = JSON.parse(schemaData) as Record<string, unknown>
      return validateJsonSchema(parsed)
    },
    onSuccess: (result) => setValidateResult(result),
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('common.error')
      setValidateResult({ valid: false, error: msg })
    },
  })

  const createMut = useMutation({
    mutationFn: async () => {
      const parsedData = JSON.parse(schemaData) as Record<string, unknown>
      const parsedUi = JSON.parse(schemaUi) as Record<string, unknown>
      return createSecretType({
        type: type.trim().toLowerCase(),
        sous_type: sousType.trim().toLowerCase(),
        label: label || undefined,
        description: description || undefined,
        schema_data: parsedData,
        schema_ui: parsedUi,
        notes: notes || undefined,
      })
    },
    onSuccess: (result) => {
      notifications.show({ color: 'green', message: t('secret_types.createSuccess') })
      navigate(`/admin/secret-types/${result.type_uuid}`)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : t('secret_types.createError')
      notifications.show({ color: 'red', message: msg })
    },
  })

  const canSubmit = type.trim() !== '' && sousType.trim() !== '' && schemaData.trim() !== ''

  return (
    <Stack>
      <Group>
        <Button variant="subtle" onClick={() => navigate('/admin/secret-types')}>
          ← {t('common.back')}
        </Button>
        <Title order={2}>{t('secret_types.createTitle')}</Title>
      </Group>

      <Card withBorder>
        <Stack>
          <Group grow>
            <TextInput
              label={t('secret_types.typeLabel')}
              placeholder="aws"
              required
              value={type}
              onChange={(e) => setType(e.currentTarget.value)}
            />
            <TextInput
              label={t('secret_types.sousTypeLabel')}
              placeholder="credentials"
              required
              value={sousType}
              onChange={(e) => setSousType(e.currentTarget.value)}
            />
          </Group>
          <TextInput
            label={t('secret_types.labelLabel')}
            placeholder="AWS Credentials"
            value={label}
            onChange={(e) => setLabel(e.currentTarget.value)}
          />
          <Textarea
            label={t('secret_types.descriptionLabel')}
            autosize
            minRows={2}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
          />
          <Textarea
            label={t('secret_types.notesLabel')}
            autosize
            minRows={2}
            value={notes}
            onChange={(e) => setNotes(e.currentTarget.value)}
          />
        </Stack>
      </Card>

      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Text fw={500}>{t('secret_types.schemaDataLabel')}</Text>
            <Button
              variant="outline"
              size="xs"
              loading={validateMut.isPending}
              onClick={() => validateMut.mutate()}
            >
              {t('secret_types.validateButton')}
            </Button>
          </Group>
          <JsonEditorMonaco
            value={schemaData}
            onChange={setSchemaData}
            height="300px"
          />
          {validateResult && (
            <Alert color={validateResult.valid ? 'green' : 'red'}>
              {validateResult.valid
                ? t('secret_types.validSchema')
                : t('secret_types.invalidSchema', { error: validateResult.error })}
            </Alert>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack>
          <Text fw={500}>{t('secret_types.schemaUiLabel')}</Text>
          <JsonEditorMonaco
            value={schemaUi}
            onChange={setSchemaUi}
            height="200px"
          />
        </Stack>
      </Card>

      <Group justify="flex-end">
        <Button variant="subtle" onClick={() => navigate('/admin/secret-types')}>
          {t('common.cancel')}
        </Button>
        <Button
          disabled={!canSubmit}
          loading={createMut.isPending}
          onClick={() => createMut.mutate()}
        >
          {t('common.create')}
        </Button>
      </Group>
    </Stack>
  )
}
