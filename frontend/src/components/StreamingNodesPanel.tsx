/**
 * StreamingNodesPanel — gestion des standby PostgreSQL streaming async.
 *
 * - Liste des standby attachés à la stratégie streaming_async
 * - État live (last_state, lag, last_seen) refresh par worker backend toutes les 30s
 * - Modale d'ajout : form → backend crée le rôle PG + insert + retourne un bundle
 * - Modale du bundle : affiche les 4 snippets à copier-coller (UNE seule fois)
 * - Bouton "Reload pg_hba.conf" après modif manuelle côté master
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Code,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";

import {
  addStreamingNode,
  deleteStreamingNode,
  fetchLagThresholds,
  fetchStreamingNodes,
  reloadPgHba,
  testStreamingNodeConnect,
  updateLagThresholds,
  type AddStreamingNodePayload,
} from "@/lib/adminApi";
import { useIsStandby } from "@/lib/useIsStandby";
import { ApiError } from "@/lib/api-client";
import type {
  LagThresholds,
  ReplicationNode,
  ReplicationNodeBundle,
  TcpPingResult,
} from "@/schemas/admin";

function formatLag(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function stateColor(state: ReplicationNode["last_state"]): string {
  switch (state) {
    case "streaming":
      return "green";
    case "catchup":
      return "orange";
    case "disconnected":
      return "red";
    default:
      return "gray";
  }
}

export function StreamingNodesPanel() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const isStandby = useIsStandby();
  const [addOpen, setAddOpen] = useState(false);
  const [bundleShown, setBundleShown] = useState<ReplicationNodeBundle | null>(
    null,
  );
  const [thresholdsOpen, setThresholdsOpen] = useState(false);
  // Map node_id → dernier résultat de test connect (affiché inline jusqu'au
  // prochain test). Réinitialisé au refetch global.
  const [pingResults, setPingResults] = useState<Record<string, TcpPingResult>>(
    {},
  );

  const nodes = useQuery({
    queryKey: ["admin-streaming-nodes"],
    queryFn: fetchStreamingNodes,
    refetchInterval: 30_000,
  });

  const deleteMut = useMutation({
    mutationFn: deleteStreamingNode,
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.replication.streaming.deleteSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-streaming-nodes"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("admin.replication.streaming.deleteFailed"),
        message: msg,
        autoClose: 8000,
      });
    },
  });

  const reloadMut = useMutation({
    mutationFn: reloadPgHba,
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.replication.streaming.reloadOk"),
      });
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

  const testConnectMut = useMutation({
    mutationFn: testStreamingNodeConnect,
    onSuccess: (result, nodeId) => {
      setPingResults((prev) => ({ ...prev, [nodeId]: result }));
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

  function confirmDelete(node: ReplicationNode) {
    modals.openConfirmModal({
      title: t("admin.replication.streaming.deleteConfirmTitle"),
      children: (
        <Stack gap="xs">
          <Text size="sm">
            {t("admin.replication.streaming.deleteConfirmDesc", {
              label: node.label,
            })}
          </Text>
          <Alert color="orange" variant="light">
            {t("admin.replication.streaming.deleteConfirmHint")}
          </Alert>
        </Stack>
      ),
      labels: { confirm: t("common.delete"), cancel: t("common.cancel") },
      confirmProps: { color: "red" },
      onConfirm: () => deleteMut.mutate(node.id),
    });
  }

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t("admin.replication.streaming.title")}</Title>
          <Group gap="xs">
            <Button
              size="xs"
              variant="subtle"
              onClick={() => setThresholdsOpen(true)}
            >
              {t("admin.replication.streaming.editThresholds")}
            </Button>
            <Tooltip label={t("admin.replication.streaming.reloadHint")}>
              <Button
                size="xs"
                variant="subtle"
                loading={reloadMut.isPending}
                disabled={isStandby}
                onClick={() => reloadMut.mutate()}
              >
                {t("admin.replication.streaming.reloadPgHba")}
              </Button>
            </Tooltip>
            <Button size="xs" disabled={isStandby} onClick={() => setAddOpen(true)}>
              {t("admin.replication.streaming.add")}
            </Button>
          </Group>
        </Group>

        <Text size="sm" c="dimmed">
          {t("admin.replication.streaming.subtitle")}
        </Text>

        {nodes.isLoading && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}
        {nodes.error && <Alert color="red">{String(nodes.error)}</Alert>}

        {!nodes.isLoading &&
          !nodes.error &&
          (nodes.data?.nodes.length ?? 0) === 0 && (
            <Alert color="blue" variant="light">
              {t("admin.replication.streaming.empty")}
            </Alert>
          )}

        {!nodes.isLoading &&
          !nodes.error &&
          (nodes.data?.nodes.length ?? 0) > 0 && (
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>
                    {t("admin.replication.streaming.colLabel")}
                  </Table.Th>
                  <Table.Th>
                    {t("admin.replication.streaming.colHost")}
                  </Table.Th>
                  <Table.Th>
                    {t("admin.replication.streaming.colRole")}
                  </Table.Th>
                  <Table.Th>
                    {t("admin.replication.streaming.colState")}
                  </Table.Th>
                  <Table.Th>{t("admin.replication.streaming.colLag")}</Table.Th>
                  <Table.Th>
                    {t("admin.replication.streaming.colLastSeen")}
                  </Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {nodes.data?.nodes.map((n) => (
                  <Table.Tr key={n.id}>
                    <Table.Td>
                      <Stack gap={0}>
                        <Text fw={500}>{n.label}</Text>
                        <Text size="xs" c="dimmed" ff="monospace">
                          app: {n.application_name}
                        </Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text size="sm" ff="monospace">
                          {n.host}:{n.port}
                        </Text>
                        {pingResults[n.id] && (
                          <Text
                            size="xs"
                            c={pingResults[n.id]?.ok ? "green" : "red"}
                            title={pingResults[n.id]?.error ?? undefined}
                          >
                            {pingResults[n.id]?.ok
                              ? `✓ TCP ${pingResults[n.id]?.latency_ms}ms`
                              : `✗ ${pingResults[n.id]?.error}`}
                          </Text>
                        )}
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light">{n.role}</Badge>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={stateColor(n.last_state)} variant="light">
                        {n.last_state ?? "unknown"}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {formatLag(n.last_lag_bytes)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {n.last_seen_at
                          ? dayjs(n.last_seen_at).format("YYYY-MM-DD HH:mm:ss")
                          : t("admin.replication.streaming.neverSeen")}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap="xs" justify="flex-end">
                        <Button
                          size="xs"
                          variant="light"
                          loading={
                            testConnectMut.isPending &&
                            testConnectMut.variables === n.id
                          }
                          onClick={() => testConnectMut.mutate(n.id)}
                        >
                          {t("admin.replication.streaming.testConnect")}
                        </Button>
                        <Button
                          size="xs"
                          variant="subtle"
                          component={RouterLink}
                          to={`/admin/replication/streaming/nodes/${n.id}`}
                        >
                          {t("admin.replication.streaming.details")}
                        </Button>
                        <Button
                          size="xs"
                          variant="subtle"
                          color="red"
                          disabled={isStandby}
                          onClick={() => confirmDelete(n)}
                        >
                          {t("common.delete")}
                        </Button>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}

        <AddNodeModal
          opened={addOpen}
          onClose={() => setAddOpen(false)}
          onAdded={(bundle) => {
            setAddOpen(false);
            setBundleShown(bundle);
            void qc.invalidateQueries({ queryKey: ["admin-streaming-nodes"] });
          }}
        />

        <BundleModal
          bundle={bundleShown}
          onClose={() => setBundleShown(null)}
        />

        <ThresholdsModal
          opened={thresholdsOpen}
          onClose={() => setThresholdsOpen(false)}
        />
      </Stack>
    </Card>
  );
}

// ─── Modale seuils de lag ────────────────────────────────────────────────────

function ThresholdsModal({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const current = useQuery({
    queryKey: ["admin-streaming-lag-thresholds"],
    queryFn: fetchLagThresholds,
    enabled: opened,
  });

  const form = useForm<LagThresholds>({
    initialValues: {
      warning_bytes: current.data?.warning_bytes ?? 67108864,
      critical_bytes: current.data?.critical_bytes ?? 536870912,
    },
    validate: {
      warning_bytes: (v) => (v < 0 ? t("common.required") : null),
      critical_bytes: (v, values) =>
        v < values.warning_bytes
          ? t("admin.replication.streaming.thresholdsCriticalLessThanWarning")
          : null,
    },
  });

  // Synchronise le form avec la valeur fetchée. setValues est stable (Mantine
  // useForm), pas besoin de le mettre dans deps.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (current.data) {
      form.setValues({
        warning_bytes: current.data.warning_bytes,
        critical_bytes: current.data.critical_bytes,
      });
    }
  }, [current.data?.warning_bytes, current.data?.critical_bytes]);

  const saveMut = useMutation({
    mutationFn: updateLagThresholds,
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.replication.streaming.thresholdsSaved"),
      });
      void qc.invalidateQueries({
        queryKey: ["admin-streaming-lag-thresholds"],
      });
      onClose();
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
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("admin.replication.streaming.thresholdsTitle")}
      size="md"
    >
      <form onSubmit={form.onSubmit((v) => saveMut.mutate(v))}>
        <Stack gap="sm">
          <Alert color="blue" variant="light">
            {t("admin.replication.streaming.thresholdsHint")}
          </Alert>

          {current.isLoading ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : (
            <>
              <NumberInput
                label={t("admin.replication.streaming.thresholdWarningBytes")}
                description={t(
                  "admin.replication.streaming.thresholdWarningHint",
                )}
                min={0}
                step={1024 * 1024}
                {...form.getInputProps("warning_bytes")}
              />
              <NumberInput
                label={t("admin.replication.streaming.thresholdCriticalBytes")}
                description={t(
                  "admin.replication.streaming.thresholdCriticalHint",
                )}
                min={0}
                step={1024 * 1024}
                {...form.getInputProps("critical_bytes")}
              />
            </>
          )}

          <Group justify="flex-end" mt="md">
            <Button variant="subtle" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={saveMut.isPending}>
              {t("common.save")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

interface AddFormValues {
  label: string;
  host: string;
  port: number | string;
  role: "standby_ro" | "standby_failover_ready" | "archive_only";
  notes: string;
  master_host: string;
  master_port: number | string;
  standby_data_dir: string;
}

function AddNodeModal({
  opened,
  onClose,
  onAdded,
}: {
  opened: boolean;
  onClose: () => void;
  onAdded: (bundle: ReplicationNodeBundle) => void;
}) {
  const { t } = useTranslation();

  const form = useForm<AddFormValues>({
    initialValues: {
      label: "",
      host: "",
      port: 5432,
      role: "standby_ro",
      notes: "",
      master_host: "",
      master_port: 5432,
      standby_data_dir: "/var/lib/postgresql/16/main",
    },
    validate: {
      label: (v) => (!v.trim() ? t("common.required") : null),
      host: (v) => (!v.trim() ? t("common.required") : null),
      master_host: (v) => (!v.trim() ? t("common.required") : null),
    },
  });

  const addMut = useMutation({
    mutationFn: addStreamingNode,
    onSuccess: (resp) => {
      onAdded(resp.bundle);
      form.reset();
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

  function handleSubmit(values: AddFormValues) {
    const payload: AddStreamingNodePayload = {
      label: values.label.trim(),
      host: values.host.trim(),
      port:
        typeof values.port === "number"
          ? values.port
          : Number(values.port) || 5432,
      role: values.role,
      notes: values.notes.trim() || null,
      master_host: values.master_host.trim(),
      master_port:
        typeof values.master_port === "number"
          ? values.master_port
          : Number(values.master_port) || 5432,
      standby_data_dir:
        values.standby_data_dir.trim() || "/var/lib/postgresql/16/main",
    };
    addMut.mutate(payload);
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("admin.replication.streaming.addTitle")}
      size="lg"
    >
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack gap="sm">
          <Alert color="blue" variant="light">
            {t("admin.replication.streaming.addHint")}
          </Alert>

          <TextInput
            label={t("admin.replication.streaming.fieldLabel")}
            description={t("admin.replication.streaming.fieldLabelHint")}
            placeholder="LXC voisin / Standby Paris / …"
            required
            {...form.getInputProps("label")}
          />

          <Group grow>
            <TextInput
              label={t("admin.replication.streaming.fieldStandbyHost")}
              description={t(
                "admin.replication.streaming.fieldStandbyHostHint",
              )}
              placeholder="192.168.10.200"
              required
              {...form.getInputProps("host")}
            />
            <NumberInput
              label={t("admin.replication.streaming.fieldStandbyPort")}
              min={1}
              max={65535}
              {...form.getInputProps("port")}
            />
          </Group>

          <Select
            label={t("admin.replication.streaming.fieldRole")}
            data={[
              {
                value: "standby_ro",
                label: t("admin.replication.streaming.roleStandbyRo"),
              },
              {
                value: "standby_failover_ready",
                label: t("admin.replication.streaming.roleStandbyFailover"),
              },
              {
                value: "archive_only",
                label: t("admin.replication.streaming.roleArchive"),
              },
            ]}
            allowDeselect={false}
            {...form.getInputProps("role")}
          />

          <Group grow>
            <TextInput
              label={t("admin.replication.streaming.fieldMasterHost")}
              description={t("admin.replication.streaming.fieldMasterHostHint")}
              placeholder="192.168.10.158"
              required
              {...form.getInputProps("master_host")}
            />
            <NumberInput
              label={t("admin.replication.streaming.fieldMasterPort")}
              min={1}
              max={65535}
              {...form.getInputProps("master_port")}
            />
          </Group>

          <TextInput
            label={t("admin.replication.streaming.fieldDataDir")}
            description={t("admin.replication.streaming.fieldDataDirHint")}
            {...form.getInputProps("standby_data_dir")}
          />

          <Textarea
            label={t("admin.replication.streaming.fieldNotes")}
            rows={2}
            {...form.getInputProps("notes")}
          />

          <Group justify="flex-end" mt="md">
            <Button variant="subtle" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={addMut.isPending}>
              {t("admin.replication.streaming.addAndShowBundle")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function CopyableSnippet({ title, value }: { title: string; value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // L'API clipboard peut échouer (HTTP non-secure context). On laisse
      // l'utilisateur sélectionner manuellement le texte.
    }
  }

  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text fw={500} size="sm">
          {title}
        </Text>
        <Button size="xs" variant="subtle" onClick={() => void copy()}>
          {copied ? t("common.copied") : t("common.copy")}
        </Button>
      </Group>
      <Code block style={{ whiteSpace: "pre-wrap", fontSize: "0.75rem" }}>
        {value}
      </Code>
    </Stack>
  );
}

function BundleModal({
  bundle,
  onClose,
}: {
  bundle: ReplicationNodeBundle | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  if (bundle === null) return null;

  return (
    <Modal
      opened
      onClose={onClose}
      title={t("admin.replication.streaming.bundleTitle")}
      size="xl"
      // Ne pas autoriser fermeture accidentelle : le password ne sera plus
      // jamais affiché. L'admin doit cliquer explicitement.
      closeOnClickOutside={false}
      closeOnEscape={false}
      withCloseButton={false}
    >
      <Stack>
        <Alert color="orange" variant="light">
          {t("admin.replication.streaming.bundlePasswordWarning")}
        </Alert>

        <CopyableSnippet
          title={`1) ${t("admin.replication.streaming.bundleStep1")}`}
          value={bundle.master_pg_hba_line}
        />

        <CopyableSnippet
          title={`2) ${t("admin.replication.streaming.bundleStep2")}`}
          value={bundle.standby_pg_basebackup_command}
        />

        <CopyableSnippet
          title={`3) ${t("admin.replication.streaming.bundleStep3")}`}
          value={bundle.standby_postgresql_auto_conf}
        />

        <CopyableSnippet
          title={`4) ${t("admin.replication.streaming.bundleStep4")}`}
          value={bundle.standby_signal_command}
        />

        <Group justify="flex-end" mt="md">
          <Button color="red" onClick={onClose}>
            {t("admin.replication.streaming.bundleAcknowledge")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
