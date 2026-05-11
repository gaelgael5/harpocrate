/**
 * Secret detail page — shows metadata, decrypts and displays value on demand.
 *
 * Decrypt flow:
 * 1. GET /v1/wallets/{id}/secrets/by-id/{secret_id} → encrypted_value + encrypted_wallet_key
 * 2. Decrypt wallet_key using rsa_priv (RSA-OAEP)
 * 3. Decrypt value using wallet_key (AES-GCM)
 * 4. Show for 30 seconds then auto-hide
 */
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Button,
  Text,
  Group,
  Badge,
  Paper,
  Code,
  Loader,
  Center,
  Alert,
  ActionIcon,
  Tooltip,
  PasswordInput,
  Breadcrumbs,
  Anchor,
  Modal,
  Textarea,
  TagsInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api-client";
import { invalidateWalletQueries } from "@/lib/walletQueries";
import { SecretDetailResponseSchema } from "@/schemas/secrets";
import { rsaOaepDecrypt } from "@/crypto/rsa-oaep";
import { aesGcmDecrypt, aesGcmEncrypt } from "@/crypto/aes-gcm";
import {
  fromBase64,
  toBase64,
  bytesToText,
  textToBytes,
} from "@/crypto/helpers";
import { useCryptoStore } from "@/stores/crypto";

const SHOW_TIMEOUT_SECS = 30;

