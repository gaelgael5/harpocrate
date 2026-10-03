/**
 * Résumé d'une demande de connexion : QUI demande l'accès et À QUOI.
 *
 * Le nom affiché est celui du registre des applications, renvoyé par le serveur ;
 * jamais un paramètre de l'URL (invariant 5 du cadrage).
 */
import { Badge, Group, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { PERMISSION_KEYS } from "@/schemas/grants";
import type { ConnectRequestView } from "@/schemas/connectFlow";

interface ConnectRequestPanelProps {
  request: ConnectRequestView;
}

function redirectHost(uri: string): string {
  try {
    return new URL(uri).host;
  } catch {
    return uri;
  }
}

export function ConnectRequestPanel({ request }: ConnectRequestPanelProps) {
  const { t } = useTranslation();
  const granted = PERMISSION_KEYS.filter(
    ({ bit }) => (request.requested_permissions & bit) !== 0,
  );

  return (
    <Stack gap="xs">
      <Text fw={600}>{request.client.name}</Text>
      {request.client.description && (
        <Text size="sm" c="dimmed">
          {request.client.description}
        </Text>
      )}
      <Text size="sm">
        {t("connect.returnTo", { host: redirectHost(request.redirect_uri) })}
      </Text>
      <Text size="sm" fw={500}>
        {t("connect.requestedPermissions")}
      </Text>
      <Group gap="xs">
        {granted.map(({ key }) => (
          <Badge key={key} variant="light">
            {t(`permissions.${key}`)}
          </Badge>
        ))}
      </Group>
      <Text size="sm">
        {request.requested_ttl_days === null
          ? t("connect.requestedTtlNone")
          : t("connect.requestedTtlDays", {
              count: request.requested_ttl_days,
            })}
      </Text>
    </Stack>
  );
}
