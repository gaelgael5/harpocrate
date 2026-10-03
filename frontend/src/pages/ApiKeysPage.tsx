/**
 * Page de gestion des API keys d'un wallet — LOT_08.
 *
 * Flux de création (crypto côté client) :
 * 1. auth_secret = randomBytes(32)
 * 2. decryption_key = randomBytes(32)
 * 3. auth_salt = randomBytes(16)
 * 4. auth_hash = Argon2id(auth_secret, auth_salt, DEFAULT_KDF_PARAMS)
 * 5. wallet_key = décrypte encrypted_wallet_key du grant via RSA-OAEP
 * 6. encrypted_wallet_key = AES-GCM(wallet_key, decryption_key)
 * 7. encrypted_decryption_key_for_owner = RSA-OAEP(decryption_key, rsa_pub_owner)
 * 8. POST /api-keys avec tous les blobs + auth_secret + decryption_key (one-shot)
 * 9. Afficher le token retourné dans ApiKeyTokenModal
 */
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Stack,
  Title,
  Button,
  Text,
  Group,
  Badge,
  Card,
  Loader,
  Center,
  Alert,
  TextInput,
  Textarea,
  Select,
  Collapse,
  Table,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api-client";
import {
  useApiKeysList,
  useCreateApiKey,
  useRevokeApiKey,
} from "@/hooks/useApiKeys";
import { ApiKeyTokenModal } from "@/components/ApiKeyTokenModal";
import { PermissionsCheckboxes } from "@/components/PermissionsCheckboxes";
import { permissionsToBadges } from "@/schemas/apiKeys";
import { MyGrantResponseSchema } from "@/schemas/grants";
import { generateApiKeyMaterial } from "@/crypto/api-key-material";
import { rsaOaepDecrypt } from "@/crypto/rsa-oaep";
import { useCryptoStore } from "@/stores/crypto";

