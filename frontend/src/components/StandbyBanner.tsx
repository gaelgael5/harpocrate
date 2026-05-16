/**
 * Bandeau global affiché quand cette instance Harpocrate est asservie à un
 * master. Polling toutes les 60s (la valeur change rarement, juste à la fin
 * du wizard d'appairage ou en cas de promote manuel).
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { getStandbyOf } from "@/lib/adminApi";
import { useAdminRole } from "@/hooks/useAdminRole";

export function StandbyBanner() {
  const { t } = useTranslation();
  const isAdmin = useAdminRole();

  const q = useQuery({
    queryKey: ["standby-of"],
    queryFn: getStandbyOf,
    refetchInterval: 60_000,
    retry: false,
    enabled: isAdmin,
  });

  const master = q.data?.is_standby_of;
  if (!master) return null;

  return (
    <Alert
      color="orange"
      title={t("admin.replication.pairing.banner.title")}
      mb="sm"
    >
      <Text size="sm">
        {t("admin.replication.pairing.banner.message", { master })}
      </Text>
    </Alert>
  );
}
