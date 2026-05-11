/**
 * Page d'export global "parachute Dashlane" — LOT_12D.
 *
 * Exporte tous les secrets accessibles (owned + grants read) en CSV compatible Dashlane.
 * Tout le chiffrement est géré côté client uniquement.
 *
 * Colonnes CSV : title, username, password, url, note, category
 */
import { useState } from "react";
import {
  Stack,
  Title,
  Text,
  Button,
  Alert,
  Progress,
  List,
  Card,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api-client";
import { rsaOaepDecrypt } from "@/crypto/rsa-oaep";
import { aesGcmDecrypt } from "@/crypto/aes-gcm";
import { fromBase64, bytesToText } from "@/crypto/helpers";
import { useCryptoStore } from "@/stores/crypto";
import { WalletListResponseSchema } from "@/schemas/wallets";
import {
  SecretListResponseSchema,
  SecretDetailResponseSchema,
} from "@/schemas/secrets";

type ExportState = "idle" | "running" | "done" | "error";

interface Row {
  title: string;
  username: string;
  password: string;
  url: string;
  note: string;
  category: string;
}

function toCsv(rows: Row[]): string {
  const header = "title,username,password,url,note,category";
  const escape = (v: string) => `"${v.replace(/"/g, '""')}"`;
  const lines = rows.map((r) =>
    [r.title, r.username, r.password, r.url, r.note, r.category]
      .map(escape)
      .join(","),
  );
  return [header, ...lines].join("\r\n");
}

function downloadCsv(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function ExportAllPage() {
  const { t } = useTranslation();
  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey);
  const getCachedKey = useCryptoStore((s) => s.getWalletKey);
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey);

  const [state, setState] = useState<ExportState>("idle");
  const [progress, setProgress] = useState({ current: 0, total: 0, step: "" });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [rowCount, setRowCount] = useState(0);

  async function handleExport() {
    if (!rsaPrivateKey) {
      setErrorMsg(t("errors.cryptoRequired"));
      return;
    }

    setState("running");
    setErrorMsg(null);
    const rows: Row[] = [];

    try {
      // 1. Fetch all wallets
      setProgress({ current: 0, total: 0, step: t("export.stepFetchWallets") });
      const walletsRaw = await api.get<unknown>("/wallets?limit=200");
      const wallets = WalletListResponseSchema.parse(walletsRaw).wallets;

      let secretsTotal = wallets.reduce(
        (a, w) => a + w.valued_secrets_count,
        0,
      );
      let done = 0;
      setProgress({
        current: 0,
        total: secretsTotal,
        step: t("export.stepDecrypting"),
      });

      // 2. For each wallet, fetch + decrypt secrets
      for (const wallet of wallets) {
        if (wallet.valued_secrets_count === 0) continue;

        // Get the wallet key (from cache or by decrypting first secret)
        let walletKey: Uint8Array | null = getCachedKey(wallet.id);

        // Fetch secret list (non-placeholders only)
        const listRaw = await api.get<unknown>(
          `/wallets/${wallet.id}/secrets?limit=200`,
        );
        const secrets = SecretListResponseSchema.parse(listRaw).secrets.filter(
          (s) => !s.is_placeholder,
        );

        for (const s of secrets) {
          // Fetch secret detail (includes encrypted_value + encrypted_wallet_key)
          const detailRaw = await api.get<unknown>(
            `/wallets/${wallet.id}/secrets/by-id/${s.id}`,
          );
          const detail = SecretDetailResponseSchema.parse(detailRaw);

          if (!walletKey) {
            const encKey = fromBase64(detail.encrypted_wallet_key);
            walletKey = await rsaOaepDecrypt(encKey, rsaPrivateKey);
            cacheWalletKey(wallet.id, walletKey);
          }

          let value = "";
          try {
            const encValue = fromBase64(detail.encrypted_value);
            const plainBytes = await aesGcmDecrypt(encValue, walletKey);
            value = bytesToText(plainBytes);
          } catch {
            value = "[DECRYPT_ERROR]";
          }

          rows.push({
            title: `${wallet.name}/${s.name}`,
            username: "",
            password: value,
            url: "",
            note: detail.description ?? "",
            category: wallet.name,
          });

          done++;
          setProgress({
            current: done,
            total: secretsTotal,
            step: t("export.stepDecrypting"),
          });
        }
      }

      // 3. Generate + download CSV
      const csv = toCsv(rows);
      const now = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadCsv(csv, `harpocrate-export-${now}.csv`);
      setRowCount(rows.length);
      setState("done");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("common.error"));
      setState("error");
    }
  }

  return (
    <Stack>
      <Title order={2}>{t("export.title")}</Title>

      <Alert color="orange" title={t("export.warningTitle")}>
        {t("export.warningBody")}
      </Alert>

      <Card withBorder>
        <Stack>
          <Text fw={600}>{t("export.whatIsExported")}</Text>
          <List size="sm">
            <List.Item>{t("export.item1")}</List.Item>
            <List.Item>{t("export.item2")}</List.Item>
            <List.Item>{t("export.item3")}</List.Item>
          </List>
        </Stack>
      </Card>

      {state === "running" && (
        <Stack>
          <Text size="sm" c="dimmed">
            {progress.step} ({progress.current}/{progress.total})
          </Text>
          <Progress
            value={
              progress.total > 0 ? (progress.current / progress.total) * 100 : 0
            }
            animated
          />
        </Stack>
      )}

      {state === "done" && (
        <Alert color="green">{t("export.success", { count: rowCount })}</Alert>
      )}

      {(state === "error" || errorMsg) && (
        <Alert color="red">{errorMsg ?? t("common.error")}</Alert>
      )}

      <Button
        color="orange"
        loading={state === "running"}
        disabled={state === "running"}
        onClick={() => void handleExport()}
        w="fit-content"
      >
        {state === "running" ? t("export.exporting") : t("export.button")}
      </Button>
    </Stack>
  );
}