export function ApiKeysPage() {
  const { t } = useTranslation();
  const { walletId } = useParams<{ walletId: string }>();
  const navigate = useNavigate();

  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey);
  const rsaPublicKey = useCryptoStore((s) => s.rsaPublicKey);
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey);
  const getCachedKey = useCryptoStore((s) => s.getWalletKey);

  const { data, isLoading, error } = useApiKeysList(walletId);
  const createMutation = useCreateApiKey(walletId ?? "");
  const revokeMutation = useRevokeApiKey(walletId ?? "");

  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState(0);
  // 'never' = pas d'expiration, sinon string nombre de jours ('30', '60', '90', '120', '365').
  // Default à 90 jours pour pousser les bonnes pratiques (rotation régulière).
  const [expiresInDays, setExpiresInDays] = useState<string>("90");
  const [isCreating, setIsCreating] = useState(false);
  const [shownToken, setShownToken] = useState<string | null>(null);

  function resetForm() {
    setName("");
    setDescription("");
    setPermissions(0);
    setExpiresInDays("90");
  }

  async function getWalletKey(): Promise<Uint8Array> {
    const wid = walletId ?? "";
    const cached = getCachedKey(wid);
    if (cached) return cached;

    if (!rsaPrivateKey) throw new Error(t("errors.cryptoRequired"));

    // Récupère le grant de l'utilisateur courant pour ce wallet
    const raw = await api.get<unknown>(`/wallets/${wid}/my-grant`);
    const grant = MyGrantResponseSchema.parse(raw);

    const encKeyBytes = Uint8Array.from(atob(grant.encrypted_wallet_key), (c) =>
      c.charCodeAt(0),
    );
    const walletKey = await rsaOaepDecrypt(encKeyBytes, rsaPrivateKey);
    cacheWalletKey(wid, walletKey);
    return walletKey;
  }

  async function handleCreate() {
    if (!name.trim()) {
      notifications.show({ color: "red", message: t("apiKeys.nameRequired") });
      return;
    }
    if (permissions === 0) {
      notifications.show({
        color: "red",
        message: t("apiKeys.permissionsRequired"),
      });
      return;
    }
    if (!rsaPublicKey) {
      notifications.show({ color: "red", message: t("errors.cryptoRequired") });
      return;
    }

    setIsCreating(true);
    try {
      // Éléments de la clé (auth_secret, hash, dkey chiffrée…) — crypto/api-key-material.
      const walletKey = await getWalletKey();
      const material = await generateApiKeyMaterial(walletKey, rsaPublicKey);

      // expires_at — valeur 'never' = pas d'expiration, sinon nombre de jours
      let expiresAt: string | null = null;
      if (expiresInDays !== "never") {
        const days = parseInt(expiresInDays, 10);
        if (!Number.isNaN(days) && days > 0) {
          const d = new Date();
          d.setDate(d.getDate() + days);
          expiresAt = d.toISOString();
        }
      }

      // Création manuelle : la dkey part au serveur, qui assemble le token complet.
      const result = await createMutation.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
        permissions,
        expires_at: expiresAt,
        ...material.body,
        decryption_key: material.decryptionKey,
      });

      setShownToken(result.token);
      resetForm();
      setFormOpen(false);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: msg,
      });
    } finally {
      setIsCreating(false);
    }
  }

  async function handleRevoke(keyId: string) {
    if (!window.confirm(t("apiKeys.revokeConfirm"))) return;
    try {
      await revokeMutation.mutateAsync(keyId);
      notifications.show({
        color: "green",
        message: t("apiKeys.revokeSuccess"),
      });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: msg,
      });
    }
  }

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (error) {
    const msg =
      error instanceof ApiError ? error.message : t("errors.serverError");
    return <Alert color="red">{msg}</Alert>;
  }

  const keys = data?.api_keys ?? [];

  return (
    <Stack>
      <ApiKeyTokenModal
        token={shownToken}
        onClose={() => setShownToken(null)}
      />

      <Group justify="space-between">
        <Title order={2}>{t("apiKeys.title")}</Title>
        <Group>
          <Button
            variant="outline"
            onClick={() => navigate(`/wallets/${walletId ?? ""}`)}
          >
            {t("common.back")}
          </Button>
          <Button onClick={() => setFormOpen((o) => !o)}>
            {formOpen ? t("common.cancel") : t("apiKeys.newKey")}
          </Button>
        </Group>
      </Group>

      {/* Formulaire de création */}
      <Collapse in={formOpen}>
        <Card withBorder p="md">
          <Stack gap="sm">
            <Title order={4}>{t("apiKeys.createTitle")}</Title>

            <TextInput
              label={t("apiKeys.name")}
              required
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              maxLength={256}
            />

            <Textarea
              label={t("apiKeys.description")}
              value={description}
              onChange={(e) => setDescription(e.currentTarget.value)}
              maxLength={1000}
              autosize
              minRows={2}
            />

            <Text size="sm" fw={500}>
              {t("apiKeys.permissions")}
            </Text>
            <PermissionsCheckboxes
              value={permissions}
              onChange={setPermissions}
            />

            <Select
              label={t("apiKeys.expiresInDays")}
              description={t("apiKeys.expiresInDaysHint")}
              data={[
                {
                  value: "30",
                  label: t("apiKeys.expirationOption", { count: 30 }),
                },
                {
                  value: "60",
                  label: t("apiKeys.expirationOption", { count: 60 }),
                },
                {
                  value: "90",
                  label: t("apiKeys.expirationOption", { count: 90 }),
                },
                {
                  value: "120",
                  label: t("apiKeys.expirationOption", { count: 120 }),
                },
                {
                  value: "365",
                  label: t("apiKeys.expirationOption", { count: 365 }),
                },
                { value: "never", label: t("apiKeys.expirationNever") },
              ]}
              value={expiresInDays}
              onChange={(v) => setExpiresInDays(v ?? "90")}
              allowDeselect={false}
              required
            />

            <Group>
              <Button
                onClick={() => void handleCreate()}
                loading={isCreating}
                disabled={!name.trim() || permissions === 0}
              >
                {t("apiKeys.create")}
              </Button>
              <Button
                variant="subtle"
                onClick={() => {
                  resetForm();
                  setFormOpen(false);
                }}
              >
                {t("common.cancel")}
              </Button>
            </Group>
          </Stack>
        </Card>
      </Collapse>

      {/* Liste */}
      {keys.length === 0 ? (
        <Text c="dimmed">{t("apiKeys.noKeys")}</Text>
      ) : (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("apiKeys.name")}</Table.Th>
              <Table.Th>{t("apiKeys.permissions")}</Table.Th>
              <Table.Th>{t("apiKeys.expires")}</Table.Th>
              <Table.Th>{t("apiKeys.lastUsed")}</Table.Th>
              <Table.Th>{t("apiKeys.status")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {keys.map((k) => {
              const isRevoked = k.revoked_at !== null;
              return (
                <Table.Tr key={k.id} style={{ opacity: isRevoked ? 0.5 : 1 }}>
                  <Table.Td>
                    <Text fw={500}>{k.name}</Text>
                    {k.description && (
                      <Text size="xs" c="dimmed">
                        {k.description}
                      </Text>
                    )}
                    {k.connect_client && (
                      <Badge size="xs" variant="light" color="grape">
                        {t("apiKeys.viaApplication", {
                          name: k.connect_client.name,
                        })}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {permissionsToBadges(k.permissions).map((p) => (
                        <Badge key={p} size="xs" variant="light">
                          {t(`permissions.${p}`)}
                        </Badge>
                      ))}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {k.expires_at
                      ? new Date(k.expires_at).toLocaleDateString()
                      : "—"}
                  </Table.Td>
                  <Table.Td>
                    {k.last_used_at
                      ? new Date(k.last_used_at).toLocaleString()
                      : "—"}
                  </Table.Td>
                  <Table.Td>
                    {isRevoked ? (
                      <Badge color="red" size="sm">
                        {t("apiKeys.revoked")}
                      </Badge>
                    ) : (
                      <Badge color="green" size="sm">
                        {t("apiKeys.active")}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {!isRevoked && (
                      <Button
                        size="xs"
                        color="red"
                        variant="outline"
                        loading={revokeMutation.isPending}
                        onClick={() => void handleRevoke(k.id)}
                      >
                        {t("apiKeys.revoke")}
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
