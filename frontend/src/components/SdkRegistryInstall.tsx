import {
  ActionIcon,
  Anchor,
  Code,
  CopyButton,
  Group,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { z } from "zod";

// Distribution d'un SDK par le registre officiel de son langage (manifest ≥ 1.1).
// L'URL et les commandes sont dérivées par le backend d'une table fermée de
// registres (services/sdk_registry.py), jamais recopiées depuis index.json.
export const RegistrySchema = z.object({
  name: z.string(),
  label: z.string(),
  package: z.string(),
  version: z.string(),
  // Défense en profondeur : le lien est rendu tel quel dans une page publique,
  // on refuse tout autre schéma que https (javascript:, data:…).
  url: z
    .string()
    .url()
    .refine((u) => u.startsWith("https://")),
  install_commands: z.array(z.string()),
});

export type Registry = z.infer<typeof RegistrySchema>;

export function SdkRegistryInstall({ registry }: { registry: Registry }) {
  const { t } = useTranslation();

  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">
        {t("integration.registry.installFrom", { registry: registry.label })}
        {" — "}
        {t("integration.latestVersion")} <strong>{registry.version}</strong>
      </Text>
      {registry.install_commands.map((cmd) => (
        <Group key={cmd} gap="xs" wrap="nowrap">
          <Code block style={{ flex: 1 }}>
            {cmd}
          </Code>
          <CopyButton value={cmd}>
            {({ copied, copy }) => (
              <Tooltip label={copied ? t("common.copied") : t("common.copy")}>
                <ActionIcon
                  variant="light"
                  onClick={copy}
                  aria-label={t("common.copy")}
                >
                  {copied ? "✓" : "📋"}
                </ActionIcon>
              </Tooltip>
            )}
          </CopyButton>
        </Group>
      ))}
      <Anchor
        href={registry.url}
        target="_blank"
        rel="noopener noreferrer"
        size="sm"
      >
        {t("integration.registry.viewPackage", { registry: registry.label })} →
      </Anchor>
    </Stack>
  );
}
