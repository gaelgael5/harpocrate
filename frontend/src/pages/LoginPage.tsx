import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Center,
  Stack,
  Text,
  Button,
  Loader,
  Tabs,
  TextInput,
  PasswordInput,
  Alert,
  Box,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api-client";
import { startLogin, getUserManager } from "@/lib/oidc";
import { localLogin, LocalAuthError } from "@/lib/authLocalApi";
import { useLocalLoginAvailable } from "@/hooks/useLocalLoginAvailable";
import { MeResponseSchema } from "@/schemas/auth";
import { useSessionStore } from "@/stores/session";
import { useCryptoStore } from "@/stores/crypto";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";

type State = "loading" | "show-login" | "redirecting";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setUser = useSessionStore((s) => s.setUser);
  const setLocalAdminToken = useSessionStore((s) => s.setLocalAdminToken);
  const isUnlocked = useCryptoStore((s) => s.isUnlocked);

  const [state, setState] = useState<State>("loading");
  const [loginError, setLoginError] = useState<string | null>(null);

  const [localUsername, setLocalUsername] = useState("");
  const [localPassword, setLocalPassword] = useState("");
  const [localSubmitting, setLocalSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const { localLoginAvailable, oidcAvailable } = useLocalLoginAvailable();

  useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const mgr = getUserManager();
        const user = await mgr.getUser();
        const localToken = useSessionStore.getState().localAdminToken;
        if ((!user || user.expired) && !localToken) {
          if (!cancelled) setState("show-login");
          return;
        }
        const me = await api.get<unknown>("/me");
        const parsed = MeResponseSchema.parse(me);
        setUser({
          id: parsed.id,
          keycloak_sub: parsed.keycloak_sub,
          email: parsed.email,
          display_name: parsed.display_name,
          has_bootstrap: parsed.has_bootstrap,
          rsa_key_size: parsed.rsa_key_size,
          kdf_params: parsed.kdf_params,
        });
        if (!cancelled) {
          setState("redirecting");
          navigate(isUnlocked ? "/" : "/unlock", { replace: true });
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError) {
          if (err.isFirstLogin) {
            setState("redirecting");
            navigate("/first-login", { replace: true });
            return;
          }
          if (err.isUnauthorized) {
            try {
              await getUserManager().removeUser();
            } catch {
              /* ignore */
            }
            setState("show-login");
            setLoginError(t("auth.sessionExpired"));
            return;
          }
        }
        setState("show-login");
        setLoginError(String(err));
      }
    }
    void probe();
    return () => {
      cancelled = true;
    };
  }, [navigate, setUser, isUnlocked]);

  async function handleLocalSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    setLocalSubmitting(true);
    try {
      const resp = await localLogin(localUsername, localPassword);
      setLocalAdminToken(resp.access_token);
      await getUserManager().removeUser();
      const me = await api.get<unknown>("/me");
      const parsed = MeResponseSchema.parse(me);
      setUser({
        id: parsed.id,
        keycloak_sub: parsed.keycloak_sub,
        email: parsed.email,
        display_name: parsed.display_name,
        has_bootstrap: parsed.has_bootstrap,
        rsa_key_size: parsed.rsa_key_size,
        kdf_params: parsed.kdf_params,
      });
      navigate(isUnlocked ? "/" : "/unlock", { replace: true });
    } catch (err) {
      if (err instanceof LocalAuthError && err.isInvalidCredentials) {
        setLocalError(t("auth.local_login.invalid_credentials"));
      } else if (err instanceof ApiError && err.isFirstLogin) {
        navigate("/first-login", { replace: true });
      } else {
        setLocalError(String(err));
      }
    } finally {
      setLocalSubmitting(false);
    }
  }

  if (state === "loading" || state === "redirecting") {
    return (
      <Center h="100vh" style={{ background: "var(--mantine-color-body)" }}>
        <Loader size="lg" color="brand" />
      </Center>
    );
  }

  return (
    <Center h="100vh" style={{ background: "var(--mantine-color-body)" }}>
      <Box style={{ position: "fixed", top: 16, right: 16, zIndex: 10 }}>
        <LocaleSwitcher />
      </Box>
      <Stack w={380} gap={0}>
        {/* Header */}
        <Box
          style={{
            borderBottom: "1px solid #dedad2",
            paddingBottom: "1.75rem",
            marginBottom: "1.75rem",
            textAlign: "center",
          }}
        >
          <Box
            style={{
              width: 40,
              height: 40,
              background: "#1e40af",
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 1.2rem",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "0.75rem",
              color: "#fff",
              letterSpacing: "-0.04em",
            }}
          >
            Hp
          </Box>
          <Text
            style={{
              fontFamily: "'Cormorant Garamond', Georgia, serif",
              fontSize: "1.75rem",
              fontWeight: 400,
              lineHeight: 1.2,
              color: "#0a0a0a",
              marginBottom: "0.4rem",
            }}
          >
            Harpocrate
          </Text>
          <Text size="sm" c="dimmed">
            {t("unlock.subtitle")}
          </Text>
        </Box>

        {/* Form */}
        <Stack gap="md">
          {loginError && (
            <Alert
              color="red"
              variant="light"
              withCloseButton
              onClose={() => setLoginError(null)}
            >
              {loginError}
            </Alert>
          )}

          {/* Rendu selon les modes d'auth disponibles côté serveur :
              - oidc + local → Tabs avec les deux
              - oidc seul    → bouton Keycloak
              - local seul   → form local (cas où Keycloak pas configuré dans .env)
              Le validator backend garantit qu'au moins un des deux est dispo. */}
          {(() => {
            const localForm = (
              <form onSubmit={(e) => void handleLocalSubmit(e)}>
                <Stack gap="sm">
                  <TextInput
                    label={t("auth.local_login.username")}
                    value={localUsername}
                    onChange={(e) => setLocalUsername(e.currentTarget.value)}
                    required
                    data-testid="local-username"
                  />
                  <PasswordInput
                    label={t("auth.local_login.password")}
                    value={localPassword}
                    onChange={(e) => setLocalPassword(e.currentTarget.value)}
                    required
                    data-testid="local-password"
                  />
                  {localError && (
                    <Alert
                      color="red"
                      variant="light"
                      data-testid="local-error"
                    >
                      {localError}
                    </Alert>
                  )}
                  <Button
                    type="submit"
                    fullWidth
                    color="brand"
                    loading={localSubmitting}
                    data-testid="local-submit"
                  >
                    {t("auth.local_login.submit")}
                  </Button>
                </Stack>
              </form>
            );
            const keycloakBtn = (
              <Button fullWidth color="brand" onClick={() => void startLogin()}>
                {t("auth.loginWithKeycloak")}
              </Button>
            );
            if (oidcAvailable && localLoginAvailable) {
              return (
                <Tabs defaultValue="keycloak" color="brand">
                  <Tabs.List>
                    <Tabs.Tab value="keycloak">Keycloak</Tabs.Tab>
                    <Tabs.Tab value="local">
                      {t("auth.local_login.tab")}
                    </Tabs.Tab>
                  </Tabs.List>
                  <Tabs.Panel value="keycloak" pt="md">
                    {keycloakBtn}
                  </Tabs.Panel>
                  <Tabs.Panel value="local" pt="md">
                    {localForm}
                  </Tabs.Panel>
                </Tabs>
              );
            }
            if (oidcAvailable) return keycloakBtn;
            if (localLoginAvailable) return localForm;
            // Cas théoriquement bloqué côté backend (validator). Si on y est,
            // c'est que /v1/config/auth-modes est inaccessible : message neutre.
            return (
              <Alert color="orange" variant="light">
                {t("auth.no_mode_available")}
              </Alert>
            );
          })()}
        </Stack>

        <Text
          mt="xl"
          ta="center"
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "0.65rem",
            letterSpacing: "0.06em",
            color: "rgba(10,10,10,0.3)",
          }}
        >
          AES-256-GCM · Argon2id · RSA-4096
        </Text>
      </Stack>
    </Center>
  );
}
