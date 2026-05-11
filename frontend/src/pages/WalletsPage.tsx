import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Button,
  Card,
  Text,
  Group,
  Badge,
  Loader,
  Center,
  Alert,
  SimpleGrid,
  Box,
  Divider,
  Collapse,
  ActionIcon,
  Tooltip,
  Modal,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api-client";
import { WalletListResponseSchema, type WalletItem } from "@/schemas/wallets";
import { hasPermission, PERM_READ } from "@/schemas/grants";
import {
  fetchWalletEnvironments,
  createWalletEnvironment,
  deleteWalletEnvironment,
  type WalletEnvironment,
} from "@/lib/walletEnvironmentsApi";

function WalletCard({ wallet }: { wallet: WalletItem }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <Card
      withBorder
      padding="lg"
      style={{
        cursor: "pointer",
        borderColor: "#dedad2",
        transition: "box-shadow 0.15s, border-color 0.15s",
      }}
      onClick={() => navigate(`/wallets/${wallet.id}`)}
      onMouseEnter={(e) => {
        const el = e.currentTarget;
        el.style.boxShadow = "0 4px 16px rgba(10,10,10,0.09)";
        el.style.borderColor = "#1e40af";
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget;
        el.style.boxShadow = "";
        el.style.borderColor = "#dedad2";
      }}
    >
      {/* Blue top accent bar */}
      <Box
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: "#1e40af",
          borderRadius: "4px 4px 0 0",
          opacity: 0.7,
        }}
      />

      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Text
            fw={600}
            size="sm"
            style={{ letterSpacing: "0.01em", color: "#0a0a0a" }}
          >
            {wallet.name}
          </Text>
          <Group gap={4}>
            {!wallet.is_owner && (
              <Badge color="brand" variant="light" size="xs">
                {t("wallets.shared")}
              </Badge>
            )}
            {wallet.tags.map((tag) => (
              <Badge key={tag} variant="outline" size="xs" color="gray">
                {tag}
              </Badge>
            ))}
          </Group>
        </Group>

        {wallet.description && (
          <Text c="dimmed" size="xs" lineClamp={2}>
            {wallet.description}
          </Text>
        )}

        <Group gap="lg" mt={4}>
          <Text
            size="xs"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              color: "rgba(10,10,10,0.45)",
            }}
          >
            {t("wallets.secretsCount", { count: wallet.valued_secrets_count })}
          </Text>
          {wallet.placeholder_secrets_count > 0 && (
            <Text size="xs" c="orange">
              {t("wallets.placeholdersCount", {
                count: wallet.placeholder_secrets_count,
              })}
            </Text>
          )}
          {hasPermission(wallet.my_permissions, PERM_READ) && (
            <Badge size="xs" color="green" variant="dot">
              {t("grants.perm_read")}
            </Badge>
          )}
        </Group>
      </Stack>
    </Card>
  );
}

function DeletedWalletCard({ wallet }: { wallet: WalletItem }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const purgeAt = wallet.deleted_at
    ? new Date(new Date(wallet.deleted_at).getTime() + 24 * 60 * 60 * 1000)
    : null;

  const restoreMutation = useMutation({
    mutationFn: () => api.post(`/wallets/${wallet.id}/restore`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["wallets"] });
      notifications.show({
        color: "green",
        message: t("wallets.restoreSuccess"),
      });
    },
    onError: () =>
      notifications.show({ color: "red", message: t("wallets.restoreError") }),
  });

  return (
    <Card
      withBorder
      padding="md"
      style={{ borderColor: "#e57373", opacity: 0.85 }}
    >
      <Box
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: "#e57373",
          borderRadius: "4px 4px 0 0",
        }}
      />
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Text fw={600} size="sm" style={{ color: "#0a0a0a" }}>
            {wallet.name}
          </Text>
          {purgeAt && (
            <Text size="xs" c="red">
              {t("wallets.purgeAt", { date: purgeAt.toLocaleString() })}
            </Text>
          )}
        </Stack>
        <Button
          size="xs"
          variant="light"
          color="brand"
          loading={restoreMutation.isPending}
          onClick={() => restoreMutation.mutate()}
        >
          {t("wallets.restore")}
        </Button>
      </Group>
    </Card>
  );
}

