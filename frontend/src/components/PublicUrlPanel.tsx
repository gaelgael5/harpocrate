/**
 * PublicUrlPanel — affiche les coordonnées publiques de cette instance
 * Harpocrate à transmettre au pair lors d'un appairage (LOT 5 — refonte).
 *
 * - URL publique du backend (settings.public_url)
 * - Host Postgres annoncé (hostname extrait de public_url)
 * - Port Postgres annoncé (settings.replication_advertised_pg_port)
 *
 * Lecture seule. Bouton copier sur chaque ligne.
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

function CopyRow({ label, value }: { label: string; value: string }) {
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
      <Stack gap={0} style={{ minWidth: 0, flex: 1 }}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Code style={{ fontSize: "0.85rem", wordBreak: "break-all" }}>
          {value}
        </Code>
      </Stack>
      <Button size="compact-xs" variant="subtle" onClick={() => void copy()}>
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

        {query.data && (
          <Stack gap="xs">
            <CopyRow
              label={t("admin.replication.selfInfo.publicUrl")}
              value={query.data.public_url}
            />
            <CopyRow
              label={t("admin.replication.selfInfo.pgHost")}
              value={query.data.advertised_pg_host}
            />
            <CopyRow
              label={t("admin.replication.selfInfo.pgPort")}
              value={String(query.data.advertised_pg_port)}
            />
            <Alert color="blue" mt="xs">
              <Text size="xs">
                {t("admin.replication.selfInfo.hostHint")}
              </Text>
            </Alert>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
