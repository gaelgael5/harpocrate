/**
 * Passphrase input with show/hide toggle and strength indicator.
 */
import { PasswordInput, type PasswordInputProps } from '@mantine/core'

interface Props extends Omit<PasswordInputProps, 'type'> {
  minLength?: number
}

export function PassphraseInput({ minLength: _minLength = 12, ...props }: Props) {
  return (
    <PasswordInput
      {...props}
      autoComplete="current-password"
    />
  )
}
