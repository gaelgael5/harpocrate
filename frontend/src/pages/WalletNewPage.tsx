/**
 * Create new wallet page.
 *
 * Generates a random wallet_key, encrypts it with user's RSA public key,
 * then POSTs to /v1/wallets.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Stack,
  Title,
  TextInput,
  Textarea,
  Button,
  Alert,
  Group,
  Select,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api-client";
import { rsaOaepEncrypt } from "@/crypto/rsa-oaep";
import { randomBytes, toBase64 } from "@/crypto/helpers";
import { useCryptoStore } from "@/stores/crypto";
import { WalletCreateResponseSchema } from "@/schemas/wallets";
import {
  fetchWalletEnvironments,
  createWalletEnvironment,
} from "@/lib/walletEnvironmentsApi";

interface FormValues {
  name: string;
  description: string;
  tags: string;
  /** "" = "None" virtuel ; sinon UUID d'un wallet_environment */
  environment_id: string;
}

const _NEW_ENV_SENTINEL = "__NEW_ENV__";

export function WalletNewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const rsaPublicKey = useCryptoStore((s) => s.rsaPublicKey);
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [creatingEnv, setCreatingEnv] = useState(false);
  const [newEnvName, setNewEnvName] = useState("");

  const envQuery = useQuery({
    queryKey: ["wallet-environments"],
    queryFn: fetchWalletEnvironments,
  });

  const createEnvMut = useMutation({
    mutationFn: createWalletEnvironment,
    onSuccess: (newEnv) => {
      void queryClient.invalidateQueries({ queryKey: ["wallet-environments"] });
      // Sélectionne automatiquement le nouvel env créé
      form.setFieldValue("environment_id", newEnv.id);
      setCreatingEnv(false);
      setNewEnvName("");
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

  const form = useForm<FormValues>({
    initialValues: {
      name: "",
      description: "",
      tags: "",
      environment_id: "",
    },
    validate: {
      name: (v) =>
        v.trim().length === 0
          ? t("common.required")
          : v.trim().length > 255
            ? "Max 255 characters"
            : null,
    },
  });

  async function handleSubmit(values: FormValues) {
    if (!rsaPublicKey) {
      setSubmitError(t("errors.cryptoRequired"));
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      // Generate wallet_key (32 bytes random)
      const walletKey = randomBytes(32);

      // Encrypt wallet_key with owner's RSA public key
      const encWalletKey = await rsaOaepEncrypt(walletKey, rsaPublicKey);

      const tags = values.tags
        .split(",")
        .map((t) => t.trim().toLowerCase())
        .filter((t) => t.length > 0);

      const body = {
        name: values.name.trim(),
        description: values.description.trim() || null,
        tags,
        encrypted_wallet_key_for_owner: toBase64(encWalletKey),
        environment_id: values.environment_id || null,
      };

      const resp = await api.post<unknown>("/wallets", body);
      const { wallet_id: walletId } = WalletCreateResponseSchema.parse(resp);

      // Cache wallet_key in RAM
      cacheWalletKey(walletId, walletKey);

      await queryClient.invalidateQueries({ queryKey: ["wallets"] });

      notifications.show({
        color: "green",
        message: t("wallets.created"),
      });

      navigate(`/wallets/${walletId}`, { replace: true });
    } catch (err) {
      let msg = t("errors.serverError");
      if (err instanceof ApiError) msg = err.message;
      setSubmitError(msg);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Stack maw={600}>
      <Title order={2}>{t("wallets.createTitle")}</Title>

      {submitError && (
        <Alert color="red" title={t("common.error")}>
          {submitError}
        </Alert>
      )}

      <form onSubmit={form.onSubmit((v) => void handleSubmit(v))}>
        <Stack>
          <TextInput
            label={t("wallets.name")}
            placeholder={t("wallets.namePlaceholder")}
            required
            {...form.getInputProps("name")}
          />
          <Textarea
            label={t("wallets.description")}
            placeholder={t("wallets.descriptionPlaceholder")}
            {...form.getInputProps("description")}
          />
          <TextInput
            label={t("wallets.tags")}
            placeholder={t("wallets.tagsPlaceholder")}
            description="Comma-separated"
            {...form.getInputProps("tags")}
          />

          {/* Select environnement avec option "+ Nouveau" inline */}
          {creatingEnv ? (
            <Stack gap="xs">
              <TextInput
                label={t("wallets.environments.nameLabel")}
                placeholder={t("wallets.environments.namePlaceholder")}
                value={newEnvName}
                onChange={(e) => setNewEnvName(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (newEnvName.trim())
                      createEnvMut.mutate(newEnvName.trim());
                  }
                }}
                autoFocus
              />
              <Group gap="xs" justify="flex-end">
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => {
                    setCreatingEnv(false);
                    setNewEnvName("");
                  }}
                >
                  {t("common.cancel")}
                </Button>
                <Button
                  size="xs"
                  color="brand"
                  loading={createEnvMut.isPending}
                  disabled={!newEnvName.trim()}
                  onClick={() => createEnvMut.mutate(newEnvName.trim())}
                >
                  {t("wallets.environments.create")}
                </Button>
              </Group>
            </Stack>
          ) : (
            <Select
              label={t("wallets.environment")}
              placeholder={t("wallets.environments.none")}
              data={[
                { value: "", label: t("wallets.environments.none") },
                ...(envQuery.data ?? []).map((env) => ({
                  value: env.id,
                  label: env.name,
                })),
                {
                  value: _NEW_ENV_SENTINEL,
                  label: `+ ${t("wallets.environments.create")}`,
                },
              ]}
              value={form.values.environment_id}
              onChange={(v) => {
                if (v === _NEW_ENV_SENTINEL) {
                  setCreatingEnv(true);
                } else {
                  form.setFieldValue("environment_id", v ?? "");
                }
              }}
              clearable={false}
              allowDeselect={false}
            />
          )}

          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => navigate(-1)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={isSubmitting}>
              {t("common.create")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Stack>
  );
}
