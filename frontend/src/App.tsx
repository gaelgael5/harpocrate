/**
 * App root — sets up OIDC, router, and inactivity timeout.
 */
import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Center, Loader } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { api } from "@/lib/api-client";
import { initOidc } from "@/lib/oidc";
import { KeycloakConfigSchema } from "@/schemas/auth";
import { useCryptoStore } from "@/stores/crypto";
import { useSessionStore } from "@/stores/session";

import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Layout } from "@/components/Layout";
import { InactivityGuard } from "@/components/InactivityGuard";
import { DevModeBanner } from "@/components/DevModeBanner";
import { InsecureContextGuard } from "@/components/InsecureContextGuard";
import { useDevMode, DEV_BANNER_HEIGHT } from "@/hooks/useDevMode";

import { LoginPage } from "@/pages/LoginPage";
import { OAuthCallbackPage } from "@/pages/OAuthCallbackPage";
import { FirstLoginPage } from "@/pages/FirstLoginPage";
import { UnlockPage } from "@/pages/UnlockPage";
import { RecoverStartPage } from "@/pages/RecoverStartPage";
import { RecoverPage } from "@/pages/RecoverPage";
import { WalletsPage } from "@/pages/WalletsPage";
import { WalletDetailPage } from "@/pages/WalletDetailPage";
import { WalletNewPage } from "@/pages/WalletNewPage";
import { SecretDetailPage } from "@/pages/SecretDetailPage";
import { SecretNewPage } from "@/pages/SecretNewPage";
import { GrantsPage } from "@/pages/GrantsPage";
import { ApiKeysPage } from "@/pages/ApiKeysPage";
import { WalletImportPage } from "@/pages/WalletImportPage";
import { AuditLogPage } from "@/pages/AuditLogPage";
import { AccountPage } from "@/pages/AccountPage";
import { IntegrationPage } from "@/pages/IntegrationPage";
import { AdminBackupsPage } from "@/pages/AdminBackupsPage";
import { AdminRemoteBackupsPage } from "@/pages/AdminRemoteBackupsPage";
import { AdminReplicationPage } from "@/pages/AdminReplicationPage";
import { AdminReplicationNodeDetailPage } from "@/pages/AdminReplicationNodeDetailPage";
import { AdminUsersPage } from "@/pages/AdminUsersPage";
import { AdminSystemPage } from "@/pages/AdminSystemPage";
import { AdminSnapshotsPage } from "@/pages/AdminSnapshotsPage";
import { AdminSecretTypesPage } from "@/pages/AdminSecretTypesPage";
import { AdminSecretTypeCreatePage } from "@/pages/AdminSecretTypeCreatePage";
import { AdminSecretTypeDetailPage } from "@/pages/AdminSecretTypeDetailPage";
import { ExportAllPage } from "@/pages/ExportAllPage";
import { AdminEnvPage } from "@/pages/AdminEnvPage";
import { AdminAnomaliesPage } from "@/pages/AdminAnomaliesPage";
import { BecomeStandbyPage } from "@/pages/BecomeStandbyPage";
import { PairingWizardPage } from "@/pages/PairingWizardPage";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { LandingPage } from "@/pages/LandingPage";
import { RgpdPage } from "@/pages/RgpdPage";
import { ApiDocsPage } from "@/pages/ApiDocsPage";
import { ApiDocsEmbeddedPage } from "@/pages/ApiDocsEmbeddedPage";

/** Wrapper qui pousse tout le contenu sous le bandeau dev (s'il est actif). */
function ContentWithBannerOffset({ children }: { children: ReactNode }) {
  const { enabled } = useDevMode();
  return (
    <div
      style={{
        paddingTop: enabled ? DEV_BANNER_HEIGHT : 0,
        minHeight: "100vh",
      }}
    >
      {children}
    </div>
  );
}

/**
 * Route /integration : accessible publiquement (pas d'auth requise) MAIS
 * rendue dans le Layout admin si l'utilisateur est connecté + déverrouillé,
 * pour ne pas faire disparaître la sidebar quand on navigue vers
 * Intégration depuis l'app authentifiée.
 */
function IntegrationRoute({ children }: { children: ReactNode }) {
  const user = useSessionStore((s) => s.user);
  const isUnlocked = useCryptoStore((s) => s.isUnlocked);
  if (user && isUnlocked) {
    return <Layout>{children}</Layout>;
  }
  return <>{children}</>;
}

