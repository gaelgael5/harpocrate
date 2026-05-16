/**
 * Route guard: requires OIDC session + vault unlocked.
 * Redirects to /login or /unlock as appropriate.
 */
import { type ReactNode, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Center, Loader } from "@mantine/core";

import { getUserManager } from "@/lib/oidc";
import { useCryptoStore } from "@/stores/crypto";
import { useSessionStore } from "@/stores/session";

interface Props {
  children: ReactNode;
}

type AuthState = "loading" | "logged-out" | "needs-unlock" | "ready";

export function ProtectedRoute({ children }: Props) {
  const [authState, setAuthState] = useState<AuthState>("loading");
  const isUnlocked = useCryptoStore((s) => s.isUnlocked);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const mgr = getUserManager();
        const user = await mgr.getUser();

        if (cancelled) return;

        // Authentifie : soit OIDC, soit local-admin token (les deux sont equivalents
        // pour ProtectedRoute — distinction faite cote backend via le claim `iss`).
        const localToken = useSessionStore.getState().localAdminToken;
        const isAuthenticated = (user && !user.expired) || !!localToken;

        if (!isAuthenticated) {
          setAuthState("logged-out");
        } else if (!isUnlocked) {
          setAuthState("needs-unlock");
        } else {
          setAuthState("ready");
        }
      } catch {
        if (!cancelled) setAuthState("logged-out");
      }
    }

    void check();
    return () => {
      cancelled = true;
    };
  }, [isUnlocked]);

  if (authState === "loading") {
    return (
      <Center h="100vh">
        <Loader size="xl" />
      </Center>
    );
  }

  if (authState === "logged-out") {
    return <Navigate to="/login" replace />;
  }

  if (authState === "needs-unlock") {
    return <Navigate to="/unlock" replace />;
  }

  return <>{children}</>;
}
