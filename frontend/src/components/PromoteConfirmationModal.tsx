/**
 * Modale de confirmation pour la promotion d'un standby en master.
 *
 * Anti-split-brain : exige 2 cases à cocher distinctes avant d'activer le
 * bouton de soumission. L'admin confirme explicitement (a) que l'ancien
 * master est arrêté et (b) qu'il reconfigurera les clients vers ce nouveau
 * master après promotion.
 */
import { useEffect, useState } from "react";
import {
  Modal,
  Stack,
  Alert,
  Checkbox,
  Group,
  Button,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

interface Props {
  opened: boolean;
  masterUrl: string | null;
  onClose: () => void;
  onSubmit: () => void;
  submitting?: boolean;
}

export function PromoteConfirmationModal({
  opened,
  masterUrl,
  onClose,
  onSubmit,
  submitting = false,
}: Props): JSX.Element {
  const { t } = useTranslation();
  const [confirmMasterDown, setConfirmMasterDown] = useState(false);
  const [confirmClientsReconfigured, setConfirmClientsReconfigured] =
    useState(false);

  useEffect(() => {
    if (!opened) {
      setConfirmMasterDown(false);
      setConfirmClientsReconfigured(false);
    }
  }, [opened]);

  const canSubmit =
    confirmMasterDown && confirmClientsReconfigured && !submitting;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("admin.replication.promote.modalTitle")}
      size="lg"
      centered
    >
      <Stack>
        <Alert
          color="orange"
          title={t("admin.replication.promote.warningTitle")}
        >
          {t("admin.replication.promote.warningBody", {
            masterUrl: masterUrl ?? "?",
          })}
        </Alert>
        <Checkbox
          checked={confirmMasterDown}
          onChange={(e) => setConfirmMasterDown(e.currentTarget.checked)}
          label={t("admin.replication.promote.confirmMasterDown")}
        />
        <Checkbox
          checked={confirmClientsReconfigured}
          onChange={(e) =>
            setConfirmClientsReconfigured(e.currentTarget.checked)
          }
          label={t("admin.replication.promote.confirmClientsReconfigured")}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            {t("admin.replication.promote.cancel")}
          </Button>
          <Button color="orange" disabled={!canSubmit} onClick={onSubmit}>
            {t("admin.replication.promote.submit")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
