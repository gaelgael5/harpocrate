/**
 * AdminUserDetailPage — A-1 du plan de finitions audit.
 *
 * Vue admin agrégée d'un compte utilisateur : infos, identités OIDC,
 * wallets owned/shared, anomalies récentes, audit log recent, et les
 * actions admin (Lot 4A) : disable/enable, lever quarantaine, toggle
 * force_reverify, délier une identité OIDC.
 *
 * Toutes les actions invalident la query `["admin-user-detail", userId]`
 * pour refléter immédiatement l'état post-action.
 */
import { useState } from "react";
import { useParams, Link as RouterLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Text,
  Group,
  Card,
  Badge,
  Button,
  Modal,
  TextInput,
  Switch,
  Alert,
  Table,
  Loader,
  Center,
  Tooltip,
  Anchor,
  Divider,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";

import {
  fetchAdminUserDetail,
  disableAdminUser,
  enableAdminUser,
  clearAdminUserQuarantine,
  setAdminUserForceReverify,
  unlinkAdminUserIdentity,
} from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";


function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return dayjs(iso).format("YYYY-MM-DD HH:mm:ss");
}


function StatusBadges({
  disabledAt,
  quarantineUntil,
  forceReverify,
}: {
  disabledAt: string | null;
  quarantineUntil: string | null;
  forceReverify: boolean;
}) {
  const { t } = useTranslation();
  const items: { color: string; label: string }[] = [];
  if (disabledAt) {
    items.push({ color: "red", label: t("admin.userDetail.statusDisabled") });
  }
  if (quarantineUntil) {
    items.push({
      color: "orange",
      label: t("admin.userDetail.statusQuarantine"),
    });
  }
  if (forceReverify) {
    items.push({
      color: "yellow",
      label: t("admin.userDetail.statusForceReverify"),
    });
  }
  if (items.length === 0) {
    items.push({ color: "green", label: t("admin.userDetail.statusActive") });
  }
  return (
    <Group gap="xs">
      {items.map((it) => (
        <Badge key={it.label} color={it.color}>
          {it.label}
        </Badge>
      ))}
    </Group>
  );
}


function DisableModal({
  userId,
  opened,
  onClose,
}: {
  userId: string;
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () => disableAdminUser(userId, reason),
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.userDetail.disableSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-user-detail", userId] });
      setReason("");
      onClose();
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof ApiError ? err.message : t("admin.userDetail.disableError");
      notifications.show({ color: "red", message: msg });
    },
  });

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("admin.userDetail.disableTitle")}
    >
      <Stack>
        <Alert color="red">{t("admin.userDetail.disableWarning")}</Alert>
        <TextInput
          label={t("admin.userDetail.disableReasonLabel")}
          placeholder={t("admin.userDetail.disableReasonPlaceholder")}
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            color="red"
            loading={mutation.isPending}
            disabled={reason.trim().length === 0}
            onClick={() => mutation.mutate()}
          >
            {t("admin.userDetail.disableConfirm")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}


