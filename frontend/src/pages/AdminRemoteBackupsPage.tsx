/**
 * AdminRemoteBackupsPage — gestion des connexions de backup distantes (LOT L2).
 *
 * Permet de créer, lister, modifier, supprimer et tester une connexion vers un
 * serveur SFTP/S3/FTPS distant. Les credentials sont chiffrés côté serveur
 * (AES-GCM via clef dérivée de HMAC_KEY) et ne sont jamais retournés en clair.
 *
 * Modèle des paths : chaque connexion stocke deux paths cible — un pour les
 * snapshots automatiques, un pour les fulls manuels. Les deux sont optionnels
 * (une connexion peut n'être utilisable que pour un seul des deux usages).
 * Le bouton "Tester" est désormais à côté de chaque champ path : on teste
 * exactement le path qu'on configure, sans avoir à sauvegarder d'abord.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Text,
  Button,
  Group,
  Table,
  Card,
  Loader,
  Center,
  Alert,
  Modal,
  TextInput,
  PasswordInput,
  Textarea,
  NumberInput,
  Select,
  Switch,
  Badge,
  ActionIcon,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import {
  fetchRemoteBackupConnections,
  createRemoteBackupConnection,
  updateRemoteBackupConnection,
  deleteRemoteBackupConnection,
  testRemoteBackupConnectionConfig,
  testRemoteBackupConnectionStored,
  type RemoteBackupCreatePayload,
  type TestRemoteBackupNewPayload,
} from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";
import type { RemoteBackupConnection } from "@/schemas/admin";

// ─── Form values pour le modal create/edit ────────────────────────────────────

type Kind = "sftp" | "s3" | "ftps" | "gdrive";

type S3Provider = "aws" | "r2" | "b2" | "scaleway" | "ovh" | "custom";

interface FormValues {
  name: string;
  kind: Kind;
  // SFTP + FTPS shared
  host: string;
  port: number | string;
  remote_path_snapshots: string;
  remote_path_full: string;
  username: string;
  password: string;
  // SFTP only
  host_key_fingerprint: string;
  auth_method: "password" | "private_key";
  private_key: string;
  private_key_passphrase: string;
  // FTPS only
  use_tls: boolean;
  // S3 only
  s3_provider: S3Provider;
  s3_r2_account_id: string;
  s3_bucket: string;
  s3_region: string;
  s3_endpoint_url: string;
  s3_prefix_snapshots: string;
  s3_prefix_full: string;
  s3_path_style: boolean;
  s3_access_key_id: string;
  s3_secret_access_key: string;
}

const DEFAULT_FORM: FormValues = {
  name: "",
  kind: "sftp",
  host: "",
  port: 22,
  remote_path_snapshots: "",
  remote_path_full: "",
  username: "",
  password: "",
  host_key_fingerprint: "",
  auth_method: "password",
  private_key: "",
  private_key_passphrase: "",
  use_tls: true,
  s3_provider: "aws",
  s3_r2_account_id: "",
  s3_bucket: "",
  s3_region: "us-east-1",
  s3_endpoint_url: "",
  s3_prefix_snapshots: "",
  s3_prefix_full: "",
  s3_path_style: false,
  s3_access_key_id: "",
  s3_secret_access_key: "",
};

// ─── Mapping providers S3 → endpoint + path-style ────────────────────────────

interface S3ProviderSpec {
  label: string;
  endpointEditable: boolean;
  buildEndpoint: (region: string, accountId: string) => string;
  defaultRegion: string;
  regionPlaceholder: string;
  pathStyle: boolean;
  needsAccountId: boolean;
}

const S3_PROVIDERS: Record<S3Provider, S3ProviderSpec> = {
  aws: {
    label: "AWS S3",
    endpointEditable: false,
    buildEndpoint: () => "",
    defaultRegion: "us-east-1",
    regionPlaceholder: "ex: eu-west-3, us-east-1, ap-southeast-1",
    pathStyle: false,
    needsAccountId: false,
  },
  r2: {
    label: "Cloudflare R2",
    endpointEditable: false,
    buildEndpoint: (_region, accountId) =>
      accountId.trim()
        ? `https://${accountId.trim()}.r2.cloudflarestorage.com`
        : "",
    defaultRegion: "auto",
    regionPlaceholder: "auto",
    pathStyle: true,
    needsAccountId: true,
  },
  b2: {
    label: "Backblaze B2",
    endpointEditable: false,
    buildEndpoint: (region) =>
      region.trim() ? `https://s3.${region.trim()}.backblazeb2.com` : "",
    defaultRegion: "eu-central-003",
    regionPlaceholder: "ex: us-west-001, eu-central-003",
    pathStyle: true,
    needsAccountId: false,
  },
  scaleway: {
    label: "Scaleway Object Storage",
    endpointEditable: false,
    buildEndpoint: (region) =>
      region.trim() ? `https://s3.${region.trim()}.scw.cloud` : "",
    defaultRegion: "fr-par",
    regionPlaceholder: "fr-par, nl-ams, pl-waw",
    pathStyle: false,
    needsAccountId: false,
  },
  ovh: {
    label: "OVH Object Storage",
    endpointEditable: false,
    buildEndpoint: (region) =>
      region.trim() ? `https://s3.${region.trim()}.io.cloud.ovh.net` : "",
    defaultRegion: "gra",
    regionPlaceholder: "gra, sbg, bhs, waw, de",
    pathStyle: false,
    needsAccountId: false,
  },
  custom: {
    label: "Autre (S3-compatible custom)",
    endpointEditable: true,
    buildEndpoint: () => "",
    defaultRegion: "us-east-1",
    regionPlaceholder: "région de ton service",
    pathStyle: true,
    needsAccountId: false,
  },
};

function detectS3Provider(endpoint: string): S3Provider {
  const e = endpoint.toLowerCase().trim();
  if (!e || e.endsWith(".amazonaws.com")) return "aws";
  if (e.includes(".r2.cloudflarestorage.com")) return "r2";
  if (e.includes(".backblazeb2.com")) return "b2";
  if (e.includes(".scw.cloud")) return "scaleway";
  if (e.includes(".io.cloud.ovh.net")) return "ovh";
  return "custom";
}

function extractR2AccountId(endpoint: string): string {
  const m = endpoint.match(
    /^https?:\/\/([^.]+)\.r2\.cloudflarestorage\.com\/?$/i,
  );
  return m?.[1] ?? "";
}

/**
 * En édition : `credentials` absent ⇒ on ne retouche pas les credentials côté
 * serveur (le backend conserve le blob chiffré existant). Le cast vers
 * `RemoteBackupCreatePayload` au call-site est sûr en création (la validation
 * form garantit que tous les champs sont remplis) et toléré en update.
 */
