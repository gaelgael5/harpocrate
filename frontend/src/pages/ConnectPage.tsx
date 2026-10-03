/**
 * Point d'entrée navigateur du flux « Se connecter avec Harpocrate » (feature 2).
 *
 * `/connect?client_id&request_uri` ne porte qu'une référence opaque (PAR, D6). Dans
 * l'ordre : paramètres valides → Keycloak disponible (sinon parcours indisponible, D15)
 * → session Keycloak (sinon redirection DIRECTE vers Keycloak, sans page de login, D15 ;
 * l'admin local est exclu, D10) → coffre déverrouillé → lecture de la demande.
 * La demande est mémorisée pour que le retour de Keycloak et le déverrouillage y ramènent.
 */
import { useEffect, useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Center, Loader } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { ConnectStatusCard } from "@/components/ConnectStatusCard";
import { ConnectRequestPanel } from "@/components/ConnectRequestPanel";
import { useConnectRequest } from "@/hooks/useConnectFlow";
import { useLocalLoginAvailable } from "@/hooks/useLocalLoginAvailable";
import { ApiError } from "@/lib/api-client";
import {
  clearConnectResume,
  parseConnectParams,
  saveConnectResume,
} from "@/lib/connectResume";
import { getUserManager, startLogin } from "@/lib/oidc";
import { ConnectUnavailablePage } from "@/pages/ConnectUnavailablePage";
import { useCryptoStore } from "@/stores/crypto";

type AuthState = "checking" | "redirecting" | "authenticated";

/** Erreurs définitives de la demande : la reprise est abandonnée. */
const TERMINAL_ERRORS = new Set([
  "request_not_found",
  "request_expired",
  "request_not_pending",
  "local_admin_not_allowed",
]);

function useKeycloakSession(enabled: boolean): AuthState {
  const [state, setState] = useState<AuthState>("checking");
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void getUserManager()
      .getUser()
      .then((user) => {
        if (cancelled) return;
        // Seule une session Keycloak compte : un jeton d'admin local ne suffit pas (D10).
        if (user && !user.expired) {
          setState("authenticated");
        } else {
          setState("redirecting");
          void startLogin();
        }
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return state;
}

function Waiting() {
  return (
    <Center h="100vh">
      <Loader size="lg" />
    </Center>
  );
}

export function ConnectPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const params = useMemo(
    () => parseConnectParams(searchParams),
    [searchParams],
  );
  const { oidcAvailable } = useLocalLoginAvailable();
  const isUnlocked = useCryptoStore((s) => s.isUnlocked);
  const auth = useKeycloakSession(params !== null && oidcAvailable === true);
  const request = useConnectRequest(
    params,
    auth === "authenticated" && isUnlocked,
  );

  useEffect(() => {
    if (params) saveConnectResume(params);
  }, [params]);

  const errorCode =
    request.error instanceof ApiError ? request.error.code : null;
  const sessionLost =
    request.error instanceof ApiError && request.error.isUnauthorized;
  useEffect(() => {
    if (errorCode && TERMINAL_ERRORS.has(errorCode)) clearConnectResume();
  }, [errorCode]);
  useEffect(() => {
    // Session Keycloak expirée entre-temps : on repasse par Keycloak, la demande est gardée.
    if (sessionLost) void startLogin();
  }, [sessionLost]);

  if (!params) {
    return (
      <ConnectStatusCard
        title={t("connect.invalidTitle")}
        message={t("connect.invalidMessage")}
        color="red"
      />
    );
  }
  if (oidcAvailable === false) return <ConnectUnavailablePage />;
  if (auth !== "authenticated") return <Waiting />;
  if (!isUnlocked) return <Navigate to="/unlock" replace />;

  if (sessionLost) return <Waiting />;
  if (request.error) {
    if (errorCode === "first_login") {
      return <Navigate to="/first-login" replace />;
    }
    const key =
      errorCode && TERMINAL_ERRORS.has(errorCode)
        ? `connect.errors.${errorCode}`
        : "connect.errors.generic";
    return (
      <ConnectStatusCard
        title={t("connect.errorTitle")}
        message={t(key)}
        color="red"
      />
    );
  }
  if (!request.data) return <Waiting />;

  return (
    <ConnectStatusCard title={t("connect.title")}>
      <ConnectRequestPanel request={request.data} />
    </ConnectStatusCard>
  );
}
