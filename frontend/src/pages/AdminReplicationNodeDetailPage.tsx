/**
 * AdminReplicationNodeDetailPage — vue détaillée d'un standby PostgreSQL.
 *
 * - Cartouche identité (label, host:port, role, application_name, replication_user)
 * - Sélecteur de fenêtre temporelle (1h / 24h / 7j)
 * - Graph SVG du lag dans le temps (couleur de fond selon l'état)
 * - Tableau des derniers événements significatifs (changements d'état)
 *
 * Pas de dépendance lourde (recharts, etc.) — le graph SVG suffit pour cette
 * volumétrie (~2880 points / jour max, downsamplé à 200 points pour le rendu).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, Link as RouterLink } from "react-router-dom";
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
  Button,
  SegmentedControl,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";

import { fetchStreamingNodeObservations } from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";
import type {
  ReplicationNode,
  ReplicationNodeObservation,
} from "@/schemas/admin";

const WINDOW_OPTIONS = [
  { label: "1h", value: "1" },
  { label: "24h", value: "24" },
  { label: "7j", value: "168" },
] as const;

const STATE_COLORS: Record<ReplicationNodeObservation["state"], string> = {
  streaming: "#a3e6a4", // vert clair
  catchup: "#ffd591", // orange clair
  disconnected: "#ffb1b1", // rouge clair
  unknown: "#dcdcdc", // gris
};

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function AdminReplicationNodeDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ nodeId: string }>();
  const nodeId = params.nodeId ?? "";
  const [hours, setHours] = useState<string>("24");

  const query = useQuery({
    queryKey: ["admin-streaming-node-observations", nodeId, hours],
    queryFn: () => fetchStreamingNodeObservations(nodeId, Number(hours)),
    refetchInterval: 30_000,
    enabled: nodeId !== "",
  });

  if (query.isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (query.error) {
    return (
      <Alert color="red">
        {query.error instanceof ApiError
          ? query.error.message
          : t("common.error")}
      </Alert>
    );
  }

  if (!query.data) return null;

  const { node, observations } = query.data;

  return (
    <Stack>
      <Group justify="space-between">
        <Stack gap={2}>
          <Group gap="xs">
            <Title order={2}>{node.label}</Title>
            <Badge variant="light">{node.role}</Badge>
          </Group>
          <Text c="dimmed" size="sm" ff="monospace">
            {node.host}:{node.port}
          </Text>
        </Stack>
        <Button component={RouterLink} to="/admin/replication" variant="subtle">
          ← {t("admin.replication.streaming.backToList")}
        </Button>
      </Group>

      <NodeIdentityCard node={node} />

      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Title order={4}>
              {t("admin.replication.streaming.lagOverTime")}
            </Title>
            <SegmentedControl
              size="xs"
              data={
                WINDOW_OPTIONS as unknown as { label: string; value: string }[]
              }
              value={hours}
              onChange={setHours}
            />
          </Group>
          {observations.length === 0 ? (
            <Alert color="blue" variant="light">
              {t("admin.replication.streaming.noObservations")}
            </Alert>
          ) : (
            <LagChart observations={observations} />
          )}
        </Stack>
      </Card>

      <RecentStateChangesCard observations={observations} />
    </Stack>
  );
}

function NodeIdentityCard({ node }: { node: ReplicationNode }) {
  const { t } = useTranslation();
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={5}>{t("admin.replication.streaming.identity")}</Title>
        <Group gap="xl">
          <KV
            label={t("admin.replication.streaming.colHost")}
            value={`${node.host}:${node.port}`}
            mono
          />
          <KV
            label={t("admin.replication.streaming.applicationName")}
            value={node.application_name}
            mono
          />
          <KV
            label={t("admin.replication.streaming.replicationUser")}
            value={node.replication_user}
            mono
          />
          <KV
            label={t("admin.replication.streaming.colState")}
            value={node.last_state ?? "unknown"}
          />
          <KV
            label={t("admin.replication.streaming.colLag")}
            value={formatBytes(node.last_lag_bytes)}
          />
        </Group>
        {node.notes && (
          <Text size="sm" c="dimmed">
            {node.notes}
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function KV({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" ff={mono ? "monospace" : undefined}>
        {value}
      </Text>
    </Stack>
  );
}

// ─── Graph SVG du lag ────────────────────────────────────────────────────────

function LagChart({
  observations,
}: {
  observations: ReplicationNodeObservation[];
}) {
  // Downsample : on garde 200 points max pour le rendu (sinon on a un SVG
  // énorme pour ~20k observations sur 7j).
  const sampled = useMemo(() => downsample(observations, 200), [observations]);

  const { paths, segments, maxLag, minTime, maxTime, width, height } = useMemo(
    () => buildChartGeometry(sampled),
    [sampled],
  );

  if (sampled.length === 0) return null;

  return (
    <Stack gap={4}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{
          width: "100%",
          height: 240,
          background: "#fafafa",
          borderRadius: 4,
        }}
        preserveAspectRatio="none"
      >
        {/* Bandes de couleur en arrière-plan selon l'état */}
        {segments.map((s, i) => (
          <rect
            key={i}
            x={s.x}
            y={0}
            width={Math.max(0.5, s.width)}
            height={height}
            fill={STATE_COLORS[s.state]}
            opacity={0.3}
          />
        ))}
        {/* Ligne du lag */}
        <path d={paths.line} stroke="#1971c2" strokeWidth={1.5} fill="none" />
        {/* Aire sous la ligne */}
        <path d={paths.area} fill="#1971c2" opacity={0.1} />
      </svg>
      <Group justify="space-between" px="xs">
        <Text size="xs" c="dimmed">
          {dayjs(minTime).format("YYYY-MM-DD HH:mm")}
        </Text>
        <Text size="xs" c="dimmed">
          max {formatBytes(maxLag)}
        </Text>
        <Text size="xs" c="dimmed">
          {dayjs(maxTime).format("YYYY-MM-DD HH:mm")}
        </Text>
      </Group>
    </Stack>
  );
}