type FormPayload = Omit<RemoteBackupCreatePayload, "credentials"> & {
  credentials?: Record<string, unknown>;
};

/**
 * Construit le `config` à envoyer pour un kind SFTP/FTPS donné, à partir des
 * valeurs du formulaire. Les paths vides ne sont PAS injectés (les deux paths
 * sont optionnels — `resolve_path()` côté backend traite l'absence et la
 * chaîne vide de la même manière).
 */
function buildSftpFtpsConfig(values: FormValues): Record<string, unknown> {
  const defaultPort = values.kind === "ftps" ? 21 : 22;
  const config: Record<string, unknown> = {
    host: values.host.trim(),
    port:
      typeof values.port === "number"
        ? values.port
        : parseInt(String(values.port), 10) || defaultPort,
  };
  if (values.remote_path_snapshots.trim()) {
    config.remote_path_snapshots = values.remote_path_snapshots.trim();
  }
  if (values.remote_path_full.trim()) {
    config.remote_path_full = values.remote_path_full.trim();
  }
  if (values.kind === "sftp" && values.host_key_fingerprint.trim()) {
    config.host_key_fingerprint = values.host_key_fingerprint.trim();
  }
  if (values.kind === "ftps") {
    config.use_tls = values.use_tls;
  }
  return config;
}

function buildS3Config(values: FormValues): Record<string, unknown> {
  const spec = S3_PROVIDERS[values.s3_provider];
  const endpoint = spec.endpointEditable
    ? values.s3_endpoint_url.trim()
    : spec.buildEndpoint(values.s3_region, values.s3_r2_account_id);
  const config: Record<string, unknown> = {
    bucket: values.s3_bucket.trim(),
    region: values.s3_region.trim(),
    path_style: spec.endpointEditable ? values.s3_path_style : spec.pathStyle,
  };
  if (endpoint) {
    config.endpoint_url = endpoint;
  }
  if (values.s3_prefix_snapshots.trim()) {
    config.prefix_snapshots = values.s3_prefix_snapshots.trim();
  }
  if (values.s3_prefix_full.trim()) {
    config.prefix_full = values.s3_prefix_full.trim();
  }
  return config;
}