/** Section "Environnement" — header + grid des wallets de cet env */
function EnvironmentSection({
  envName,
  envId,
  isVirtualNone,
  wallets,
  onDelete,
}: {
  envName: string;
  envId: string | null;
  isVirtualNone: boolean;
  wallets: WalletItem[];
  onDelete?: (envId: string, envName: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Text fw={600} size="md" style={{ color: "#0a0a0a" }}>
            {envName}
          </Text>
          <Badge variant="outline" size="xs" color="gray">
            {wallets.length}
          </Badge>
        </Group>
        {!isVirtualNone && envId && onDelete && (
          <Tooltip label={t("wallets.environments.delete")}>
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              onClick={() => onDelete(envId, envName)}
            >
              ×
            </ActionIcon>
          </Tooltip>
        )}
      </Group>
      {wallets.length === 0 ? (
        <Text c="dimmed" size="xs" pl="sm">
          {t("wallets.environments.empty")}
        </Text>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {wallets.map((w) => (
            <WalletCard key={w.id} wallet={w} />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}

export function WalletsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [trashOpen, setTrashOpen] = useState(false);
  const [envModalOpen, setEnvModalOpen] = useState(false);
  const [newEnvName, setNewEnvName] = useState("");
  const [envCreateError, setEnvCreateError] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["wallets"],
    queryFn: async () => {
      const raw = await api.get<unknown>("/wallets");
      return WalletListResponseSchema.parse(raw);
    },
  });

  const envQuery = useQuery({
    queryKey: ["wallet-environments"],
    queryFn: fetchWalletEnvironments,
  });

  const createEnvMut = useMutation({
    mutationFn: createWalletEnvironment,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["wallet-environments"] });
      setEnvModalOpen(false);
      setNewEnvName("");
      setEnvCreateError(null);
      notifications.show({
        color: "green",
        message: t("wallets.environments.createSuccess"),
      });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err);
      setEnvCreateError(msg);
    },
  });

  const deleteEnvMut = useMutation({
    mutationFn: deleteWalletEnvironment,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["wallet-environments"] });
      void queryClient.invalidateQueries({ queryKey: ["wallets"] });
      notifications.show({
        color: "green",
        message: t("wallets.environments.deleteSuccess"),
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

  function handleDeleteEnv(envId: string, envName: string) {
    if (
      !window.confirm(
        t("wallets.environments.deleteConfirm", { name: envName }),
      )
    ) {
      return;
    }
    deleteEnvMut.mutate(envId);
  }

  function handleSubmitNewEnv() {
    const trimmed = newEnvName.trim();
    if (!trimmed) {
      setEnvCreateError(t("common.required"));
      return;
    }
    createEnvMut.mutate(trimmed);
  }

  if (isLoading || envQuery.isLoading) {
    return (
      <Center py="xl">
        <Loader color="brand" />
      </Center>
    );
  }

  if (error) {
    const msg =
      error instanceof ApiError ? error.message : t("errors.serverError");
    return <Alert color="red">{msg}</Alert>;
  }

  const wallets = data?.wallets ?? [];
  const deletedWallets = data?.deleted_wallets ?? [];
  const environments: WalletEnvironment[] = envQuery.data ?? [];

  // Groupage des wallets par environment_id (NULL → "None" virtuel).
  const noneWallets = wallets.filter((w) => !w.environment_id);
  const walletsByEnv = new Map<string, WalletItem[]>();
  for (const env of environments) {
    walletsByEnv.set(env.id, []);
  }
  for (const w of wallets) {
    if (w.environment_id && walletsByEnv.has(w.environment_id)) {
      walletsByEnv.get(w.environment_id)!.push(w);
    }
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={2}>{t("wallets.title")}</Title>
        <Group gap="xs">
          <Button variant="default" onClick={() => setEnvModalOpen(true)}>
            {t("wallets.environments.create")}
          </Button>
          <Button variant="default" onClick={() => navigate("/wallets/import")}>
            {t("wallets.import.button")}
          </Button>
          <Button color="brand" onClick={() => navigate("/wallets/new")}>
            {t("wallets.create")}
          </Button>
        </Group>
      </Group>

      {wallets.length === 0 && environments.length === 0 ? (
        <Text c="dimmed">{t("wallets.noWallets")}</Text>
      ) : (
        <Stack gap="lg">
          {/* Section "None" toujours en tête */}
          <EnvironmentSection
            envName={t("wallets.environments.none")}
            envId={null}
            isVirtualNone
            wallets={noneWallets}
          />
          {/* Sections par env (alphabétique = ordre du backend) */}
          {environments.map((env) => (
            <EnvironmentSection
              key={env.id}
              envName={env.name}
              envId={env.id}
              isVirtualNone={false}
              wallets={walletsByEnv.get(env.id) ?? []}
              onDelete={handleDeleteEnv}
            />
          ))}
        </Stack>
      )}

      {/* Modal création environnement */}
      <Modal
        opened={envModalOpen}
        onClose={() => {
          setEnvModalOpen(false);
          setNewEnvName("");
          setEnvCreateError(null);
        }}
        title={t("wallets.environments.createTitle")}
        size="sm"
      >
        <Stack gap="sm">
          <TextInput
            label={t("wallets.environments.nameLabel")}
            placeholder={t("wallets.environments.namePlaceholder")}
            value={newEnvName}
            onChange={(e) => setNewEnvName(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmitNewEnv();
            }}
            autoFocus
            data-testid="env-name-input"
          />
          {envCreateError && (
            <Alert color="red" variant="light">
              {envCreateError}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setEnvModalOpen(false);
                setNewEnvName("");
                setEnvCreateError(null);
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              color="brand"
              onClick={handleSubmitNewEnv}
              loading={createEnvMut.isPending}
              disabled={!newEnvName.trim()}
            >
              {t("wallets.environments.create")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Corbeille */}
      <Divider />
      <Group
        justify="space-between"
        style={{ cursor: "pointer" }}
        onClick={() => setTrashOpen((o) => !o)}
      >
        <Group gap="xs">
          <Text fw={500} size="sm">
            {t("wallets.trash")}
          </Text>
          {deletedWallets.length > 0 && (
            <Badge color="red" variant="light" size="xs">
              {deletedWallets.length}
            </Badge>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          {trashOpen ? "▲" : "▼"}
        </Text>
      </Group>
      <Collapse in={trashOpen}>
        {deletedWallets.length === 0 ? (
          <Text c="dimmed" size="sm">
            {t("wallets.trashEmpty")}
          </Text>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
            {deletedWallets.map((w) => (
              <DeletedWalletCard key={w.id} wallet={w} />
            ))}
          </SimpleGrid>
        )}
      </Collapse>
    </Stack>
  );
}
