/**
 * Modale côté master (A) pour démarrer un appairage avec un standby (B) — v2.
 *
 * Flow simplifié LOT 5 :
 *  - Étape 1 : l'admin colle l'URL publique du standby.
 *  - Étape 2 : le backend génère une URL d'appairage signée que l'admin copie
 *    et transmet à l'admin du standby. Ce dernier la collera dans son propre
 *    formulaire « Ajouter en tant que standby » pour démarrer le wizard.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
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

import { initPairingV2 } from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";
import type { PairingInitV2Response } from "@/schemas/pairing";

interface Props {
  opened: boolean;
  onClose: () => void;
}

export function AddStandbyModal({ opened, onClose }: Props) {
  const { t } = useTranslation();
  const [standbyUrl, setStandbyUrl] = useState("");
  const [init, setInit] = useState<PairingInitV2Response | null>(null);
  const [copied, setCopied] = useState(false);

  const initMut = useMutation({
    mutationFn: () => initPairingV2(standbyUrl.trim()),
    onSuccess: (r) => setInit(r),
  });

  function reset() {
    setInit(null);
    setStandbyUrl("");
    setCopied(false);
    initMut.reset();
    onClose();
  }

  async function copyPairingUrl() {
    if (!init) return;
    try {
      await navigator.clipboard.writeText(init.pairing_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard non dispo — l'admin sélectionnera manuellement.
    }
  }

  const errMsg =
    initMut.error instanceof ApiError
      ? initMut.error.message
      : initMut.error
        ? String(initMut.error)
        : null;

  return (
    <Modal
      opened={opened}
      onClose={reset}
      size="lg"
      title={t("admin.replication.pairing.modal.title")}
      // Empêche la fermeture accidentelle une fois l'URL générée : c'est la
      // seule occurrence où l'admin pourra la copier (la session expire après
      // pairing_code_ttl_seconds).
      closeOnClickOutside={init === null}
      closeOnEscape={init === null}
    >
      {!init ? (
        <Stack>
          <Text size="sm" c="dimmed">
            {t("admin.replication.pairing.modal.step1Hint")}
          </Text>
          <TextInput
            label={t("admin.replication.pairing.modal.partnerUrl")}
            value={standbyUrl}
            onChange={(e) => setStandbyUrl(e.currentTarget.value)}
            placeholder="https://harpo-2.example/"
          />
          {errMsg && <Alert color="red">{errMsg}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={reset}>
              {t("common.cancel")}
            </Button>
            <Button
              onClick={() => initMut.mutate()}
              loading={initMut.isPending}
              disabled={!standbyUrl.trim()}
            >
              {t("admin.replication.pairing.modal.generate")}
            </Button>
          </Group>
        </Stack>
      ) : (
        <Stack>
          <Alert color="green">
            {t("admin.replication.pairing.modal.step2Hint", {
              minutes: Math.round(init.expires_in_seconds / 60),
            })}
          </Alert>
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {t("admin.replication.pairing.modal.pairingUrl")}
            </Text>
            <Code
              block
              style={{ wordBreak: "break-all", fontSize: "0.85rem" }}
            >
              {init.pairing_url}
            </Code>
          </Stack>
          <Group justify="space-between">
            <Button
              variant="filled"
              color={copied ? "green" : "blue"}
              onClick={() => void copyPairingUrl()}
            >
              {copied
                ? t("common.copied")
                : t("admin.replication.pairing.modal.copyPairingUrl")}
            </Button>
            <Button variant="default" onClick={reset}>
              {t("common.close")}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