function buildPayload(values: FormValues, isEditing: boolean): FormPayload {
  const name = values.name.trim();
  if (values.kind === "sftp") {
    const config = buildSftpFtpsConfig(values);
    const secretField =
      values.auth_method === "password" ? values.password : values.private_key;
    const credentialsTouched =
      values.username.trim() !== "" || secretField !== "";
    if (isEditing && !credentialsTouched) {
      return { name, kind: "sftp", config };
    }
    const credentials: Record<string, unknown> = {
      username: values.username.trim(),
      auth_method: values.auth_method,
    };
    if (values.auth_method === "password") {
      credentials.password = values.password;
    } else {
      credentials.private_key = values.private_key;
      if (values.private_key_passphrase) {
        credentials.private_key_passphrase = values.private_key_passphrase;
      }
    }
    return { name, kind: "sftp", config, credentials };
  }
  if (values.kind === "ftps") {
    const config = buildSftpFtpsConfig(values);
    const credentialsTouched =
      values.username.trim() !== "" || values.password !== "";
    if (isEditing && !credentialsTouched) {
      return { name, kind: "ftps", config };
    }
    return {
      name,
      kind: "ftps",
      config,
      credentials: {
        username: values.username.trim(),
        password: values.password,
      },
    };
  }
  // s3
  const config = buildS3Config(values);
  const s3CredentialsTouched =
    values.s3_access_key_id.trim() !== "" || values.s3_secret_access_key !== "";
  if (isEditing && !s3CredentialsTouched) {
    return { name, kind: "s3", config };
  }
  return {
    name,
    kind: "s3",
    config,
    credentials: {
      access_key_id: values.s3_access_key_id.trim(),
      secret_access_key: values.s3_secret_access_key,
    },
  };
}

/**
 * Extrait les credentials du formulaire courant pour un test.
 * Retourne null si les creds ne sont pas (re)saisis : le caller doit alors
 * utiliser l'endpoint "stored" (avec id) au lieu de l'endpoint "config".
 */