interface Segment {
  x: number;
  width: number;
  state: ReplicationNodeObservation["state"];
}

interface ChartGeometry {
  paths: { line: string; area: string };
  segments: Segment[];
  maxLag: number;
  minTime: number;
  maxTime: number;
  width: number;
  height: number;
}

function buildChartGeometry(obs: ReplicationNodeObservation[]): ChartGeometry {
  const width = 1000;
  const height = 200;
  if (obs.length === 0) {
    return {
      paths: { line: "", area: "" },
      segments: [],
      maxLag: 0,
      minTime: 0,
      maxTime: 0,
      width,
      height,
    };
  }
  const times = obs.map((o) => new Date(o.observed_at).getTime());
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const lags = obs.map((o) => o.lag_bytes ?? 0);
  const maxLag = Math.max(1, ...lags);

  const xOf = (t: number): number =>
    maxTime === minTime ? 0 : ((t - minTime) / (maxTime - minTime)) * width;
  const yOf = (lag: number): number => height - (lag / maxLag) * height;

  const points = obs.map((o, i) => ({
    x: xOf(times[i]!),
    y: yOf(o.lag_bytes ?? 0),
  }));

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");
  const areaPath =
    points.length > 0
      ? `M ${points[0]!.x.toFixed(2)} ${height} ${points
          .map((p) => `L ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
          .join(" ")} L ${points[points.length - 1]!.x.toFixed(2)} ${height} Z`
      : "";

  // Segments d'état : pour chaque pair d'observations consécutives, on
  // crée un rectangle de la couleur de l'état de la 1ere obs.
  const segments: Segment[] = [];
  for (let i = 0; i < obs.length; i++) {
    const xStart = xOf(times[i]!);
    const xEnd = i === obs.length - 1 ? width : xOf(times[i + 1]!);
    segments.push({
      x: xStart,
      width: xEnd - xStart,
      state: obs[i]!.state,
    });
  }

  return {
    paths: { line: linePath, area: areaPath },
    segments,
    maxLag,
    minTime,
    maxTime,
    width,
    height,
  };
}

function downsample(
  obs: ReplicationNodeObservation[],
  maxPoints: number,
): ReplicationNodeObservation[] {
  if (obs.length <= maxPoints) return obs;
  const step = obs.length / maxPoints;
  const result: ReplicationNodeObservation[] = [];
  for (let i = 0; i < maxPoints; i++) {
    result.push(obs[Math.floor(i * step)]!);
  }
  // Garde toujours le dernier point pour ne pas couper la ligne avant la fin.
  if (result[result.length - 1] !== obs[obs.length - 1]) {
    result.push(obs[obs.length - 1]!);
  }
  return result;
}

// ─── Derniers changements d'état ─────────────────────────────────────────────

function RecentStateChangesCard({
  observations,
}: {
  observations: ReplicationNodeObservation[];
}) {
  const { t } = useTranslation();
  const changes = useMemo(
    () => extractStateChanges(observations),
    [observations],
  );

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={5}>
          {t("admin.replication.streaming.recentStateChanges")}
        </Title>
        {changes.length === 0 ? (
          <Text c="dimmed" size="sm">
            {t("admin.replication.streaming.noStateChanges")}
          </Text>
        ) : (
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("admin.replication.streaming.changeAt")}</Table.Th>
                <Table.Th>
                  {t("admin.replication.streaming.changeFrom")}
                </Table.Th>
                <Table.Th>{t("admin.replication.streaming.changeTo")}</Table.Th>
                <Table.Th>{t("admin.replication.streaming.colLag")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {changes
                .slice(-30)
                .reverse()
                .map((c, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>
                      <Text size="xs">
                        {dayjs(c.observed_at).format("YYYY-MM-DD HH:mm:ss")}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" size="sm">
                        {c.from}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" size="sm">
                        {c.to}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {formatBytes(c.lag_bytes)}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  );
}

interface StateChange {
  observed_at: string;
  from: ReplicationNodeObservation["state"];
  to: ReplicationNodeObservation["state"];
  lag_bytes: number | null;
}

function extractStateChanges(obs: ReplicationNodeObservation[]): StateChange[] {
  const out: StateChange[] = [];
  for (let i = 1; i < obs.length; i++) {
    if (obs[i]!.state !== obs[i - 1]!.state) {
      out.push({
        observed_at: obs[i]!.observed_at,
        from: obs[i - 1]!.state,
        to: obs[i]!.state,
        lag_bytes: obs[i]!.lag_bytes,
      });
    }
  }
  return out;
}
