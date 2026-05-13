/**
 * Modale Mantine — confirmation de remplacement d'un node de réplication
 * existant côté master lors d'un nouveau pairing v2.
 *
 * Affichée par BecomeStandbyPage quand l'API renvoie 409 node_already_exists.
 * Sur confirmation, le caller relance accept-v2 avec force=true.
 */
import {
  Alert,
  Button,
  Group,
  Modal,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { ExistingNode } from "@/schemas/pairing";

interface Props {
  opened: boolean;
  existingNode: ExistingNode;
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}

export function ConfirmReplaceNodeModal({
  opened,
  existingNode,
  onConfirm,
  onCancel,
  loading,
}: Props) {
  const { t } = useTranslation();

  const lastSeen = existingNode.last_seen_at
    ? new Date(existingNode.last_seen_at).toLocaleString()
    : t("admin.replication.pairing.becomeStandby.replaceModal.neverSeen");

  return (
    <Modal
      opened={opened}
      onClose={onCancel}
      title={t("admin.replication.pairing.becomeStandby.replaceModal.title")}
      size="lg"
      closeOnClickOutside={false}
    >
      <Stack>
        <Alert color="yellow">
          {t("admin.replication.pairing.becomeStandby.replaceModal.intro")}
        </Alert>
        <Table withTableBorder withColumnBorders>
          <Table.Tbody>
            <Table.Tr>
              <Table.Td>
                {t(
                  "admin.replication.pairing.becomeStandby.replaceModal.existingLabel",
                )}
              </Table.Td>
              <Table.Td>
                <Text size="sm" ff="monospace">
                  {existingNode.label}
                </Text>
              </Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t(
                  "admin.replication.pairing.becomeStandby.replaceModal.existingHost",
                )}
              </Table.Td>
              <Table.Td>{existingNode.host}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t(
                  "admin.replication.pairing.becomeStandby.replaceModal.existingAppName",
                )}
              </Table.Td>
              <Table.Td>{existingNode.application_name}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t(
                  "admin.replication.pairing.becomeStandby.replaceModal.existingState",
                )}
              </Table.Td>
              <Table.Td>{existingNode.last_state ?? "unknown"}</Table.Td>
            </Table.Tr>
            <Table.Tr>
              <Table.Td>
                {t(
                  "admin.replication.pairing.becomeStandby.replaceModal.existingSeen",
                )}
              </Table.Td>
              <Table.Td>{lastSeen}</Table.Td>
            </Table.Tr>
          </Table.Tbody>
        </Table>
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel} disabled={loading}>
            {t(
              "admin.replication.pairing.becomeStandby.replaceModal.cancel",
            )}
          </Button>
          <Button color="red" loading={loading} onClick={onConfirm}>
            {t(
              "admin.replication.pairing.becomeStandby.replaceModal.replace",
            )}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
