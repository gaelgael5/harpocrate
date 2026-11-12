/**
 * Connexion Listmonk (URL, utilisateur, token) de l'écran « Paramétrage Listmonk »
 * (feature 3).
 *
 * Le token s'écrit mais ne se relit pas : le serveur ne le renvoie jamais. Champ vide =
 * garder le token enregistré. Le test appelle Listmonk avec les valeurs saisies, sans
 * rien enregistrer.
 */
import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  PasswordInput,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import {
  useSaveListmonkConnection,
  useTestListmonkConnection,
} from "@/hooks/useListmonk";
import type {
  ListmonkConnection,
  ListmonkConnectionBody,
} from "@/schemas/listmonk";

interface ListmonkConnectionCardProps {
  /** Connexion enregistrée, ou null si aucune n'est encore réglée. */
  connection: ListmonkConnection | null;
}

export function ListmonkConnectionCard({
  connection,
}: ListmonkConnectionCardProps) {
  const { t } = useTranslation();
  const save = useSaveListmonkConnection();
  const test = useTestListmonkConnection();
  // Brouillon semé une seule fois : le parent remonte la carte (clé sur `updated_at`)
  // après un enregistrement, ce qui vide aussi le champ token.
  const [url, setUrl] = useState(connection?.url ?? "");
  const [apiUser, setApiUser] = useState(connection?.api_user ?? "");
  const [token, setToken] = useState("");

  // Le token enregistré ne se garde que vers la même URL et s'il est encore lisible
  // (clé serveur inchangée) : le serveur refuse les autres cas (token_required) pour
  // qu'un changement d'URL ne fasse jamais partir l'ancien token vers un autre hôte.
  const canKeepToken =
    connection?.token_readable === true && url.trim() === connection.url;
  const tokenMissing = !token && !canKeepToken;
  const complete = /^https?:\/\//.test(url.trim()) && apiUser.trim() !== "";
  const changed =
    token !== "" ||
    url.trim() !== (connection?.url ?? "") ||
    apiUser.trim() !== (connection?.api_user ?? "");

  const body = (): ListmonkConnectionBody => ({
    url: url.trim(),
    api_user: apiUser.trim(),
    ...(token ? { token } : {}),
  });

  const onError = (err: Error) =>
    notifications.show({
      color: "red",
      title: t("common.error"),
      message: err.message,
    });

  const result = test.data;
  // Un résultat de test ne vaut que pour les valeurs testées : toute saisie l'efface.
  const edit = (setter: (value: string) => void) => (value: string) => {
    test.reset();
    setter(value);
  };

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group gap="xs">
          <Text fw={500}>{t("admin.listmonk.connection")}</Text>
          <Badge color={connection ? "green" : "gray"}>
            {connection
              ? t("admin.listmonk.configured")
              : t("admin.listmonk.notConfigured")}
          </Badge>
        </Group>
        {connection && !connection.token_readable && (
          <Alert color="orange">{t("admin.listmonk.tokenUnreadable")}</Alert>
        )}
        <TextInput
          label={t("admin.listmonk.url")}
          placeholder="http://mail.home.lan:9000"
          value={url}
          onChange={(e) => edit(setUrl)(e.currentTarget.value)}
        />
        <TextInput
          label={t("admin.listmonk.apiUser")}
          value={apiUser}
          onChange={(e) => edit(setApiUser)(e.currentTarget.value)}
        />
        <PasswordInput
          label={t("admin.listmonk.token")}
          description={
            canKeepToken
              ? t("admin.listmonk.tokenKeepHelp")
              : t("admin.listmonk.tokenRequiredHelp")
          }
          value={token}
          onChange={(e) => edit(setToken)(e.currentTarget.value)}
          autoComplete="new-password"
        />
        {result && (
          <Alert color={result.ok ? "green" : "red"}>
            {result.ok
              ? t("admin.listmonk.testOk")
              : result.http_status === null
                ? t("admin.listmonk.testUnreachable")
                : t("admin.listmonk.testRefused", {
                    status: String(result.http_status),
                  })}
          </Alert>
        )}
        <Text size="xs" c="dimmed">
          {t("admin.listmonk.testHelp")}
        </Text>
        <Group justify="flex-end">
          <Button
            variant="default"
            disabled={!complete || tokenMissing}
            loading={test.isPending}
            onClick={() => test.mutate(body(), { onError })}
          >
            {t("admin.listmonk.test")}
          </Button>
          <Button
            disabled={!complete || tokenMissing || !changed}
            loading={save.isPending}
            onClick={() =>
              save.mutate(body(), {
                onError,
                onSuccess: () =>
                  notifications.show({
                    color: "green",
                    message: t("admin.listmonk.connectionSaved"),
                  }),
              })
            }
          >
            {t("admin.listmonk.save")}
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