export function SecretDetailPage() {
  const { t } = useTranslation();
  const { walletId, secretId } = useParams<{
    walletId: string;
    secretId: string;
  }>();
  const navigate = useNavigate();
  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey);
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey);
  const getCachedKey = useCryptoStore((s) => s.getWalletKey);

  const queryClient = useQueryClient();
  const [shownValue, setShownValue] = useState<string | null>(null);
  const [showCountdown, setShowCountdown] = useState<number | null>(null);
  const [isDecrypting, setIsDecrypting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [decryptError, setDecryptError] = useState<string | null>(null);
  // Modale d'édition des métadonnées (description + tags) — séparée du flow
  // edit value (qui touche au crypto). Les champs sont initialisés depuis
  // `secret` à l'ouverture de la modale.
  const [isEditingMeta, setIsEditingMeta] = useState(false);
  const [metaDescription, setMetaDescription] = useState("");
  const [metaTags, setMetaTags] = useState<string[]>([]);
  const [isSavingMeta, setIsSavingMeta] = useState(false);

  function openMetaModal() {
    if (!secret) return;
    setMetaDescription(secret.description ?? "");
    setMetaTags([...secret.tags]);
    setIsEditingMeta(true);
  }

  async function handleSaveMeta() {
    if (!secret || isSavingMeta) return;
    setIsSavingMeta(true);
    try {
      await api.patch<unknown>(
        `/wallets/${walletId}/secrets/by-id/${secret.id}`,
        {
          description: metaDescription.trim() || null,
          tags: metaTags,
        },
      );
      notifications.show({ color: "green", message: t("secrets.meta_saved") });
      setIsEditingMeta(false);
      void queryClient.invalidateQueries({
        queryKey: ["secret-detail", walletId, secretId],
      });
      invalidateWalletQueries(queryClient, walletId ?? "");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: msg,
      });
    } finally {
      setIsSavingMeta(false);
    }
  }

  async function handleSaveEdit() {
    if (!secret || isSaving) return;
    if (!editValue) return;
    setIsSaving(true);
    try {
      const walletKey = await getWalletKey();
      const plainBytes = textToBytes(editValue);
      const encValue = await aesGcmEncrypt(plainBytes, walletKey);
      await api.put<unknown>(
        `/wallets/${walletId}/secrets/by-id/${secret.id}`,
        { encrypted_value: toBase64(encValue) },
      );
      notifications.show({
        color: "green",
        message: t("secrets.edit_success"),
      });
      setIsEditing(false);
      setEditValue("");
      setShownValue(null);
      // refresh la query
      await queryClient.invalidateQueries({
        queryKey: ["secret", walletId, secret.id],
      });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: msg,
      });
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete() {
    if (!secret || isDeleting) return;
    if (!window.confirm(t("secrets.delete_confirm", { name: secret.name })))
      return;
    setIsDeleting(true);
    try {
      await api.delete<unknown>(
        `/wallets/${walletId}/secrets/by-id/${secret.id}`,
      );
      notifications.show({
        color: "green",
        message: t("secrets.delete_success"),
      });
      // Invalide TOUTES les queries du wallet (compteurs, tree, sidebar arbre,
      // listes par path) avant de retourner — sinon TanStack Query sert l'ancien cache.
      if (walletId) await invalidateWalletQueries(queryClient, walletId);
      navigate(`/wallets/${walletId}`);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      notifications.show({
        color: "red",
        title: t("common.error"),
        message: msg,
      });
    } finally {
      setIsDeleting(false);
    }
  }

  const {
    data: secret,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["secret", walletId, secretId],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId ?? ""}/secrets/by-id/${secretId ?? ""}`,
      );
      return SecretDetailResponseSchema.parse(raw);
    },
    enabled: !!walletId && !!secretId,
  });

  async function getWalletKey(): Promise<Uint8Array> {
    const cached = getCachedKey(walletId ?? "");
    if (cached) return cached;

    if (!rsaPrivateKey) throw new Error(t("errors.cryptoRequired"));
    if (!secret) throw new Error("Secret not loaded");

    const encKey = fromBase64(secret.encrypted_wallet_key);
    const key = await rsaOaepDecrypt(encKey, rsaPrivateKey);
    cacheWalletKey(walletId ?? "", key);
    return key;
  }

  async function handleShowValue() {
    if (!secret || isDecrypting) return;
    setIsDecrypting(true);
    setDecryptError(null);

    try {
      const walletKey = await getWalletKey();
      const encValue = fromBase64(secret.encrypted_value);
      const plainBytes = await aesGcmDecrypt(encValue, walletKey);
      const value = bytesToText(plainBytes);

      setShownValue(value);

      // Auto-hide countdown
      let remaining = SHOW_TIMEOUT_SECS;
      setShowCountdown(remaining);
      const interval = setInterval(() => {
        remaining -= 1;
        setShowCountdown(remaining);
        if (remaining <= 0) {
          clearInterval(interval);
          setShownValue(null);
          setShowCountdown(null);
        }
      }, 1000);
    } catch (err) {
      let msg = t("errors.decryptFailed");
      if (err instanceof Error) msg = err.message;
      setDecryptError(msg);
    } finally {
      setIsDecrypting(false);
    }
  }

  async function handleCopyValue() {
    if (!secret) return;
    setIsDecrypting(true);
    setDecryptError(null);

    try {
      const walletKey = await getWalletKey();
      const encValue = fromBase64(secret.encrypted_value);
      const plainBytes = await aesGcmDecrypt(encValue, walletKey);
      const value = bytesToText(plainBytes);

      await navigator.clipboard.writeText(value);
      notifications.show({
        color: "green",
        message: t("secrets.valueCopied"),
      });
    } catch (err) {
      let msg = t("errors.decryptFailed");
      if (err instanceof Error) msg = err.message;
      setDecryptError(msg);
    } finally {
      setIsDecrypting(false);
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

  if (!secret) return null;

  return (
    <Stack>
      {/* Breadcrumb : "Coffre" cliquable pour remonter au wallet, puis nom du
          secret en texte. Cohérent avec le breadcrumb intra-wallet pour que
          l'utilisateur sache toujours comment revenir. */}
      <Breadcrumbs>
        <Anchor
          onClick={() => navigate(`/wallets/${walletId ?? ""}`)}
          style={{ cursor: "pointer" }}
        >
          {t("secrets.paths.root")}
        </Anchor>
        <Text>{secret.name}</Text>
      </Breadcrumbs>

      <Group justify="space-between">
        <Stack gap={2}>
          <Group gap="sm">
            <Title order={2} ff="monospace">
              {secret.name}
            </Title>
            {secret.is_placeholder ? (
              <Badge color="orange">{t("secrets.isPlaceholder")}</Badge>
            ) : (
              <Badge color="green">
                {t("secrets.generationVersion", {
                  version: secret.generation_version,
                })}
              </Badge>
            )}
          </Group>
          {secret.description && <Text c="dimmed">{secret.description}</Text>}
        </Stack>
        <Button variant="subtle" onClick={() => navigate(-1)}>
          {t("common.back")}
        </Button>
      </Group>

      {secret.tags.length > 0 && (
        <Group gap="xs">
          {secret.tags.map((tag) => (
            <Badge key={tag} variant="light">
              {tag}
            </Badge>
          ))}
        </Group>
      )}

      {decryptError && (
        <Alert color="red" title={t("errors.decryptFailed")}>
          {decryptError}
        </Alert>
      )}

      {/* Value section */}
      <Paper withBorder p="md">
        {shownValue !== null ? (
          <Stack>
            <Group justify="space-between">
              <Text size="sm" c="dimmed">
                {t("secrets.valueTimeout", { seconds: showCountdown ?? 0 })}
              </Text>
              <Tooltip label={t("common.copy")}>
                <ActionIcon
                  variant="subtle"
                  onClick={() => void navigator.clipboard.writeText(shownValue)}
                >
                  📋
                </ActionIcon>
              </Tooltip>
            </Group>
            <Code block>{shownValue}</Code>
            <Button
              variant="outline"
              size="xs"
              onClick={() => {
                setShownValue(null);
                setShowCountdown(null);
              }}
            >
              {t("secrets.hideValue")}
            </Button>
          </Stack>
        ) : (
          <Group>
            <Button
              onClick={() => void handleShowValue()}
              loading={isDecrypting}
              // loading
              disabled={secret.is_placeholder}
            >
              {t("secrets.showValue")}
            </Button>
            <Button
              variant="outline"
              onClick={() => void handleCopyValue()}
              loading={isDecrypting}
              disabled={secret.is_placeholder}
            >
              {t("secrets.copyValue")}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setIsEditing(!isEditing);
                setEditValue("");
              }}
              disabled={secret.is_placeholder}
            >
              {isEditing ? t("common.cancel") : t("secrets.editValue")}
            </Button>
            <Button variant="outline" onClick={openMetaModal}>
              {t("secrets.editProperties")}
            </Button>
            <Button
              variant="outline"
              color="red"
              onClick={() => void handleDelete()}
              loading={isDeleting}
            >
              {t("secrets.delete")}
            </Button>
          </Group>
        )}
        {isEditing && !secret.is_placeholder && (
          <Stack gap="xs" mt="md">
            <PasswordInput
              label={t("secrets.newValue")}
              value={editValue}
              onChange={(e) => setEditValue(e.currentTarget.value)}
              autoFocus
            />
            <Group>
              <Button
                onClick={() => void handleSaveEdit()}
                loading={isSaving}
                disabled={!editValue}
              >
                {t("common.save")}
              </Button>
              <Button
                variant="subtle"
                onClick={() => {
                  setIsEditing(false);
                  setEditValue("");
                }}
              >
                {t("common.cancel")}
              </Button>
            </Group>
          </Stack>
        )}
      </Paper>

      <Modal
        opened={isEditingMeta}
        onClose={() => setIsEditingMeta(false)}
        title={t("secrets.editPropertiesTitle")}
        size="md"
      >
        <Stack>
          <Textarea
            label={t("secrets.descriptionLabel")}
            value={metaDescription}
            onChange={(e) => setMetaDescription(e.currentTarget.value)}
            rows={3}
            maxLength={1000}
          />
          <TagsInput
            label={t("secrets.tagsLabel")}
            description={t("secrets.tagsHint")}
            value={metaTags}
            onChange={setMetaTags}
            clearable
          />
          <Group justify="flex-end" mt="md">
            <Button variant="subtle" onClick={() => setIsEditingMeta(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={isSavingMeta}
              onClick={() => void handleSaveMeta()}
            >
              {t("common.save")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
