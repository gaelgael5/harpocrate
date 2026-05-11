/**
 * BulkImportSecretsModal — import en masse de secrets dans un wallet.
 *
 * Workflow en 2 étapes :
 *   1. Paste : textarea + auto-détection du format (.env / JSON flat /
 *      Harpocrate). Preview du nombre de secrets détectés.
 *   2. Liste : tableau des secrets avec colonnes name (éditable), valeur
 *      (preview tronqué), badge type=raw, checkbox override (auto si conflit
 *      détecté), checkbox import (décochable pour skip individuel).
 *      Bouton "Importer N secrets" → chiffre chaque valeur avec wallet_key
 *      puis POST /v1/wallets/{id}/secrets/bulk-import.
 *
 * Crypto : zero-knowledge respecté — chaque valeur est chiffrée AES-GCM
 * avec la wallet_key DANS le navigateur avant envoi. Le backend ne voit
 * jamais les valeurs en clair.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { aesGcmEncrypt } from "@/crypto/aes-gcm";
import { textToBytes, toBase64, fromBase64 } from "@/crypto/helpers";
import { rsaOaepDecrypt } from "@/crypto/rsa-oaep";
import { api, ApiError } from "@/lib/api-client";
import {
  parseBulkImport,
  type ParsedSecret,
  type BulkImportFormat,
} from "@/lib/bulkImportParsers";
import { MyGrantResponseSchema } from "@/schemas/grants";
import { useCryptoStore } from "@/stores/crypto";

// ─── Types ───────────────────────────────────────────────────────────────────

interface SecretRowState {
  name: string;
  value: string;
  exists: boolean; // détecté en checkant la liste actuelle des secrets
  override: boolean; // coché par défaut si exists
  include: boolean; // décochable pour skip cet item
}

interface BulkImportItem {
  name: string;
  encrypted_value: string;
  override: boolean;
}

interface BulkImportResponse {
  summary: {
    created: number;
    updated: number;
    skipped: number;
    failed: number;
  };
  items: Array<{
    name: string;
    action: "created" | "updated" | "skipped" | "failed";
    secret_id?: string;
    reason?: string;
    error?: string;
  }>;
}

interface ExistingSecret {
  name: string;
}

// ─── Composant principal ─────────────────────────────────────────────────────

export function BulkImportSecretsModal({
  walletId,
  opened,
  onClose,
  onImported,
}: {
  walletId: string;
  opened: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState<"paste" | "review">("paste");
  const [pasted, setPasted] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [detectedFormat, setDetectedFormat] = useState<BulkImportFormat | null>(
    null,
  );
  const [rows, setRows] = useState<SecretRowState[]>([]);

  // Liste des secrets existants pour détection des conflits.
  const existingSecretsQuery = useQuery({
    queryKey: ["wallet-secrets-names", walletId],
    queryFn: async (): Promise<Set<string>> => {
      const r = await api.get<{ secrets: ExistingSecret[] }>(
        `/wallets/${walletId}/secrets`,
      );
      return new Set(r.secrets.map((s) => s.name));
    },
    enabled: opened,
  });

  // Reset state à la fermeture / ouverture.
  useEffect(() => {
    if (!opened) {
      setStep("paste");
      setPasted("");
      setParseError(null);
      setDetectedFormat(null);
      setRows([]);
    }
  }, [opened]);

  // Auto-parse à la saisie (debounced indirectement via état React).
  function handlePastedChange(v: string) {
    setPasted(v);
    if (!v.trim()) {
      setParseError(null);
      setDetectedFormat(null);
      return;
    }
    const r = parseBulkImport(v);
    if (r.ok) {
      setParseError(null);
      setDetectedFormat(r.format);
    } else {
      setParseError(r.error);
      setDetectedFormat(null);
    }
  }

  function goToReview() {
    const r = parseBulkImport(pasted);
    if (!r.ok) {
      setParseError(r.error);
      return;
    }
    const existing = existingSecretsQuery.data ?? new Set<string>();
    setRows(
      r.secrets.map((s: ParsedSecret) => {
        const exists = existing.has(s.name);
        return {
          name: s.name,
          value: s.value,
          exists,
          override: exists, // override auto-coché si conflit
          include: true,
        };
      }),
    );
    setStep("review");
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("wallets.bulkImport.title")}
      // Étape paste : largeur "xl" suffit pour la textarea.
      // Étape review : tableau à 5 colonnes (incl. textInput nom + valeur
      // tronquée) — on prend 95% du viewport pour confort de lecture.
      size={step === "review" ? "95%" : "xl"}
      closeOnClickOutside={step === "paste"}
    >
      {step === "paste" && (
        <PasteStep
          pasted={pasted}
          onChange={handlePastedChange}
          parseError={parseError}
          detectedFormat={detectedFormat}
          parsedCount={
            detectedFormat
              ? parseBulkImport(pasted).ok
                ? (parseBulkImport(pasted) as { secrets: ParsedSecret[] })
                    .secrets.length
                : 0
              : 0
          }
          onCancel={onClose}
          onNext={goToReview}
          existingLoaded={existingSecretsQuery.isSuccess}
        />
      )}
      {step === "review" && (
        <ReviewStep
          walletId={walletId}
          rows={rows}
          onRowsChange={setRows}
          onBack={() => setStep("paste")}
          onCancel={onClose}
          onImported={onImported}
        />
      )}
    </Modal>
  );
}

// ─── Étape 1 : Paste ─────────────────────────────────────────────────────────

function PasteStep({
  pasted,
  onChange,
  parseError,
  detectedFormat,
  parsedCount,
  onCancel,
  onNext,
  existingLoaded,
}: {
  pasted: string;
  onChange: (v: string) => void;
  parseError: string | null;
  detectedFormat: BulkImportFormat | null;
  parsedCount: number;
  onCancel: () => void;
  onNext: () => void;
  existingLoaded: boolean;
}) {
  const { t } = useTranslation();
  const canProceed =
    detectedFormat !== null && parsedCount > 0 && existingLoaded;

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {t("wallets.bulkImport.pasteHint")}
      </Text>
      <Textarea
        minRows={12}
        autosize
        placeholder={t("wallets.bulkImport.pastePlaceholder")}
        value={pasted}
        onChange={(e) => onChange(e.currentTarget.value)}
        styles={{ input: { fontFamily: "monospace", fontSize: "0.85rem" } }}
      />
      {parseError && (
        <Alert color="orange" variant="light">
          {parseError}
        </Alert>
      )}
      {detectedFormat && parsedCount > 0 && (
        <Alert color="blue" variant="light">
          {t("wallets.bulkImport.detected", {
            count: parsedCount,
            format: detectedFormat,
          })}
        </Alert>
      )}
      <Group justify="flex-end">
        <Button variant="subtle" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button disabled={!canProceed} onClick={onNext}>
          {t("wallets.bulkImport.next")}
        </Button>
      </Group>
    </Stack>
  );
}

// ─── Étape 2 : Review + Import ───────────────────────────────────────────────

function ReviewStep({
  walletId,
  rows,
  onRowsChange,
  onBack,
  onCancel,
  onImported,
}: {
  walletId: string;
  rows: SecretRowState[];
  onRowsChange: (rows: SecretRowState[]) => void;
  onBack: () => void;
  onCancel: () => void;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const rsaPrivateKey = useCryptoStore((s) => s.rsaPrivateKey);
  const cacheWalletKey = useCryptoStore((s) => s.cacheWalletKey);
  const getCachedWalletKey = useCryptoStore((s) => s.getWalletKey);
  const [report, setReport] = useState<BulkImportResponse | null>(null);

  const includedCount = useMemo(
    () => rows.filter((r) => r.include).length,
    [rows],
  );

  function updateRow(idx: number, patch: Partial<SecretRowState>) {
    const next = [...rows];
    next[idx] = { ...next[idx]!, ...patch };
    onRowsChange(next);
  }

  async function getWalletKey(): Promise<Uint8Array> {
    const cached = getCachedWalletKey(walletId);
    if (cached) return cached;
    if (!rsaPrivateKey)
      throw new Error("RSA private key not available — unlock first");
    const raw = await api.get<unknown>(`/wallets/${walletId}/my-grant`);
    const grant = MyGrantResponseSchema.parse(raw);
    const encKey = fromBase64(grant.encrypted_wallet_key);
    const key = await rsaOaepDecrypt(encKey, rsaPrivateKey);
    cacheWalletKey(walletId, key);
    return key;
  }

  const importMut = useMutation({
    mutationFn: async (): Promise<BulkImportResponse> => {
      const walletKey = await getWalletKey();
      const items: BulkImportItem[] = [];
      for (const r of rows) {
        if (!r.include) continue;
        const enc = await aesGcmEncrypt(textToBytes(r.value), walletKey);
        items.push({
          name: r.name.trim(),
          encrypted_value: toBase64(enc),
          override: r.override,
        });
      }
      return await api.post<BulkImportResponse>(
        `/wallets/${walletId}/secrets/bulk-import`,
        { secrets: items },
      );
    },
    onSuccess: (resp) => {
      setReport(resp);
      const { created, updated, skipped, failed } = resp.summary;
      const color = failed > 0 ? "orange" : "green";
      notifications.show({
        color,
        title: t("wallets.bulkImport.doneTitle"),
        message: t("wallets.bulkImport.doneMessage", {
          created,
          updated,
          skipped,
          failed,
        }),
        autoClose: 6000,
      });
      onImported();
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

  // Si on a un rapport, on l'affiche. Sinon, on affiche la table éditable.
  if (report) {
    return (
      <Stack>
        <Alert color="green" variant="light">
          {t("wallets.bulkImport.reportSummary", report.summary)}
        </Alert>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("wallets.bulkImport.colName")}</Table.Th>
              <Table.Th>{t("wallets.bulkImport.colAction")}</Table.Th>
              <Table.Th>{t("wallets.bulkImport.colDetail")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {report.items.map((item, i) => (
              <Table.Tr key={i}>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {item.name}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge color={actionColor(item.action)} variant="light">
                    {item.action}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {item.error ?? item.reason ?? ""}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Group justify="flex-end">
          <Button onClick={onCancel}>{t("common.close")}</Button>
        </Group>
      </Stack>
    );
  }

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {t("wallets.bulkImport.reviewHint")}
      </Text>
      <Box style={{ maxHeight: "50vh", overflow: "auto" }}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: 40 }}>
                <Checkbox
                  checked={rows.every((r) => r.include)}
                  indeterminate={
                    rows.some((r) => r.include) && !rows.every((r) => r.include)
                  }
                  onChange={(e) => {
                    const checked = e.currentTarget.checked;
                    onRowsChange(rows.map((r) => ({ ...r, include: checked })));
                  }}
                  aria-label={t("wallets.bulkImport.colInclude")}
                />
              </Table.Th>
              <Table.Th>{t("wallets.bulkImport.colName")}</Table.Th>
              <Table.Th>{t("wallets.bulkImport.colValue")}</Table.Th>
              <Table.Th>{t("wallets.bulkImport.colType")}</Table.Th>
              <Table.Th>{t("wallets.bulkImport.colOverride")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row, i) => (
              <Table.Tr
                key={i}
                style={
                  row.exists
                    ? { background: "rgba(255,165,0,0.08)" }
                    : undefined
                }
              >
                <Table.Td>
                  <Checkbox
                    checked={row.include}
                    onChange={(e) =>
                      updateRow(i, { include: e.currentTarget.checked })
                    }
                  />
                </Table.Td>
                <Table.Td>
                  <TextInput
                    size="xs"
                    value={row.name}
                    onChange={(e) =>
                      updateRow(i, { name: e.currentTarget.value })
                    }
                    styles={{ input: { fontFamily: "monospace" } }}
                  />
                </Table.Td>
                <Table.Td>
                  <Text
                    size="xs"
                    ff="monospace"
                    c="dimmed"
                    lineClamp={1}
                    title={row.value}
                  >
                    {row.value.length > 60
                      ? row.value.slice(0, 60) + "…"
                      : row.value}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light">raw</Badge>
                </Table.Td>
                <Table.Td>
                  {row.exists ? (
                    <Checkbox
                      label={t("wallets.bulkImport.overrideLabel")}
                      checked={row.override}
                      onChange={(e) =>
                        updateRow(i, { override: e.currentTarget.checked })
                      }
                    />
                  ) : (
                    <Text size="xs" c="dimmed">
                      {t("wallets.bulkImport.newSecret")}
                    </Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Box>

      <Group justify="space-between">
        <Button variant="subtle" onClick={onBack}>
          ← {t("common.back")}
        </Button>
        <Group gap="xs">
          <Button variant="subtle" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={includedCount === 0}
            loading={importMut.isPending}
            onClick={() => importMut.mutate()}
          >
            {t("wallets.bulkImport.importBtn", { count: includedCount })}
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

function actionColor(action: string): string {
  switch (action) {
    case "created":
      return "green";
    case "updated":
      return "blue";
    case "skipped":
      return "gray";
    default:
      return "red";
  }
}
