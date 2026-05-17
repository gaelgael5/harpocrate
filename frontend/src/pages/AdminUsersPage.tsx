import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Table,
  Text,
  Badge,
  Loader,
  Center,
  Alert,
  Group,
  Button,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";

import { Link as RouterLink } from "react-router-dom";

import { fetchAdminUsers } from "@/lib/adminApi";
import type { AdminUser } from "@/schemas/admin";

const PAGE_SIZE = 50;

function UserRow({ user }: { user: AdminUser }) {
  const { t } = useTranslation();

  return (
    <Table.Tr>
      <Table.Td>
        <Text
          component={RouterLink}
          to={`/admin/users/${user.id}`}
          size="sm"
          c="blue"
          style={{ textDecoration: "none" }}
        >
          {user.email}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {user.display_name ?? "—"}
        </Text>
      </Table.Td>
      <Table.Td>
        <Badge color={user.has_bootstrap ? "green" : "gray"} size="sm">
          {user.has_bootstrap ? t("admin.users.yes") : t("admin.users.no")}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {dayjs(user.created_at).format("YYYY-MM-DD")}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="xs" c="dimmed">
          {user.last_unlock_at
            ? dayjs(user.last_unlock_at).format("YYYY-MM-DD HH:mm")
            : t("admin.users.never")}
        </Text>
      </Table.Td>
      <Table.Td>
        {user.quarantine_until && (
          <Badge color="orange" size="sm">
            {t("admin.users.quarantine")}
          </Badge>
        )}
        {user.disabled_at && (
          <Badge color="red" size="sm">
            {t("admin.users.disabled")}
          </Badge>
        )}
      </Table.Td>
    </Table.Tr>
  );
}

export function AdminUsersPage() {
  const { t } = useTranslation();
  const [offset, setOffset] = useState(0);

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-users", offset],
    queryFn: () => fetchAdminUsers({ limit: PAGE_SIZE, offset }),
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

  const total = data?.total ?? 0;
  const users = data?.users ?? [];

  return (
    <Stack>
      <Title order={2}>{t("admin.users.title")}</Title>
      <Text size="sm" c="dimmed">
        {t("admin.users.total", { count: total })}
      </Text>

      {users.length === 0 ? (
        <Text c="dimmed">{t("admin.users.noUsers")}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("admin.users.email")}</Table.Th>
              <Table.Th>{t("admin.users.displayName")}</Table.Th>
              <Table.Th>{t("admin.users.hasBootstrap")}</Table.Th>
              <Table.Th>{t("admin.users.createdAt")}</Table.Th>
              <Table.Th>{t("admin.users.lastUnlock")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.map((u) => (
              <UserRow key={u.id} user={u} />
            ))}
          </Table.Tbody>
        </Table>
      )}

      {total > PAGE_SIZE && (
        <Group justify="center">
          <Button
            variant="outline"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            ←
          </Button>
          <Text size="sm">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}
          </Text>
          <Button
            variant="outline"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            →
          </Button>
        </Group>
      )}
    </Stack>
  );
}
