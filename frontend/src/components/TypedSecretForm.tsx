import { useState } from 'react'
import Form from '@rjsf/mantine'
import validator from '@rjsf/validator-ajv8'
import type { WidgetProps } from '@rjsf/utils'
import { Group, PasswordInput, ActionIcon, CopyButton, Tooltip } from '@mantine/core'

const SecretPasswordWidget = (props: WidgetProps) => {
  const { value, onChange, options, disabled, readonly } = props
  const [revealed, setRevealed] = useState(false)
  const copyable = options?.copyable !== false
  const canReveal = options?.reveal !== false

  return (
    <Group gap="xs" align="flex-end">
      <PasswordInput
        style={{ flex: 1 }}
        value={value ?? ''}
        onChange={(e) => onChange(e.currentTarget.value)}
        disabled={disabled || readonly}
        visible={revealed}
        onVisibilityChange={() => {
          if (canReveal) setRevealed((r) => !r)
        }}
      />
      {copyable && (
        <CopyButton value={value ?? ''}>
          {({ copied, copy }) => (
            <Tooltip label={copied ? '✓' : 'Copy'}>
              <ActionIcon variant="subtle" onClick={copy}>
                {copied ? '✓' : '📋'}
              </ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
      )}
    </Group>
  )
}

const WIDGETS = {
  PasswordWidget: SecretPasswordWidget,
}

interface Props {
  schemaData: object
  schemaUi: object
  initialValue?: object
  onSubmit?: (value: object) => void
  onChange?: (value: object) => void
  readOnly?: boolean
  submitLabel?: string
}

export function TypedSecretForm({
  schemaData,
  schemaUi,
  initialValue,
  onSubmit,
  onChange,
  readOnly = false,
  submitLabel,
}: Props) {
  return (
    <Form
      schema={schemaData as never}
      uiSchema={{
        ...schemaUi,
        'ui:submitButtonOptions': submitLabel
          ? { submitText: submitLabel }
          : { norender: true },
      }}
      formData={initialValue}
      validator={validator}
      widgets={WIDGETS}
      onSubmit={(data) => onSubmit?.(data.formData as object)}
      onChange={(data) => onChange?.(data.formData as object)}
      disabled={readOnly}
      readonly={readOnly}
      liveValidate
    />
  )
}
