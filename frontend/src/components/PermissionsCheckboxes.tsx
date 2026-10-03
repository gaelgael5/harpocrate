/**
 * Checkbox group for wallet permission bits.
 */
import { Checkbox, Stack } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { PERMISSION_KEYS } from "@/schemas/grants";

interface Props {
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}

export function PermissionsCheckboxes({ value, onChange, disabled }: Props) {
  const { t } = useTranslation();

  function toggle(bit: number) {
    onChange(value ^ bit);
  }

  return (
    <Stack gap="xs">
      {PERMISSION_KEYS.map(({ bit, key }) => (
        <Checkbox
          key={key}
          label={t(`permissions.${key}`)}
          checked={(value & bit) !== 0}
          onChange={() => toggle(bit)}
          disabled={disabled}
        />
      ))}
    </Stack>
  );
}
