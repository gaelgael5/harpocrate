/**
 * Clés déjà obtenues par CETTE application sur CE wallet (décision D8) : au
 * renouvellement, l'utilisateur peut révoquer les anciennes ; il peut aussi les garder
 * (une seconde instance de l'application s'en sert peut-être).
 */
import { Alert, Button, Group, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { useApiKeysList, useRevokeApiKey } from "@/hooks/useApiKeys";

interface ConnectExistingKeysProps {
  walletId: string;
  clientId: string;
}

export function ConnectExistingKeys({
  walletId,
  clientId,
}: ConnectExistingKeysProps) {
  const { t, i18n } = useTranslation();
  const { data } = useApiKeysList(walletId);
  const revoke = useRevokeApiKey(walletId);

  const keys = (data?.api_keys ?? []).filter(
    (k) => k.revoked_at === null && k.connect_client?.client_id === clientId,
  );
  if (keys.length === 0) return null;

  return (
    <Alert
      color="yellow"
      variant="light"
      title={t("connect.existingKeysTitle")}
    >
      <Stack gap="xs">
        <Text size="sm">{t("connect.existingKeysHelp")}</Text>
        {keys.map((k) => (
          <Group key={k.id} justify="space-between" wrap="nowrap">
            <Text size="sm">
              {t("connect.existingKeyCreated", {
                date: new Date(k.created_at).toLocaleDateString(i18n.language),
              })}
            </Text>
            <Button
              size="xs"
              variant="light"
              color="red"
              loading={revoke.isPending && revoke.variables === k.id}
              onClick={() => revoke.mutate(k.id)}
            >
              {t("connect.revokeKey")}
            </Button>
          </Group>
        ))}
      </Stack>
    </Alert>
  );
}
