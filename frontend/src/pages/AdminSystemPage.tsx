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
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { fetchSystemInfo } from "@/lib/adminApi";

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
    </Stack>
  );
}
