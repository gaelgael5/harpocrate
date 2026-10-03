/**
 * Registre des applications autorisées à « Se connecter avec Harpocrate » (feature 1).
 *
 * Seules les applications déclarées ici, avec leurs URLs de retour exactes, peuvent
 * demander une API key sur un wallet. Une application se désactive (pas de suppression) :
 * les clés qu'elle a obtenues restent rattachées à une ligne lisible.
 */
import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Center,
  Code,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import { ConnectClientFormModal } from "@/components/ConnectClientFormModal";
import {
  useConnectClients,
  useUpdateConnectClient,
} from "@/hooks/useConnectClients";
import type { ConnectClient } from "@/schemas/connectClients";

interface ClientRowProps {
  client: ConnectClient;
  onEdit: (client: ConnectClient) => void;
}

function ClientRow({ client, onEdit }: ClientRowProps) {
  const { t } = useTranslation();
  const update = useUpdateConnectClient();

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm" fw={500}>
          {client.name}
        </Text>
        {client.description && (
          <Text size="xs" c="dimmed">
            {client.description}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Code>{client.client_id}</Code>
      </Table.Td>
      <Table.Td>
        <Stack gap={2}>
          {client.redirect_uris.map((uri) => (
            <Text key={uri} size="xs" ff="monospace">
              {uri}
            </Text>
          ))}
        </Stack>
      </Table.Td>
      <Table.Td>
        <Badge color={client.active ? "green" : "gray"} size="sm">
          {client.active
            ? t("admin.connectClients.statusActive")
            : t("admin.connectClients.statusDisabled")}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Group gap="xs" justify="flex-end">
          <Button size="xs" variant="default" onClick={() => onEdit(client)}>
            {t("admin.connectClients.edit")}
          </Button>
          <Button
            size="xs"
            variant="light"
            color={client.active ? "red" : "green"}
            loading={update.isPending}
            onClick={() =>
              void update.mutateAsync({
                id: client.id,
                body: { active: !client.active },
              })
            }
          >
            {client.active
              ? t("admin.connectClients.disable")
              : t("admin.connectClients.enable")}
          </Button>
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}

export function AdminConnectClientsPage() {
  const { t } = useTranslation();
  const { data, isLoading, error } = useConnectClients();
  // `undefined` : modale fermée ; `null` : déclaration ; objet : modification.
  const [editing, setEditing] = useState<ConnectClient | null | undefined>(
    undefined,
  );

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert color="red">
        {error instanceof Error ? error.message : t("common.error")}
      </Alert>
    );
  }

  const clients = data?.items ?? [];

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t("admin.connectClients.title")}</Title>
        <Button onClick={() => setEditing(null)}>
          {t("admin.connectClients.declare")}
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {t("admin.connectClients.intro")}
      </Text>

      {clients.length === 0 ? (
        <Text c="dimmed">{t("admin.connectClients.empty")}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("admin.connectClients.colName")}</Table.Th>
              <Table.Th>{t("admin.connectClients.colClientId")}</Table.Th>
              <Table.Th>{t("admin.connectClients.colRedirectUris")}</Table.Th>
              <Table.Th>{t("admin.connectClients.colStatus")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {clients.map((c) => (
              <ClientRow key={c.id} client={c} onEdit={setEditing} />
            ))}
          </Table.Tbody>
        </Table>
      )}

      {editing !== undefined && (
        <ConnectClientFormModal
          key={editing?.id ?? "new"}
          opened
          client={editing}
          onClose={() => setEditing(undefined)}
        />
      )}
    </Stack>
  );
}
