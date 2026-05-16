/**
 * Grants management page — list grants, share with another user.
 */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Stack,
  Title,
  Button,
  Card,
  Text,
  Group,
  Badge,
  Modal,
  TextInput,
  Alert,
  Loader,
  Center,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api-client";
import {
  GrantListResponseSchema,
  type GrantItem,
  PERM_ALL,
} from "@/schemas/grants";
import { UserLookupResponseSchema } from "@/schemas/wallets";
import { PermissionsCheckboxes } from "@/components/PermissionsCheckboxes";
import { rsaOaepDecrypt, rsaOaepEncrypt } from "@/crypto/rsa-oaep";
import { fromBase64, toBase64 } from "@/crypto/helpers";
import { useCryptoStore } from "@/stores/crypto";
import { MyGrantResponseSchema } from "@/schemas/grants";

function GrantRow({ grant }: { grant: GrantItem }) {
  const { t } = useTranslation();

  return (
    <Card withBorder padding="sm">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text fw={500}>
            {grant.grantee_display_name ?? grant.grantee_email}
          </Text>
          <Text size="xs" c="dimmed">
            {grant.grantee_email}
          </Text>
        </Stack>
        <Group>
          {grant.is_owner && <Badge color="gold">{t("grants.isOwner")}</Badge>}
          <Badge variant="outline">{grant.permissions}</Badge>
        </Group>
      </Group>
    </Card>
  );
}

export function GrantsPage() {
  const { t } = useTranslation();
  const { walletId } = useParams<{ walletId: string }>();
  const queryClient = useQueryClient();
  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey);
  const getCachedKey = useCryptoStore((s) => s.getWalletKey);
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey);

  const [opened, { open, close }] = useDisclosure();
  const [shareEmail, setShareEmail] = useState("");
  const [sharePerms, setSharePerms] = useState(PERM_ALL);
  const [isSharing, setIsSharing] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["grants", walletId],
    queryFn: async () => {
      const raw = await api.get<unknown>(`/wallets/${walletId ?? ""}/grants`);
      return GrantListResponseSchema.parse(raw);
    },
    enabled: !!walletId,
  });

  async function getWalletKey(): Promise<Uint8Array> {
    const cached = getCachedKey(walletId ?? "");
    if (cached) return cached;
    if (!rsaPrivateKey) throw new Error(t("errors.cryptoRequired"));

    const raw = await api.get<unknown>(`/wallets/${walletId ?? ""}/my-grant`);
    const grant = MyGrantResponseSchema.parse(raw);
    const encKey = fromBase64(grant.encrypted_wallet_key);
    const key = await rsaOaepDecrypt(encKey, rsaPrivateKey);
    cacheWalletKey(walletId ?? "", key);
    return key;
  }

  async function handleShare() {
    if (!shareEmail.trim()) return;
    setIsSharing(true);
    setShareError(null);

    try {
      // 1. Look up grantee
      const userRaw = await api.get<unknown>(
        `/users/lookup?email=${encodeURIComponent(shareEmail)}`,
      );
      const grantee = UserLookupResponseSchema.parse(userRaw);

      // 2. Get wallet key and re-encrypt for grantee
      const walletKey = await getWalletKey();
      const granteePub = fromBase64(grantee.rsa_public_key);
      const encKeyForGrantee = await rsaOaepEncrypt(walletKey, granteePub);

      // 3. POST grant
      await api.post(`/wallets/${walletId ?? ""}/grants`, {
        grantee_user_id: grantee.user_id,
        encrypted_wallet_key_for_grantee: toBase64(encKeyForGrantee),
        permissions: sharePerms,
      });

      await queryClient.invalidateQueries({ queryKey: ["grants", walletId] });
      notifications.show({ color: "green", message: "Shared!" });
      close();
      setShareEmail("");
    } catch (err) {
      let msg = t("errors.serverError");
      if (err instanceof ApiError) msg = err.message;
      else if (err instanceof Error) msg = err.message;
      setShareError(msg);
    } finally {
      setIsSharing(false);
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

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t("grants.title")}</Title>
        <Button onClick={open}>{t("grants.share")}</Button>
      </Group>

      {data?.grants.length === 0 ? (
        <Text c="dimmed">{t("grants.noGrants")}</Text>
      ) : (
        data?.grants.map((g) => <GrantRow key={g.id} grant={g} />)
      )}

      <Modal opened={opened} onClose={close} title={t("grants.share")}>
        <Stack>
          {shareError && <Alert color="red">{shareError}</Alert>}
          <TextInput
            label={t("grants.email")}
            value={shareEmail}
            onChange={(e) => setShareEmail(e.currentTarget.value)}
            placeholder="user@example.com"
          />
          <Text size="sm" fw={500}>
            {t("grants.selectPermissions")}
          </Text>
          <PermissionsCheckboxes value={sharePerms} onChange={setSharePerms} />
          <Button onClick={() => void handleShare()} loading={isSharing}>
            {t("grants.share")}
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
