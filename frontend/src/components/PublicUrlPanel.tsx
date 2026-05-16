/**
 * PublicUrlPanel — affiche l'URL publique de cette instance Harpocrate à
 * transmettre au pair lors d'un appairage (LOT 5 — refonte mono-URL).
 *
 * Une seule ligne copiable = URL du back-office. C'est cette URL que l'autre
 * instance collera dans sa modale « Ajouter un standby » pour générer une
 * URL d'appairage signée.
 *
 * Lecture seule.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Center,
  Code,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import { getReplicationSelfInfo } from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";

function CopyRow({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard non dispo (HTTP non-secure) — l'admin peut sélectionner le Code.
    }
  }

  return (
    <Group justify="space-between" wrap="nowrap" align="center">
      <Code
        style={{ fontSize: "0.95rem", wordBreak: "break-all", flex: 1 }}
      >
        {value}
      </Code>
      <Button size="compact-sm" variant="filled" onClick={() => void copy()}>
        {copied ? t("common.copied") : t("common.copy")}
      </Button>
    </Group>
  );
}

export function PublicUrlPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-replication-self-info"],
    queryFn: getReplicationSelfInfo,
    staleTime: 60_000,
  });

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t("admin.replication.selfInfo.title")}</Title>
          <Button
            size="xs"
            variant="subtle"
            loading={query.isFetching}
            onClick={() =>
              void qc.invalidateQueries({
                queryKey: ["admin-replication-self-info"],
              })
            }
          >
            {t("common.refresh")}
          </Button>
        </Group>

        <Text size="sm" c="dimmed">
          {t("admin.replication.selfInfo.subtitle")}
        </Text>

        {query.isLoading && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}
        {query.error && (
          <Alert color="red">
            {query.error instanceof ApiError
              ? query.error.message
              : t("common.error")}
          </Alert>
        )}

        {query.data && <CopyRow value={query.data.public_url} />}
      </Stack>
    </Card>
  );
}
