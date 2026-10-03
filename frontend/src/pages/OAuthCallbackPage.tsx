/**
 * OAuth2 callback page — processes the OIDC redirect and routes to /login,
 * or back to a pending /connect request.
 */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Center, Loader, Text, Stack } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { peekConnectResume } from "@/lib/connectResume";
import { handleCallback } from "@/lib/oidc";

export function OAuthCallbackPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;

    async function process() {
      try {
        await handleCallback();
        if (!cancelled) {
          // Demande « Se connecter avec Harpocrate » en cours : on y retourne directement
          // (la page /connect gère premier login et déverrouillage). Sinon /login, qui
          // re-sonde /me et oriente.
          navigate(peekConnectResume() ?? "/login", { replace: true });
        }
      } catch (err) {
        if (!cancelled) {
          console.error("OIDC callback error:", err);
          navigate("/login", { replace: true });
        }
      }
    }

    void process();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <Center h="100vh">
      <Stack align="center">
        <Loader size="xl" />
        <Text>{t("auth.callbackProcessing")}</Text>
      </Stack>
    </Center>
  );
}