function extractCredentialsForTest(
  values: FormValues,
): Record<string, unknown> | null {
  if (values.kind === "sftp") {
    const secret =
      values.auth_method === "password" ? values.password : values.private_key;
    if (!values.username.trim() || !secret) return null;
    const creds: Record<string, unknown> = {
      username: values.username.trim(),
      auth_method: values.auth_method,
    };
    if (values.auth_method === "password") {
      creds.password = values.password;
    } else {
      creds.private_key = values.private_key;
      if (values.private_key_passphrase) {
        creds.private_key_passphrase = values.private_key_passphrase;
      }
    }
    return creds;
  }
  if (values.kind === "ftps") {
    if (!values.username.trim() || !values.password) return null;
    return { username: values.username.trim(), password: values.password };
  }
  // s3
  if (!values.s3_access_key_id.trim() || !values.s3_secret_access_key)
    return null;
  return {
    access_key_id: values.s3_access_key_id.trim(),
    secret_access_key: values.s3_secret_access_key,
  };
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function AdminRemoteBackupsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [editTarget, setEditTarget] = useState<RemoteBackupConnection | null>(
    null,
  );
  const [modalOpen, setModalOpen] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-remote-backups"],
    queryFn: fetchRemoteBackupConnections,
  });

  const createMut = useMutation({
    mutationFn: createRemoteBackupConnection,
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.remoteBackups.createSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-remote-backups"] });
      setModalOpen(false);
      setEditTarget(null);
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

  const updateMut = useMutation({
    mutationFn: (args: { id: string; payload: FormPayload }) =>
      updateRemoteBackupConnection(args.id, {
        name: args.payload.name,
        config: args.payload.config,
        credentials: args.payload.credentials,
      }),
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.remoteBackups.updateSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-remote-backups"] });
      setModalOpen(false);
      setEditTarget(null);
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

  const deleteMut = useMutation({
    mutationFn: deleteRemoteBackupConnection,
    onSuccess: () => {
      notifications.show({
        color: "green",
        message: t("admin.remoteBackups.deleteSuccess"),
      });
      void qc.invalidateQueries({ queryKey: ["admin-remote-backups"] });
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

  function openCreate() {
    setEditTarget(null);
    setModalOpen(true);
  }

  function openEdit(conn: RemoteBackupConnection) {
    setEditTarget(conn);
    setModalOpen(true);
  }

  function confirmDelete(conn: RemoteBackupConnection) {
    modals.openConfirmModal({
      title: t("admin.remoteBackups.deleteConfirmTitle"),
      children: (
        <Text size="sm">
          {t("admin.remoteBackups.deleteConfirmDesc", { name: conn.name })}
        </Text>
      ),
      labels: { confirm: t("common.delete"), cancel: t("common.cancel") },
      confirmProps: { color: "red" },
      onConfirm: () => deleteMut.mutate(conn.id),
    });
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t("admin.remoteBackups.title")}</Title>
        <Button onClick={openCreate}>
          {t("admin.remoteBackups.addConnection")}
        </Button>
      </Group>

      <Text c="dimmed" size="sm">
        {t("admin.remoteBackups.subtitle")}
      </Text>

      {isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {error && (
        <Alert color="red">
          {error instanceof ApiError ? error.message : t("common.error")}
        </Alert>
      )}

      {!isLoading && !error && (data?.connections.length ?? 0) === 0 && (
        <Alert color="blue" variant="light">
          {t("admin.remoteBackups.noConnections")}
        </Alert>
      )}

      {!isLoading && !error && (data?.connections.length ?? 0) > 0 && (
        <Card withBorder>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("admin.remoteBackups.colName")}</Table.Th>
                <Table.Th>{t("admin.remoteBackups.colKind")}</Table.Th>
                <Table.Th>{t("admin.remoteBackups.colHost")}</Table.Th>
                <Table.Th>{t("admin.remoteBackups.colPaths")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data?.connections.map((c) => (
                <Table.Tr key={c.id}>
                  <Table.Td>
                    <Text fw={500}>{c.name}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light">{c.kind}</Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {String(c.config.host ?? "")}:
                      {String(c.config.port ?? "")}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <PathsCell connection={c} />
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <Button
                        size="xs"
                        variant="subtle"
                        onClick={() => openEdit(c)}
                      >
                        {t("common.edit")}
                      </Button>
                      <Button
                        size="xs"
                        variant="subtle"
                        color="red"
                        onClick={() => confirmDelete(c)}
                      >
                        {t("common.delete")}
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      <ConnectionFormModal
        key={editTarget?.id ?? "create"}
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditTarget(null);
        }}
        editTarget={editTarget}
        onSubmit={(payload) => {
          if (editTarget) {
            updateMut.mutate({ id: editTarget.id, payload });
          } else {
            createMut.mutate(payload as RemoteBackupCreatePayload);
          }
        }}
        submitting={createMut.isPending || updateMut.isPending}
      />
    </Stack>
  );
}

/**
 * Affiche les deux paths d'une connexion (snapshots et full) avec une pastille
 * "non configuré" si vide. Le path effectivement utilisé dépend du kind :
 *   - sftp/ftps : remote_path_snapshots / remote_path_full
 *   - s3        : prefix_snapshots      / prefix_full
 */
function PathsCell({ connection }: { connection: RemoteBackupConnection }) {
  const { t } = useTranslation();
  const cfg = connection.config;
  const isS3 = connection.kind === "s3";
  const snapshots = String(
    (isS3 ? cfg.prefix_snapshots : cfg.remote_path_snapshots) ?? "",
  );
  const full = String((isS3 ? cfg.prefix_full : cfg.remote_path_full) ?? "");
  return (
    <Stack gap={2}>
      <Text size="xs">
        <Text component="span" c="dimmed">
          snapshots:
        </Text>{" "}
        {snapshots ? (
          <Text component="span" ff="monospace">
            {snapshots}
          </Text>
        ) : (
          <Text component="span" c="dimmed" fs="italic">
            {t("admin.remoteBackups.pathNotConfigured")}
          </Text>
        )}
      </Text>
      <Text size="xs">
        <Text component="span" c="dimmed">
          full:
        </Text>{" "}
        {full ? (
          <Text component="span" ff="monospace">
            {full}
          </Text>
        ) : (
          <Text component="span" c="dimmed" fs="italic">
            {t("admin.remoteBackups.pathNotConfigured")}
          </Text>
        )}
      </Text>
    </Stack>
  );
}

// ─── Modal create/edit ───────────────────────────────────────────────────────

function ConnectionFormModal({
  opened,
  onClose,
  editTarget,
  onSubmit,
  submitting,
}: {
  opened: boolean;
  onClose: () => void;
  editTarget: RemoteBackupConnection | null;
  onSubmit: (payload: FormPayload) => void;
  submitting: boolean;
}) {
  const { t } = useTranslation();

  const form = useForm<FormValues>({
    initialValues: editTarget
      ? {
          ...DEFAULT_FORM,
          name: editTarget.name,
          kind: editTarget.kind,
          host: String(editTarget.config.host ?? ""),
          port:
            typeof editTarget.config.port === "number"
              ? editTarget.config.port
              : editTarget.kind === "ftps"
                ? 21
                : 22,
          remote_path_snapshots: String(
            editTarget.config.remote_path_snapshots ?? "",
          ),
          remote_path_full: String(editTarget.config.remote_path_full ?? ""),
          host_key_fingerprint: String(
            editTarget.config.host_key_fingerprint ?? "",
          ),
          use_tls:
            typeof editTarget.config.use_tls === "boolean"
              ? editTarget.config.use_tls
              : true,
          s3_provider: detectS3Provider(
            String(editTarget.config.endpoint_url ?? ""),
          ),
          s3_r2_account_id: extractR2AccountId(
            String(editTarget.config.endpoint_url ?? ""),
          ),
          s3_bucket: String(editTarget.config.bucket ?? ""),
          s3_region: String(editTarget.config.region ?? "us-east-1"),
          s3_endpoint_url: String(editTarget.config.endpoint_url ?? ""),
          s3_prefix_snapshots: String(editTarget.config.prefix_snapshots ?? ""),
          s3_prefix_full: String(editTarget.config.prefix_full ?? ""),
          s3_path_style: Boolean(editTarget.config.path_style ?? false),
        }
      : DEFAULT_FORM,
    validate: {
      name: (v) => (!v.trim() ? t("common.required") : null),
      host: (v, values) =>
        values.kind !== "s3" && !v.trim() ? t("common.required") : null,
      username: (v, values) =>
        values.kind !== "s3" && !editTarget && !v.trim()
          ? t("common.required")
          : null,
      password: (v, values) =>
        values.kind === "sftp" &&
        values.auth_method === "password" &&
        !editTarget &&
        !v
          ? t("common.required")
          : values.kind === "ftps" && !editTarget && !v
            ? t("common.required")
            : null,
      private_key: (v, values) =>
        values.kind === "sftp" &&
        values.auth_method === "private_key" &&
        !editTarget &&
        !v
          ? t("common.required")
          : null,
      s3_bucket: (v, values) =>
        values.kind === "s3" && !v.trim() ? t("common.required") : null,
      s3_region: (v, values) =>
        values.kind === "s3" && !v.trim() ? t("common.required") : null,
      s3_access_key_id: (v, values) =>
        values.kind === "s3" && !editTarget && !v.trim()
          ? t("common.required")
          : null,
      s3_secret_access_key: (v, values) =>
        values.kind === "s3" && !editTarget && !v ? t("common.required") : null,
      s3_r2_account_id: (v, values) =>
        values.kind === "s3" && values.s3_provider === "r2" && !v.trim()
          ? t("common.required")
          : null,
    },
  });

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        editTarget
          ? t("admin.remoteBackups.editTitle")
          : t("admin.remoteBackups.addTitle")
      }
      size="lg"
    >
      <form
        onSubmit={form.onSubmit((v) =>
          onSubmit(buildPayload(v, editTarget !== null)),
        )}
      >
        <Stack gap="sm">
          <TextInput
            label={t("admin.remoteBackups.fieldName")}
            description={t("admin.remoteBackups.fieldNameHint")}
            required
            {...form.getInputProps("name")}
          />
          <Select
            label={t("admin.remoteBackups.fieldKind")}
            data={[
              { value: "sftp", label: "SFTP (SSH)" },
              {
                value: "s3",
                label: "S3-compatible (AWS / R2 / B2 / Scaleway / OVH)",
              },
              { value: "ftps", label: "FTPS" },
            ]}
            {...form.getInputProps("kind")}
            allowDeselect={false}
            disabled={editTarget !== null}
            description={
              editTarget ? t("admin.remoteBackups.kindLockedHint") : undefined
            }
          />

          {/* Indicateur visuel de l'état des credentials (zero-knowledge :
              les champs ne se repeuplent jamais). */}
          {editTarget &&
            (editTarget.has_credentials ? (
              <Alert color="green" variant="light">
                {t("admin.remoteBackups.credentialsStoredHint")}
              </Alert>
            ) : (
              <Alert color="orange" variant="light">
                {t("admin.remoteBackups.credentialsMissingHint")}
              </Alert>
            ))}

          {form.values.kind === "sftp" && (
            <SftpFields
              form={form}
              editing={editTarget !== null}
              editTarget={editTarget}
            />
          )}
          {form.values.kind === "ftps" && (
            <FtpsFields
              form={form}
              editing={editTarget !== null}
              editTarget={editTarget}
            />
          )}
          {form.values.kind === "s3" && (
            <S3Fields
              form={form}
              editing={editTarget !== null}
              editTarget={editTarget}
            />
          )}

          <Group justify="flex-end" mt="md">
            <Button variant="subtle" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={submitting}>
              {editTarget ? t("common.save") : t("common.create")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

// ─── PathFieldWithTest : input de path + bouton Tester + résultat inline ────

interface PathTestResult {
  ok: boolean;
  message: string;
}

function PathFieldWithTest({
  label,
  description,
  pathValue,
  onPathChange,
  form,
  editTarget,
}: {
  label: string;
  description?: string;
  pathValue: string;
  onPathChange: (v: string) => void;
  form: ReturnType<typeof useForm<FormValues>>;
  editTarget: RemoteBackupConnection | null;
}) {
  const { t } = useTranslation();
  const [result, setResult] = useState<PathTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  async function runTest() {
    if (!pathValue.trim()) {
      setResult({
        ok: false,
        message: t("admin.remoteBackups.pathEmptyForTest"),
      });
      return;
    }
    setTesting(true);
    setResult(null);
    try {
      const config =
        form.values.kind === "s3"
          ? buildS3Config(form.values)
          : buildSftpFtpsConfig(form.values);
      const credentials = extractCredentialsForTest(form.values);

      // Si l'admin n'a pas (re)saisi les creds en édition, on tape l'endpoint
      // "stored" qui réutilise les creds chiffrés en DB. Sinon on tape
      // l'endpoint "config" avec les creds du formulaire (création ou
      // resaisie en édition).
      const r =
        editTarget && credentials === null
          ? await testRemoteBackupConnectionStored(editTarget.id, {
              path: pathValue.trim(),
              config,
            })
          : credentials === null
            ? {
                ok: false as const,
                error: "no_credentials",
                message: t("admin.remoteBackups.fillCredsForTest"),
              }
            : await testRemoteBackupConnectionConfig({
                kind: form.values.kind,
                config,
                credentials,
                path: pathValue.trim(),
              } satisfies TestRemoteBackupNewPayload);

      if (r.ok) {
        setResult({ ok: true, message: t("admin.remoteBackups.testSuccess") });
      } else {
        setResult({
          ok: false,
          message: r.message || t("admin.remoteBackups.testFailed"),
        });
      }
    } catch (err) {
      setResult({
        ok: false,
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <Stack gap={4}>
      <Group gap="xs" align="end" wrap="nowrap">
        <TextInput
          label={label}
          description={description}
          value={pathValue}
          onChange={(e) => {
            onPathChange(e.currentTarget.value);
            setResult(null);
          }}
          style={{ flex: 1 }}
        />
        <ActionIcon
          variant="light"
          size="lg"
          loading={testing}
          onClick={() => void runTest()}
          aria-label={t("admin.remoteBackups.test")}
          title={t("admin.remoteBackups.test")}
        >
          {/* Loupe simple en SVG inline pour éviter une dep d'icônes */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </ActionIcon>
      </Group>
      {result && (
        <Alert color={result.ok ? "green" : "orange"} variant="light" py={6}>
          <Text size="xs" style={{ whiteSpace: "pre-wrap" }}>
            {result.message}
          </Text>
        </Alert>
      )}
    </Stack>
  );
}

function SftpFields({
  form,
  editing,
  editTarget,
}: {
  form: ReturnType<typeof useForm<FormValues>>;
  editing: boolean;
  editTarget: RemoteBackupConnection | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Group grow>
        <TextInput
          label={t("admin.remoteBackups.fieldHost")}
          required
          {...form.getInputProps("host")}
        />
        <NumberInput
          label={t("admin.remoteBackups.fieldPort")}
          min={1}
          max={65535}
          {...form.getInputProps("port")}
        />
      </Group>
      <PathFieldWithTest
        label={t("admin.remoteBackups.fieldPathSnapshots")}
        description={t("admin.remoteBackups.fieldPathSnapshotsHint")}
        pathValue={form.values.remote_path_snapshots}
        onPathChange={(v) => form.setFieldValue("remote_path_snapshots", v)}
        form={form}
        editTarget={editTarget}
      />
      <PathFieldWithTest
        label={t("admin.remoteBackups.fieldPathFull")}
        description={t("admin.remoteBackups.fieldPathFullHint")}
        pathValue={form.values.remote_path_full}
        onPathChange={(v) => form.setFieldValue("remote_path_full", v)}
        form={form}
        editTarget={editTarget}
      />
      <TextInput
        label={t("admin.remoteBackups.fieldFingerprint")}
        description={t("admin.remoteBackups.fieldFingerprintHint")}
        {...form.getInputProps("host_key_fingerprint")}
      />
      <TextInput
        label={t("admin.remoteBackups.fieldUsername")}
        required={!editing}
        description={
          editing ? t("admin.remoteBackups.usernameEditHint") : undefined
        }
        {...form.getInputProps("username")}
      />
      <Select
        label={t("admin.remoteBackups.fieldAuthMethod")}
        data={[
          { value: "password", label: t("admin.remoteBackups.authPassword") },
          {
            value: "private_key",
            label: t("admin.remoteBackups.authPrivateKey"),
          },
        ]}
        {...form.getInputProps("auth_method")}
        allowDeselect={false}
      />
      {form.values.auth_method === "password" ? (
        <PasswordInput
          label={t("admin.remoteBackups.fieldPassword")}
          description={
            editing ? t("admin.remoteBackups.passwordEditHint") : undefined
          }
          {...form.getInputProps("password")}
        />
      ) : (
        <>
          <Textarea
            label={t("admin.remoteBackups.fieldPrivateKey")}
            description={
              editing ? t("admin.remoteBackups.privateKeyEditHint") : undefined
            }
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----..."
            rows={6}
            {...form.getInputProps("private_key")}
          />
          <PasswordInput
            label={t("admin.remoteBackups.fieldPrivateKeyPassphrase")}
            {...form.getInputProps("private_key_passphrase")}
          />
        </>
      )}
    </>
  );
}

function FtpsFields({
  form,
  editing,
  editTarget,
}: {
  form: ReturnType<typeof useForm<FormValues>>;
  editing: boolean;
  editTarget: RemoteBackupConnection | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Group grow>
        <TextInput
          label={t("admin.remoteBackups.fieldHost")}
          required
          {...form.getInputProps("host")}
        />
        <NumberInput
          label={t("admin.remoteBackups.fieldPort")}
          min={1}
          max={65535}
          {...form.getInputProps("port")}
        />
      </Group>
      <PathFieldWithTest
        label={t("admin.remoteBackups.fieldPathSnapshots")}
        description={t("admin.remoteBackups.fieldPathSnapshotsHint")}
        pathValue={form.values.remote_path_snapshots}
        onPathChange={(v) => form.setFieldValue("remote_path_snapshots", v)}
        form={form}
        editTarget={editTarget}
      />
      <PathFieldWithTest
        label={t("admin.remoteBackups.fieldPathFull")}
        description={t("admin.remoteBackups.fieldPathFullHint")}
        pathValue={form.values.remote_path_full}
        onPathChange={(v) => form.setFieldValue("remote_path_full", v)}
        form={form}
        editTarget={editTarget}
      />
      <Switch
        label={t("admin.remoteBackups.fieldUseTls")}
        description={t("admin.remoteBackups.fieldUseTlsHint")}
        {...form.getInputProps("use_tls", { type: "checkbox" })}
      />
      <TextInput
        label={t("admin.remoteBackups.fieldUsername")}
        required={!editing}
        description={
          editing ? t("admin.remoteBackups.usernameEditHint") : undefined
        }
        {...form.getInputProps("username")}
      />
      <PasswordInput
        label={t("admin.remoteBackups.fieldPassword")}
        description={
          editing ? t("admin.remoteBackups.passwordEditHint") : undefined
        }
        {...form.getInputProps("password")}
      />
    </>
  );
}

function S3Fields({
  form,
  editing,
  editTarget,
}: {
  form: ReturnType<typeof useForm<FormValues>>;
  editing: boolean;
  editTarget: RemoteBackupConnection | null;
}) {
  const { t } = useTranslation();
  const provider: S3Provider = form.values.s3_provider;
  const spec = S3_PROVIDERS[provider];

  return (
    <>
      <Select
        label={t("admin.remoteBackups.fieldS3Provider")}
        description={t("admin.remoteBackups.fieldS3ProviderHint")}
        data={Object.entries(S3_PROVIDERS).map(([value, s]) => ({
          value,
          label: s.label,
        }))}
        allowDeselect={false}
        {...form.getInputProps("s3_provider")}
        onChange={(v) => {
          if (!v) return;
          const next = v as S3Provider;
          const nextSpec = S3_PROVIDERS[next];
          form.setFieldValue("s3_provider", next);
          form.setFieldValue("s3_region", nextSpec.defaultRegion);
        }}
      />

      {spec.needsAccountId && (
        <TextInput
          label={t("admin.remoteBackups.fieldS3R2AccountId")}
          description={t("admin.remoteBackups.fieldS3R2AccountIdHint")}
          placeholder="abc123def456..."
          required
          {...form.getInputProps("s3_r2_account_id")}
        />
      )}

      <TextInput
        label={t("admin.remoteBackups.fieldS3Bucket")}
        required
        {...form.getInputProps("s3_bucket")}
      />

      <TextInput
        label={t("admin.remoteBackups.fieldS3Region")}
        placeholder={spec.regionPlaceholder}
        required
        {...form.getInputProps("s3_region")}
      />

      <PathFieldWithTest
        label={t("admin.remoteBackups.fieldS3PrefixSnapshots")}
        description={t("admin.remoteBackups.fieldS3PrefixSnapshotsHint")}
        pathValue={form.values.s3_prefix_snapshots}
        onPathChange={(v) => form.setFieldValue("s3_prefix_snapshots", v)}
        form={form}
        editTarget={editTarget}
      />
      <PathFieldWithTest
        label={t("admin.remoteBackups.fieldS3PrefixFull")}
        description={t("admin.remoteBackups.fieldS3PrefixFullHint")}
        pathValue={form.values.s3_prefix_full}
        onPathChange={(v) => form.setFieldValue("s3_prefix_full", v)}
        form={form}
        editTarget={editTarget}
      />

      {spec.endpointEditable && (
        <>
          <TextInput
            label={t("admin.remoteBackups.fieldS3Endpoint")}
            description={t("admin.remoteBackups.fieldS3EndpointHint")}
            placeholder="https://s3.example.com"
            required
            {...form.getInputProps("s3_endpoint_url")}
          />
          <Switch
            label={t("admin.remoteBackups.fieldS3PathStyle")}
            description={t("admin.remoteBackups.fieldS3PathStyleHint")}
            {...form.getInputProps("s3_path_style", { type: "checkbox" })}
          />
        </>
      )}

      <TextInput
        label={t("admin.remoteBackups.fieldS3AccessKeyId")}
        required={!editing}
        description={
          editing ? t("admin.remoteBackups.usernameEditHint") : undefined
        }
        {...form.getInputProps("s3_access_key_id")}
      />
      <PasswordInput
        label={t("admin.remoteBackups.fieldS3SecretAccessKey")}
        description={
          editing ? t("admin.remoteBackups.passwordEditHint") : undefined
        }
        {...form.getInputProps("s3_secret_access_key")}
      />
    </>
  );
}
