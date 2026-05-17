/**
 * AdminReplicationPage — état + bascule de la stratégie de réplication (LOT_20).
 *
 * Affiche :
 * - la stratégie active + son état temps réel (interrogation Patroni quand applicable)
 * - la liste des stratégies disponibles
 * - bouton "Activer" pour basculer vers une autre stratégie
 *
 * Les stratégies futures (harpocrate_sync, s3_wal) sont listées mais désactivées
 * tant que leur backend n'est pas implémenté.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Text,
  Card,
  Group,
  Badge,
  Loader,
  Center,
  Alert,
  Table,
  Switch,
  Button,
  Modal,
  TextInput,
  Divider,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  fetchReplicationStrategies,
  fetchReplicationStatus,
  activateReplicationStrategy,
  deactivateReplicationStrategy,
  patroniSwitchover,
  patroniReinit,
  patroniPause,
  patroniResume,
} from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";
import { StreamingNodesPanel } from "@/components/StreamingNodesPanel";
import { PostgresInfoPanel } from "@/components/PostgresInfoPanel";
import { PublicUrlPanel } from "@/components/PublicUrlPanel";
import { AddStandbyModal } from "@/components/AddStandbyModal";
import { PromoteToMasterButton } from "@/components/PromoteToMasterButton";
import { useIsStandby } from "@/lib/useIsStandby";

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "ok" ? "green" : status === "degraded" ? "orange" : "red";
  return <Badge color={color}>{status}</Badge>;
}

// A-9 — Operations Patroni admin (switchover/reinit/pause/resume).
// Visible uniquement quand la strategie active est Patroni.
function PatroniOpsPanel({
  nodes,
}: {
  nodes: Array<Record<string, unknown>>;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [switchoverOpen, setSwitchoverOpen] = useState(false);
  const [reinitOpen, setReinitOpen] = useState(false);
  const [switchoverCandidate, setSwitchoverCandidate] = useState("");
  const [reinitMemberUrl, setReinitMemberUrl] = useState("");
  const [switchoverConfirm, setSwitchoverConfirm] = useState("");
  const [reinitConfirm, setReinitConfirm] = useState("");

  // Detecte si le cluster est en pause via les nodes : un node "paused"
  // s'expose generalement via state, mais Patroni n'expose pas le flag
  // pause au niveau /patroni — il faudrait /cluster. Pour rester simple,
  // on affiche les 2 boutons (pause / resume) et on laisse l'admin
  // choisir. Le backend rejette l'inversion impossible (no_leader).
  const onSuccess = (key: string) => {
    notifications.show({
      color: "green",
      message: t(`admin.replication.patroni.${key}Success`),
    });
    void qc.invalidateQueries({ queryKey: ["replication-status"] });
  };
  const onError = (err: unknown) => {
    const msg = err instanceof ApiError ? err.message : t("common.error");
    notifications.show({ color: "red", message: msg });
  };

  const switchoverMut = useMutation({
    mutationFn: () =>
      patroniSwitchover({
        candidate_name: switchoverCandidate.trim() || undefined,
      }),
    onSuccess: () => {
      onSuccess("switchover");
      setSwitchoverOpen(false);
      setSwitchoverCandidate("");
      setSwitchoverConfirm("");
    },
    onError,
  });

  const reinitMut = useMutation({
    mutationFn: () => patroniReinit(reinitMemberUrl.trim()),
    onSuccess: () => {
      onSuccess("reinit");
      setReinitOpen(false);
      setReinitMemberUrl("");
      setReinitConfirm("");
    },
    onError,
  });

  const pauseMut = useMutation({
    mutationFn: () => patroniPause(),
    onSuccess: () => onSuccess("pause"),
    onError,
  });

  const resumeMut = useMutation({
    mutationFn: () => patroniResume(),
    onSuccess: () => onSuccess("resume"),
    onError,
  });

  const replicaUrls = nodes
    .filter((n) => n.role === "replica")
    .map((n) => String(n.url ?? ""));

  return (
    <>
      <Divider my="md" />
      <Stack gap="xs">
        <Title order={5}>{t("admin.replication.patroni.title")}</Title>
        <Text size="sm" c="dimmed">
          {t("admin.replication.patroni.help")}
        </Text>
        <Group>
          <Button
            color="orange"
            variant="outline"
            onClick={() => setSwitchoverOpen(true)}
          >
            {t("admin.replication.patroni.switchover")}
          </Button>
          <Button
            color="red"
            variant="outline"
            disabled={replicaUrls.length === 0}
            onClick={() => setReinitOpen(true)}
          >
            {t("admin.replication.patroni.reinit")}
          </Button>
          <Button
            variant="outline"
            loading={pauseMut.isPending}
            onClick={() => pauseMut.mutate()}
          >
            {t("admin.replication.patroni.pause")}
          </Button>
          <Button
            variant="outline"
            loading={resumeMut.isPending}
            onClick={() => resumeMut.mutate()}
          >
            {t("admin.replication.patroni.resume")}
          </Button>
        </Group>
      </Stack>

      <Modal
        opened={switchoverOpen}
        onClose={() => setSwitchoverOpen(false)}
        title={t("admin.replication.patroni.switchoverTitle")}
      >
        <Stack>
          <Alert color="orange">
            {t("admin.replication.patroni.switchoverWarning")}
          </Alert>
          <TextInput
            label={t("admin.replication.patroni.candidateLabel")}
            placeholder={t("admin.replication.patroni.candidatePlaceholder")}
            value={switchoverCandidate}
            onChange={(e) => setSwitchoverCandidate(e.currentTarget.value)}
          />
          <TextInput
            label={t("admin.replication.patroni.confirmLabel", {
              expected: "SWITCHOVER",
            })}
            placeholder="SWITCHOVER"
            value={switchoverConfirm}
            onChange={(e) => setSwitchoverConfirm(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button
              variant="subtle"
              onClick={() => setSwitchoverOpen(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              color="orange"
              disabled={switchoverConfirm !== "SWITCHOVER"}
              loading={switchoverMut.isPending}
              onClick={() => switchoverMut.mutate()}
            >
              {t("admin.replication.patroni.switchover")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={reinitOpen}
        onClose={() => setReinitOpen(false)}
        title={t("admin.replication.patroni.reinitTitle")}
      >
        <Stack>
          <Alert color="red">
            {t("admin.replication.patroni.reinitWarning")}
          </Alert>
          <TextInput
            label={t("admin.replication.patroni.memberUrlLabel")}
            placeholder="https://pg2:8008"
            value={reinitMemberUrl}
            onChange={(e) => setReinitMemberUrl(e.currentTarget.value)}
          />
          {replicaUrls.length > 0 && (
            <Stack gap={0}>
              <Text size="xs" c="dimmed">
                {t("admin.replication.patroni.availableReplicas")}:
              </Text>
              {replicaUrls.map((u) => (
                <Text
                  key={u}
                  size="xs"
                  ff="monospace"
                  onClick={() => setReinitMemberUrl(u)}
                  style={{ cursor: "pointer" }}
                  c="blue"
                >
                  {u}
                </Text>
              ))}
            </Stack>
          )}
          <TextInput
            label={t("admin.replication.patroni.confirmLabel", {
              expected: "REINIT",
            })}
            placeholder="REINIT"
            value={reinitConfirm}
            onChange={(e) => setReinitConfirm(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setReinitOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              color="red"
              disabled={
                reinitConfirm !== "REINIT" || !reinitMemberUrl.trim()
              }
              loading={reinitMut.isPending}
              onClick={() => reinitMut.mutate()}
            >
              {t("admin.replication.patroni.reinit")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}


function NodesTable({ nodes }: { nodes: Array<Record<string, unknown>> }) {
  const { t } = useTranslation();
  if (nodes.length === 0) return null;
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={5}>{t("admin.replication.nodes")}</Title>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>URL</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th>Timeline</Table.Th>
              <Table.Th>Lag</Table.Th>
              <Table.Th>Healthy</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {nodes.map((n, i) => (
              <Table.Tr key={i}>
                <Table.Td>
                  <Text size="xs" ff="monospace">
                    {String(n.url ?? "")}
                  </Text>
                </Table.Td>
                <Table.Td>{String(n.role ?? "—")}</Table.Td>
                <Table.Td>{String(n.state ?? "—")}</Table.Td>
                <Table.Td>{String(n.timeline ?? "—")}</Table.Td>
                <Table.Td>{n.lag != null ? String(n.lag) : "—"}</Table.Td>
                <Table.Td>
                  {n.healthy ? (
                    <Badge color="green">✓</Badge>
                  ) : (
                    <Badge color="red">✗</Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  );
}

export function AdminReplicationPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const isStandby = useIsStandby();
  const [addStandbyOpen, setAddStandbyOpen] = useState(false);

  const statusQuery = useQuery({
    queryKey: ["admin-replication-status"],
    queryFn: fetchReplicationStatus,
    refetchInterval: 15_000,
  });

  const strategiesQuery = useQuery({
    queryKey: ["admin-replication-strategies"],
    queryFn: fetchReplicationStrategies,
  });

  // Multi-actives autorisé : Switch indépendant par stratégie. activate/
  // deactivate sont deux endpoints distincts mais on les unifie ici pour
  // simplifier le composant (le résultat n'est pas consommé, juste le
  // succès/erreur compte).
  const toggleMut = useMutation({
    mutationFn: async (args: { id: string; enable: boolean }) => {
      if (args.enable) {
        await activateReplicationStrategy(args.id);
      } else {
        await deactivateReplicationStrategy(args.id);
      }
    },
    onSuccess: (_data, args) => {
      notifications.show({
        color: "green",
        message: args.enable
          ? t("admin.replication.activateSuccess")
          : t("admin.replication.deactivateSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-replication-status"] });
      void qc.invalidateQueries({ queryKey: ["admin-replication-strategies"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: msg,
      });
    },
  });

  return (
    <Stack>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Title order={2}>{t("admin.replication.title")}</Title>
        <Group gap="xs" wrap="nowrap">
          <Button
            onClick={() => setAddStandbyOpen(true)}
            disabled={isStandby}
            variant="filled"
          >
            {t("admin.replication.pairing.addStandby")}
          </Button>
          <Button
            component={Link}
            to="/admin/become-standby"
            variant="light"
            disabled={isStandby}
          >
            {t("admin.replication.pairing.becomeStandby.title")}
          </Button>
        </Group>
      </Group>
      <Text c="dimmed" size="sm">
        {t("admin.replication.subtitle")}
      </Text>

      <AddStandbyModal
        opened={addStandbyOpen}
        onClose={() => setAddStandbyOpen(false)}
      />

      {/* État temps réel */}
      {statusQuery.isLoading && (
        <Center py="md">
          <Loader />
        </Center>
      )}
      {statusQuery.error && (
        <Alert color="red">
          {statusQuery.error instanceof ApiError
            ? statusQuery.error.message
            : t("common.error")}
        </Alert>
      )}
      {statusQuery.data && (
        <Card withBorder>
          <Stack>
            <Group justify="space-between">
              <Title order={4}>{t("admin.replication.activeStrategy")}</Title>
              {statusQuery.data.live && (
                <StatusBadge status={statusQuery.data.live.status} />
              )}
            </Group>
            {statusQuery.data.strategy ? (
              <>
                <Text>
                  <strong>{statusQuery.data.strategy.label}</strong>{" "}
                  <Text span c="dimmed" size="sm">
                    ({statusQuery.data.strategy.type})
                  </Text>
                </Text>
                {statusQuery.data.strategy.description && (
                  <Text size="sm" c="dimmed">
                    {statusQuery.data.strategy.description}
                  </Text>
                )}
                {statusQuery.data.live?.nodes && (
                  <NodesTable nodes={statusQuery.data.live.nodes} />
                )}
                {statusQuery.data.strategy.type === "patroni" && (
                  <PatroniOpsPanel
                    nodes={
                      (statusQuery.data.live?.nodes as
                        | Array<Record<string, unknown>>
                        | undefined) ?? []
                    }
                  />
                )}
              </>
            ) : (
              <Alert color="orange">
                {t("admin.replication.noActiveStrategy")}
              </Alert>
            )}
          </Stack>
        </Card>
      )}

      {/* Liste des stratégies — multi-actives, switch indépendant par strat */}
      {strategiesQuery.data && (
        <Card withBorder>
          <Stack>
            <Title order={4}>
              {t("admin.replication.availableStrategies")}
            </Title>
            <Text size="sm" c="dimmed">
              {t("admin.replication.multiActiveHint")}
            </Text>
            <Stack gap="md">
              {strategiesQuery.data.strategies.map((s) => (
                <Card key={s.id} withBorder padding="sm">
                  <Group justify="space-between">
                    <Stack gap={4}>
                      <Group gap="xs">
                        <Text fw={600}>{s.label}</Text>
                        <Badge variant="light">{s.type}</Badge>
                        {!s.enabled && (
                          <Badge color="gray">
                            {t("admin.replication.disabled")}
                          </Badge>
                        )}
                      </Group>
                      {s.description && (
                        <Text size="sm" c="dimmed">
                          {s.description}
                        </Text>
                      )}
                    </Stack>
                    <Switch
                      label={
                        s.is_active
                          ? t("admin.replication.active")
                          : t("admin.replication.inactive")
                      }
                      checked={s.is_active}
                      disabled={!s.enabled || toggleMut.isPending || isStandby}
                      onChange={(e) =>
                        toggleMut.mutate({
                          id: s.id,
                          enable: e.currentTarget.checked,
                        })
                      }
                    />
                  </Group>
                </Card>
              ))}
            </Stack>
          </Stack>
        </Card>
      )}

      {/* Failover MVP : bouton de promotion. Auto-hide si l'instance n'est
          pas en mode standby (master ou standalone). */}
      <PromoteToMasterButton />

      {/* URL publique de cette instance — à transmettre au pair pour l'appairage. */}
      <PublicUrlPanel />

      {/* Postgres info — paramètres de l'instance courante (master), à
          copier côté standby pour matcher la config de réplication. */}
      <PostgresInfoPanel />

      {/* Streaming async — gestion des standby */}
      <StreamingNodesPanel />
    </Stack>
  );
}
