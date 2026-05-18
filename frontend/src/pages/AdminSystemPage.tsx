import { useQuery } from "@tanstack/react-query";
import {
  Stack,
  Title,
  SimpleGrid,
  Card,
  Text,
  Loader,
  Center,
  Alert,
  NumberFormatter,
  Table,
  Badge,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { fetchSystemInfo, fetchAdminWallets } from "@/lib/adminApi";

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card withBorder>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      <Text size="xl" fw={700} mt={4}>
        <NumberFormatter value={value} thousandSeparator />
      </Text>
    </Card>
  );
}

export function AdminSystemPage() {
  const { t } = useTranslation();

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-system-info"],
    queryFn: fetchSystemInfo,
    refetchInterval: 30_000,
  });

  const walletsQuery = useQuery({
    queryKey: ["admin-wallets-list"],
    queryFn: () => fetchAdminWallets({ limit: 200 }),
    refetchInterval: 30_000,
  });

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

  return (
    <Stack>
      <Title order={2}>{t("admin.system.title")}</Title>

      <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }}>
        <StatCard
          label={t("admin.system.users")}
          value={data?.users_count ?? 0}
        />
        <StatCard
          label={t("admin.system.bootstrapped")}
          value={data?.bootstrapped_users_count ?? 0}
        />
        <StatCard
          label={t("admin.system.wallets")}
          value={data?.wallets_count ?? 0}
        />
        <StatCard
          label={t("admin.system.secrets")}
          value={data?.secrets_count ?? 0}
        />
        <StatCard
          label={t("admin.system.apiKeys")}
          value={data?.active_api_keys_count ?? 0}
        />
        <StatCard
          label={t("admin.system.backups")}
          value={data?.backups_count ?? 0}
        />
        <StatCard
          label={t("admin.system.auditEvents")}
          value={data?.audit_events_count ?? 0}
        />
      </SimpleGrid>

      {/* Liste détaillée des coffres avec leur propriétaire */}
      <Title order={3} mt="lg">
        {t("admin.system.walletsTableTitle", "Coffres et propriétaires")}
      </Title>
      {walletsQuery.isLoading && (
        <Center py="md">
          <Loader size="sm" />
        </Center>
      )}
      {walletsQuery.error && (
        <Alert color="red">
          {walletsQuery.error instanceof Error
            ? walletsQuery.error.message
            : t("common.error")}
        </Alert>
      )}
      {walletsQuery.data && (
        <Card withBorder>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("admin.system.colName", "Nom")}</Table.Th>
                <Table.Th>{t("admin.system.colOwner", "Propriétaire")}</Table.Th>
                <Table.Th>{t("admin.system.colSecrets", "Secrets")}</Table.Th>
                <Table.Th>{t("admin.system.colCreated", "Créé le")}</Table.Th>
                <Table.Th>{t("admin.system.colStatus", "État")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {walletsQuery.data.wallets.map((w) => (
                <Table.Tr key={w.id}>
                  <Table.Td>
                    <Text fw={500}>{w.name}</Text>
                    {w.description && (
                      <Text size="xs" c="dimmed">
                        {w.description}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {w.owner.email ? (
                      <>
                        <Text size="sm">{w.owner.display_name ?? "—"}</Text>
                        <Text size="xs" c="dimmed">
                          {w.owner.email}
                        </Text>
                      </>
                    ) : (
                      <Text size="xs" c="dimmed" fs="italic">
                        {t("admin.system.ownerOrphan", "(sans propriétaire)")}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <NumberFormatter
                      value={w.secrets_count}
                      thousandSeparator
                    />
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {new Date(w.created_at).toLocaleDateString()}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {w.deleted_at ? (
                      <Badge color="red" variant="light">
                        {t("admin.system.deleted", "supprimé")}
                      </Badge>
                    ) : (
                      <Badge color="green" variant="light">
                        {t("admin.system.active", "actif")}
                      </Badge>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  );
}