export default function App() {
  const { t } = useTranslation();
  // null = config fetch en cours, true = prêt, false = échec ou Keycloak indispo
  const [oidcReady, setOidcReady] = useState<boolean | null>(null);
  const lock = useCryptoStore((s) => s.lock);
  const clearUser = useSessionStore((s) => s.clearUser);

  useEffect(() => {
    // Fetch Keycloak config and initialize OIDC
    api
      .get<unknown>("/config/keycloak")
      .then((data) => {
        const config = KeycloakConfigSchema.parse(data);
        initOidc(config);
        setOidcReady(true);
      })
      .catch((err: unknown) => {
        setOidcReady(false);
        notifications.show({
          color: "red",
          title: t("common.error"),
          message: String(err),
        });
      });
  }, [t]);

  // Pendant le fetch de /config/keycloak : loader sans catch-all pour ne pas
  // écraser l'URL /oauth-callback que Keycloak vient de nous envoyer.
  if (oidcReady === null) {
    return (
      <BrowserRouter>
        <DevModeBanner />
        <Center h="100vh">
          <Loader size="lg" />
        </Center>
      </BrowserRouter>
    );
  }

  // Keycloak indispo ou non configuré : landing + redirect catch-all.
  if (!oidcReady) {
    return (
      <BrowserRouter>
        <DevModeBanner />
        <ContentWithBannerOffset>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/rgpd" element={<RgpdPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ContentWithBannerOffset>
      </BrowserRouter>
    );
  }

  return (
    <BrowserRouter>
      <DevModeBanner />
      <MaintenanceBanner />
      <ContentWithBannerOffset>
        <InsecureContextGuard>
          <InactivityGuard
            timeoutMs={15 * 60 * 1000}
            onTimeout={() => {
              lock();
              clearUser();
            }}
          >
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<LandingPage />} />
              <Route path="/rgpd" element={<RgpdPage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/oauth-callback" element={<OAuthCallbackPage />} />
              <Route path="/first-login" element={<FirstLoginPage />} />
              <Route path="/unlock" element={<UnlockPage />} />
              <Route path="/recover/start" element={<RecoverStartPage />} />
              <Route path="/recover/:sessionId" element={<RecoverPage />} />
              <Route
                path="/integration"
                element={
                  <IntegrationRoute>
                    <IntegrationPage />
                  </IntegrationRoute>
                }
              />
              <Route
                path="/integration/api-docs"
                element={
                  <IntegrationRoute>
                    <ApiDocsPage />
                  </IntegrationRoute>
                }
              />

              {/* Protected routes — require OIDC + vault unlocked */}
              <Route
                element={
                  <ProtectedRoute>
                    <Layout />
                  </ProtectedRoute>
                }
              >
                <Route path="/wallets" element={<WalletsPage />} />
                <Route path="/wallets/new" element={<WalletNewPage />} />
                <Route path="/wallets/import" element={<WalletImportPage />} />
                <Route
                  path="/wallets/:walletId"
                  element={<WalletDetailPage />}
                />
                <Route
                  path="/wallets/:walletId/secrets/new"
                  element={<SecretNewPage />}
                />
                <Route
                  path="/wallets/:walletId/secrets/:secretId"
                  element={<SecretDetailPage />}
                />
                <Route
                  path="/wallets/:walletId/grants"
                  element={<GrantsPage />}
                />
                <Route
                  path="/wallets/:walletId/api-keys"
                  element={<ApiKeysPage />}
                />
                <Route path="/audit" element={<AuditLogPage />} />
                <Route path="/account" element={<AccountPage />} />
                <Route path="/admin/backups" element={<AdminBackupsPage />} />
                <Route
                  path="/admin/backup-remotes"
                  element={<AdminRemoteBackupsPage />}
                />
                <Route
                  path="/admin/replication"
                  element={<AdminReplicationPage />}
                />
                <Route
                  path="/admin/replication/streaming/nodes/:nodeId"
                  element={<AdminReplicationNodeDetailPage />}
                />
                <Route
                  path="/admin/become-standby"
                  element={<BecomeStandbyPage />}
                />
                <Route
                  path="/admin/pairing/:sessionId"
                  element={<PairingWizardPage />}
                />
                <Route
                  path="/admin/snapshots"
                  element={<AdminSnapshotsPage />}
                />
                <Route
                  path="/admin/secret-types"
                  element={<AdminSecretTypesPage />}
                />
                <Route
                  path="/admin/secret-types/new"
                  element={<AdminSecretTypeCreatePage />}
                />
                <Route
                  path="/admin/secret-types/:typeUuid"
                  element={<AdminSecretTypeDetailPage />}
                />
                <Route path="/admin/users" element={<AdminUsersPage />} />
                <Route path="/admin/system" element={<AdminSystemPage />} />
                <Route
                  path="/admin/anomalies"
                  element={<AdminAnomaliesPage />}
                />
                <Route path="/export-all" element={<ExportAllPage />} />
                <Route path="/admin/env" element={<AdminEnvPage />} />
                <Route path="/api-docs" element={<ApiDocsEmbeddedPage />} />
              </Route>

              {/* Fallback */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </InactivityGuard>
        </InsecureContextGuard>
      </ContentWithBannerOffset>
    </BrowserRouter>
  );
}
