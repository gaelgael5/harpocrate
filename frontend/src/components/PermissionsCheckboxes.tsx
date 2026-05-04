/**
 * Checkbox group for wallet permission bits.
 */
import { Checkbox, Stack } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import {
  PERM_READ,
  PERM_ADD,
  PERM_INIT,
  PERM_WRITE,
  PERM_REMOVE,
  PERM_SHARE,
} from '@/schemas/grants'

interface Props {
  value: number
  onChange: (v: number) => void
  disabled?: boolean
}

const PERMS = [
  { bit: PERM_READ, key: 'read' },
  { bit: PERM_ADD, key: 'add' },
  { bit: PERM_INIT, key: 'init' },
  { bit: PERM_WRITE, key: 'write' },
  { bit: PERM_REMOVE, key: 'remove' },
  { bit: PERM_SHARE, key: 'share' },
] as const

export function PermissionsCheckboxes({ value, onChange, disabled }: Props) {
  const { t } = useTranslation()

  function toggle(bit: number) {
    onChange(value ^ bit)
  }

  return (
    <Stack gap="xs">
      {PERMS.map(({ bit, key }) => (
        <Checkbox
          key={key}
          label={t(`permissions.${key}`)}
          checked={(value & bit) !== 0}
          onChange={() => toggle(bit)}
          disabled={disabled}
        />
      ))}
    </Stack>
  )
}