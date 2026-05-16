/**
 * GDriveFields — wizard 3 phases pour configurer une connexion Google Drive.
 *
 * Phases :
 *   idle      → formulaire (Client ID, Client Secret, Redirect URI, Folder Name)
 *   waiting   → spinner pendant que la popup OAuth Google est ouverte
 *   authorized → alerte verte + résumé, bouton "Recommencer"
 *   error     → alerte rouge avec message traduit, retour aux champs
 *
 * Ce composant ne fait PAS le save final. Le parent (modal) assemble le
 * payload avec l'`oauth_state` remonté via `onAuthorized` et fait le POST.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ActionIcon,
  Alert,
  Button,
  CopyButton,
  Group,
  Loader,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";

import { fetchGDriveRedirectUri } from "@/lib/adminApi";
import {
  OAuthAbortedError,
  OAuthError,
  PopupBlockedError,
  runGDriveOAuthFlow,
} from "@/lib/gdriveOAuth";

// ── Types publics ─────────────────────────────────────────────────────────────

export type GDriveWizardState =
  | { phase: "idle" }
  | { phase: "waiting" }
  | { phase: "authorized"; state: string; user_email: string }
  | { phase: "error"; message: string };

export interface GDriveFieldsProps {
  /** Nom de la connexion (déjà saisi dans le modal parent — nécessaire pour startGDriveOAuth). */
  name: string;
  wizard: GDriveWizardState;
  onWizardChange: (s: GDriveWizardState) => void;
  /** Appelé quand l'autorisation Google réussit — remonte l'oauth_state + email + folder au parent. */
  onAuthorized: (
    oauth_state: string,
    user_email: string,
    folder_name: string,
  ) => void;
}

// ── Composant ─────────────────────────────────────────────────────────────────

export function GDriveFields({
  name,
  wizard,
  onWizardChange,
  onAuthorized,
}: GDriveFieldsProps): JSX.Element {
  const { t } = useTranslation();

  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [folderName, setFolderName] = useState("Harpocrate Backups");
  const [redirectUri, setRedirectUri] = useState("");

  // Charge le redirect URI en lecture seule depuis le backend.
  useEffect(() => {
    let cancelled = false;
    fetchGDriveRedirectUri()
      .then((r) => {
        if (!cancelled) setRedirectUri(r.redirect_uri);
      })
      .catch(() => {
        // Champ read-only — échec silencieux, l'admin peut saisir manuellement.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const canAuthorize = useMemo(
    () =>
      Boolean(
        name.trim() && clientId.trim() && clientSecret && folderName.trim(),
      ),
    [name, clientId, clientSecret, folderName],
  );

  async function handleAuthorize(): Promise<void> {
    onWizardChange({ phase: "waiting" });
    try {
      const result = await runGDriveOAuthFlow({
        name: name.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret,
        folder_name: folderName.trim(),
      });
      onWizardChange({
        phase: "authorized",
        state: result.state,
        user_email: result.user_email,
      });
      onAuthorized(result.state, result.user_email, folderName.trim());
    } catch (err) {
      let message: string;
      if (err instanceof PopupBlockedError) {
        message = t("admin.remoteBackups.gdrive.popupBlocked");
      } else if (err instanceof OAuthAbortedError) {
        message = t("admin.remoteBackups.gdrive.aborted");
      } else if (err instanceof OAuthError) {
        message = err.reason;
      } else {
        message = err instanceof Error ? err.message : String(err);
      }
      onWizardChange({ phase: "error", message });
    }
  }

  // ── Phase authorized ──────────────────────────────────────────────────────

  if (wizard.phase === "authorized") {
    return (
      <Stack gap="sm">
        <Alert color="green" variant="light">
          {t("admin.remoteBackups.gdrive.authorizedAs", {
            email: wizard.user_email,
          })}
        </Alert>
        <Text size="sm" c="dimmed">
          {t("admin.remoteBackups.gdrive.fieldFolderName")} :{" "}
          <Text component="code" inherit>
            {folderName}
          </Text>
        </Text>
        <Group justify="flex-start">
          <Button
            variant="subtle"
            onClick={() => onWizardChange({ phase: "idle" })}
          >
            {t("admin.remoteBackups.gdrive.btnRestart")}
          </Button>
        </Group>
      </Stack>
    );
  }

  // ── Phase waiting ─────────────────────────────────────────────────────────

  if (wizard.phase === "waiting") {
    return (
      <Stack gap="sm">
        <Alert color="blue" variant="light">
          <Group gap="sm" wrap="nowrap">
            <Loader size="sm" />
            <Text size="sm">
              {t("admin.remoteBackups.gdrive.waitingAuth")}
            </Text>
          </Group>
        </Alert>
      </Stack>
    );
  }

  // ── Phase idle ou error : afficher les champs ─────────────────────────────

  return (
    <Stack gap="sm">
      <Text size="sm">{t("admin.remoteBackups.gdrive.step1Desc")}</Text>

      <TextInput
        label={t("admin.remoteBackups.gdrive.fieldClientId")}
        required
        value={clientId}
        onChange={(e) => setClientId(e.currentTarget.value)}
      />

      <PasswordInput
        label={t("admin.remoteBackups.gdrive.fieldClientSecret")}
        required
        value={clientSecret}
        onChange={(e) => setClientSecret(e.currentTarget.value)}
      />

      <Group align="end" gap="xs" wrap="nowrap">
        <TextInput
          label={t("admin.remoteBackups.gdrive.fieldRedirectUri")}
          description={t("admin.remoteBackups.gdrive.fieldRedirectUriHint")}
          value={redirectUri}
          readOnly
          style={{ flex: 1 }}
        />
        <CopyButton value={redirectUri}>
          {({ copied, copy }) => (
            <Tooltip
              label={
                copied
                  ? t("admin.remoteBackups.gdrive.copied")
                  : t("admin.remoteBackups.gdrive.copyHint")
              }
            >
              <ActionIcon
                variant="light"
                size="lg"
                onClick={copy}
                aria-label={t("admin.remoteBackups.gdrive.copyHint")}
              >
                {copied ? "✓" : "📋"}
              </ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
      </Group>

      <TextInput
        label={t("admin.remoteBackups.gdrive.fieldFolderName")}
        placeholder={t("admin.remoteBackups.gdrive.fieldFolderNamePlaceholder")}
        required
        value={folderName}
        onChange={(e) => setFolderName(e.currentTarget.value)}
      />

      {wizard.phase === "error" && (
        <Alert color="red" variant="light">
          {wizard.message}
        </Alert>
      )}

      <Group justify="flex-end">
        <Button
          onClick={() => void handleAuthorize()}
          disabled={!canAuthorize}
        >
          {t("admin.remoteBackups.gdrive.btnAuthorize")} →
        </Button>
      </Group>
    </Stack>
  );
}