export function AdminUserDetailPage() {
  const { t } = useTranslation();
  const { userId } = useParams<{ userId: string }>();
  const qc = useQueryClient();
  const [disableOpen, setDisableOpen] = useState(false);

  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["admin-user-detail", userId],
    queryFn: () => fetchAdminUserDetail(userId!),
    enabled: !!userId,
  });

  const enableMut = useMutation({
    mutationFn: () => enableAdminUser(userId!),
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.userDetail.enableSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-user-detail", userId] });
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      notifications.show({ color: "red", message: msg });
    },
  });

  const clearQuarantineMut = useMutation({
    mutationFn: () => clearAdminUserQuarantine(userId!),
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.userDetail.quarantineClearSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-user-detail", userId] });
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      notifications.show({ color: "red", message: msg });
    },
  });

  const forceReverifyMut = useMutation({
    mutationFn: (enabled: boolean) =>
      setAdminUserForceReverify(userId!, enabled),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin-user-detail", userId] });
    },
    onError: (err: unknown) => {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      notifications.show({ color: "red", message: msg });
    },
  });

  const unlinkIdentityMut = useMutation({
    mutationFn: (identityId: string) =>
      unlinkAdminUserIdentity(userId!, identityId),
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.userDetail.unlinkSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-user-detail", userId] });
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof ApiError ? err.message : t("admin.userDetail.unlinkError");
      notifications.show({ color: "red", message: msg });
    },
  });

  if (isLoading) {
    return (
      <Center mih={200}>
        <Loader />
      </Center>
    );
  }
  if (error) {
    const msg = error instanceof ApiError ? error.message : t("errors.serverError");
    return <Alert color="red">{msg}</Alert>;
  }
  if (!detail) {
    return <Alert color="red">{t("admin.userDetail.notFound")}</Alert>;
  }

  const u = detail.user;
  const isDisabled = !!u.disabled_at;
  const isQuarantined =
    !!u.quarantine_until && new Date(u.quarantine_until) > new Date();

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Anchor component={RouterLink} to="/admin/users" size="sm">
            ← {t("admin.userDetail.backToList")}
          </Anchor>
          <Title order={2}>{u.email}</Title>
          <StatusBadges
            disabledAt={u.disabled_at}
            quarantineUntil={u.quarantine_until}
            forceReverify={u.force_reverify_next_login}
          />
        </Group>
      </Group>

      {/* Info card */}
      <Card withBorder>
        <Stack gap="xs">
          <Title order={4}>{t("admin.userDetail.info")}</Title>
          <Group>
            <Text fw={500} w={180}>
              {t("admin.userDetail.email")}
            </Text>
            <Text>{u.email}</Text>
          </Group>
          <Group>
            <Text fw={500} w={180}>
              {t("admin.userDetail.displayName")}
            </Text>
            <Text>{u.display_name ?? "—"}</Text>
          </Group>
          <Group>
            <Text fw={500} w={180}>
              {t("admin.userDetail.createdAt")}
            </Text>
            <Text>{formatDate(u.created_at)}</Text>
          </Group>
          <Group>
            <Text fw={500} w={180}>
              {t("admin.userDetail.lastUnlockAt")}
            </Text>
            <Text>{formatDate(u.last_unlock_at)}</Text>
          </Group>
          <Group>
            <Text fw={500} w={180}>
              {t("admin.userDetail.bootstrap")}
            </Text>
            <Badge color={u.has_bootstrap ? "green" : "gray"}>
              {u.has_bootstrap
                ? t("admin.userDetail.bootstrapDone")
                : t("admin.userDetail.bootstrapPending")}
            </Badge>
          </Group>
          {u.disabled_at && (
            <Group>
              <Text fw={500} w={180}>
                {t("admin.userDetail.disabledAt")}
              </Text>
              <Text>
                {formatDate(u.disabled_at)}
                {u.disabled_reason && ` — ${u.disabled_reason}`}
              </Text>
            </Group>
          )}
          {u.quarantine_until && (
            <Group>
              <Text fw={500} w={180}>
                {t("admin.userDetail.quarantineUntil")}
              </Text>
              <Text>
                {formatDate(u.quarantine_until)}
                {u.quarantine_reason && ` — ${u.quarantine_reason}`}
              </Text>
            </Group>
          )}
        </Stack>
      </Card>

      {/* Actions admin */}
      <Card withBorder>
        <Stack>
          <Title order={4}>{t("admin.userDetail.actions")}</Title>
          <Group>
            {isDisabled ? (
              <Button
                color="green"
                loading={enableMut.isPending}
                onClick={() => enableMut.mutate()}
              >
                {t("admin.userDetail.enable")}
              </Button>
            ) : (
              <Button color="red" onClick={() => setDisableOpen(true)}>
                {t("admin.userDetail.disable")}
              </Button>
            )}
            {isQuarantined && (
              <Button
                color="orange"
                variant="outline"
                loading={clearQuarantineMut.isPending}
                onClick={() => clearQuarantineMut.mutate()}
              >
                {t("admin.userDetail.quarantineClear")}
              </Button>
            )}
            <Tooltip label={t("admin.userDetail.forceReverifyHelp")}>
              <Switch
                label={t("admin.userDetail.forceReverify")}
                checked={u.force_reverify_next_login}
                onChange={(e) =>
                  forceReverifyMut.mutate(e.currentTarget.checked)
                }
                disabled={forceReverifyMut.isPending}
              />
            </Tooltip>
          </Group>
        </Stack>
      </Card>

      {/* Identities */}
      <Card withBorder>
        <Stack>
          <Title order={4}>
            {t("admin.userDetail.identities")} ({detail.identities.length})
          </Title>
          {detail.identities.length === 0 ? (
            <Text c="dimmed">{t("admin.userDetail.noIdentities")}</Text>
          ) : (
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("admin.userDetail.identityProvider")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.identitySubject")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.identityLinkedAt")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.identityLastLogin")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.primary")}</Table.Th>
                  <Table.Th></Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {detail.identities.map((id) => (
                  <Table.Tr key={id.id}>
                    <Table.Td>{id.provider}</Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {id.external_subject}
                      </Text>
                    </Table.Td>
                    <Table.Td>{formatDate(id.linked_at)}</Table.Td>
                    <Table.Td>{formatDate(id.last_login_at)}</Table.Td>
                    <Table.Td>
                      {id.is_primary ? <Badge color="blue">✓</Badge> : "—"}
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="subtle"
                        color="red"
                        loading={unlinkIdentityMut.isPending}
                        disabled={detail.identities.length <= 1}
                        onClick={() => {
                          if (
                            confirm(
                              t("admin.userDetail.unlinkConfirm", {
                                provider: id.provider,
                              }),
                            )
                          ) {
                            unlinkIdentityMut.mutate(id.id);
                          }
                        }}
                      >
                        {t("admin.userDetail.unlink")}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>

      {/* Wallets summary */}
      <Card withBorder>
        <Stack>
          <Title order={4}>{t("admin.userDetail.wallets")}</Title>
          <Group>
            <Text>
              <strong>{detail.wallets.owned_count}</strong>{" "}
              {t("admin.userDetail.walletsOwned")}
            </Text>
            <Divider orientation="vertical" />
            <Text>
              <strong>{detail.wallets.shared_count}</strong>{" "}
              {t("admin.userDetail.walletsShared")}
            </Text>
          </Group>
          {detail.wallets.recent_owned.length > 0 && (
            <Stack gap="xs">
              <Text fw={500}>{t("admin.userDetail.walletsRecent")}</Text>
              {detail.wallets.recent_owned.map((w) => (
                <Text key={w.id} size="sm">
                  • {w.name}{" "}
                  <Text span size="xs" c="dimmed">
                    ({formatDate(w.created_at)})
                  </Text>
                </Text>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

      {/* Anomalies */}
      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Title order={4}>{t("admin.userDetail.anomalies")}</Title>
            <Group gap="xs">
              <Badge color="gray">
                {t("admin.userDetail.anomaliesTotal", {
                  n: detail.anomalies.total_count,
                })}
              </Badge>
              {detail.anomalies.unacknowledged_count > 0 && (
                <Badge color="orange">
                  {t("admin.userDetail.anomaliesUnack", {
                    n: detail.anomalies.unacknowledged_count,
                  })}
                </Badge>
              )}
            </Group>
          </Group>
          {detail.anomalies.recent.length === 0 ? (
            <Text c="dimmed">{t("admin.userDetail.noAnomalies")}</Text>
          ) : (
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("admin.userDetail.detectedAt")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.severity")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.anomalyType")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.acknowledged")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {detail.anomalies.recent.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>{formatDate(a.detected_at)}</Table.Td>
                    <Table.Td>
                      <Badge
                        color={
                          a.severity === "critical"
                            ? "red"
                            : a.severity === "warning"
                              ? "orange"
                              : "blue"
                        }
                      >
                        {a.severity}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{a.anomaly_type}</Table.Td>
                    <Table.Td>{a.acknowledged_at ? "✓" : "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>

      {/* Audit recent */}
      <Card withBorder>
        <Stack>
          <Title order={4}>{t("admin.userDetail.recentAudit")}</Title>
          {detail.recent_audit.length === 0 ? (
            <Text c="dimmed">{t("admin.userDetail.noAudit")}</Text>
          ) : (
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("admin.userDetail.occurredAt")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.action")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.success")}</Table.Th>
                  <Table.Th>{t("admin.userDetail.ip")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {detail.recent_audit.map((ev) => (
                  <Table.Tr key={ev.id}>
                    <Table.Td>{formatDate(ev.occurred_at)}</Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {ev.action}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={ev.success ? "green" : "red"}>
                        {ev.success ? "✓" : "✗"}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{ev.actor_ip ?? "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>

      <DisableModal
        userId={userId!}
        opened={disableOpen}
        onClose={() => setDisableOpen(false)}
      />
    </Stack>
  );
}
