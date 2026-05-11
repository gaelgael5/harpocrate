/**
 * Modale côté master (A) pour démarrer un appairage avec un standby (B).
 *
 * Flow :
 *  - Étape 1 : saisie de l'URL publique du standby
 *  - Étape 2 : affichage du code 4 chiffres + polling du status (3s)
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Code,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import { getPairingStatus, initPairing } from "@/lib/adminApi";
import type { PairingInitResponse } from "@/schemas/pairing";

interface Props {
  opened: boolean;
  onClose: () => void;
}

export function AddStandbyModal({ opened, onClose }: Props) {
  const { t } = useTranslation();
  const [partnerUrl, setPartnerUrl] = useState("");
  const [init, setInit] = useState<PairingInitResponse | null>(null);

  const initMut = useMutation({
    mutationFn: () => initPairing(partnerUrl),
    onSuccess: (r) => setInit(r),
  });

  const statusQuery = useQuery({
    queryKey: ["pairing-status", init?.session_id],
    queryFn: () => getPairingStatus(init!.session_id),
    enabled: !!init,
    refetchInterval: 3000,
  });

  function reset() {
    setInit(null);
    setPartnerUrl("");
    onClose();
  }

  const status = statusQuery.data?.status;

  return (
    <Modal
      opened={opened}
      onClose={reset}
      size="lg"
      title={t("admin.replication.pairing.modal.title")}
    >
      {!init ? (
        <Stack>
          <Text size="sm" c="dimmed">
            {t("admin.replication.pairing.modal.step1Hint")}
          </Text>
          <TextInput
            label={t("admin.replication.pairing.modal.partnerUrl")}
            value={partnerUrl}
            onChange={(e) => setPartnerUrl(e.currentTarget.value)}
            placeholder="https://harpo-2.example/"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={reset}>
              {t("common.cancel")}
            </Button>
            <Button
              onClick={() => initMut.mutate()}
              loading={initMut.isPending}
              disabled={!partnerUrl}
            >
              {t("admin.replication.pairing.modal.generate")}
            </Button>
          </Group>
        </Stack>
      ) : (
        <Stack>
          <Text size="sm" c="dimmed">
            {t("admin.replication.pairing.modal.step2Hint", {
              minutes: Math.round(init.expires_in_seconds / 60),
            })}
          </Text>
          <Group justify="center">
            <Code
              style={{
                fontSize: "2.5rem",
                letterSpacing: "0.5rem",
                padding: "1rem 2rem",
              }}
            >
              {init.code}
            </Code>
          </Group>
          {(status === "pending" ||
            status === "confirmed" ||
            status === "wizard") && (
            <Alert color="blue">
              {t("admin.replication.pairing.modal.waiting")}
            </Alert>
          )}
          {status === "completed" && (
            <Alert color="green">
              {t("admin.replication.pairing.modal.completed")}
            </Alert>
          )}
          {status === "expired" && (
            <Alert color="orange">
              {t("admin.replication.pairing.modal.expired")}
            </Alert>
          )}
          {status === "failed" && (
            <Alert color="red">
              {t("admin.replication.pairing.modal.failed")}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button onClick={reset}>{t("common.close")}</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
