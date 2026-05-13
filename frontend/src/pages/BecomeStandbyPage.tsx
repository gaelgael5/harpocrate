/**
 * Page côté standby (B) — saisie d'une URL d'appairage (v2, LOT 5).
 *
 * L'admin colle l'URL générée par le master. Le backend extrait master_url +
 * session_id + token, contacte le master pour récupérer les creds de
 * réplication, puis redirige vers PairingWizardPage qui guide l'exécution
 * des commandes SSH.
 *
 * Si le master refuse en 409 node_already_exists, on affiche
 * ConfirmReplaceNodeModal pour relancer avec force=true.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Text,
  TextInput,
  Group,
  Button,
  Card,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { acceptPairingV2 } from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";
import { ConfirmReplaceNodeModal } from "@/components/ConfirmReplaceNodeModal";
import { ExistingNodeSchema, type ExistingNode } from "@/schemas/pairing";

export function BecomeStandbyPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [pairingUrl, setPairingUrl] = useState("");
  const [existing, setExisting] = useState<ExistingNode | null>(null);

  const submitMut = useMutation({
    mutationFn: (force: boolean) => acceptPairingV2(pairingUrl.trim(), force),
    onSuccess: (r) => {
      setExisting(null);
      nav(`/admin/pairing/${r.session_id}`);
    },
    onError: (e) => {
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        e.code === "node_already_exists" &&
        e.detail !== null &&
        typeof e.detail === "object" &&
        "existing_node" in (e.detail as Record<string, unknown>)
      ) {
        const parsed = ExistingNodeSchema.safeParse(
          (e.detail as { existing_node: unknown }).existing_node,
        );
        if (parsed.success) {
          setExisting(parsed.data);
          return;
        }
      }
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: e instanceof ApiError ? e.message : String(e),
      });
    },
  });

  return (
    <Stack maw={600} mx="auto" mt="xl">
      <Title order={2}>
        {t("admin.replication.pairing.becomeStandby.title")}
      </Title>
      <Text c="dimmed">
        {t("admin.replication.pairing.becomeStandby.subtitle")}
      </Text>
      <Card withBorder>
        <Stack>
          <TextInput
            label={t("admin.replication.pairing.becomeStandby.pairingUrl")}
            description={t(
              "admin.replication.pairing.becomeStandby.pairingUrlHint",
            )}
            placeholder="https://harpo-1.example/pair?sid=...&t=..."
            value={pairingUrl}
            onChange={(e) => setPairingUrl(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button
              loading={submitMut.isPending}
              disabled={!pairingUrl.trim()}
              onClick={() => submitMut.mutate(false)}
            >
              {t("admin.replication.pairing.becomeStandby.submit")}
            </Button>
          </Group>
        </Stack>
      </Card>
      {existing !== null && (
        <ConfirmReplaceNodeModal
          opened={true}
          existingNode={existing}
          loading={submitMut.isPending}
          onCancel={() => setExisting(null)}
          onConfirm={() => submitMut.mutate(true)}
        />
      )}
    </Stack>
  );
}
