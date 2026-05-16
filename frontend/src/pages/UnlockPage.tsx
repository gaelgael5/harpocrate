import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Center,
  Stack,
  Text,
  Button,
  PasswordInput,
  Alert,
  Loader,
  Box,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { notifications } from "@mantine/notifications";

import { api, ApiError } from "@/lib/api-client";
import { getUserManager } from "@/lib/oidc";
import { useSessionStore } from "@/stores/session";
import { deriveKey } from "@/crypto/argon2";
import { aesGcmDecrypt } from "@/crypto/aes-gcm";
import { fromBase64 } from "@/crypto/helpers";
import { useCryptoStore } from "@/stores/crypto";
import { CryptoResponseSchema } from "@/schemas/auth";

type PageState = "check-auth" | "ready" | "unlocking";

export function UnlockPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setUnlocked = useCryptoStore((s) => s.setUnlocked);
  const isUnlocked = useCryptoStore((s) => s.isUnlocked);

  const [pageState, setPageState] = useState<PageState>("check-auth");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isUnlocked) navigate("/", { replace: true });
  }, [isUnlocked, navigate]);

  useEffect(() => {
    async function checkAuth() {
      try {
        const mgr = getUserManager();
        const user = await mgr.getUser();
        const localToken = useSessionStore.getState().localAdminToken;
        const authenticated = (user && !user.expired) || !!localToken;
        if (!authenticated) {
          navigate("/login", { replace: true });
          return;
        }
        setPageState("ready");
      } catch {
        navigate("/login", { replace: true });
      }
    }
    void checkAuth();
  }, [navigate]);

  async function handleUnlock() {
    if (!passphrase) return;
    setPageState("unlocking");
    setError(null);

    try {
      const raw = await api.get<unknown>("/me/crypto");
      const crypto = CryptoResponseSchema.parse(raw);

      const saltPassphrase = fromBase64(crypto.salt_passphrase);
      const encRsaPriv = fromBase64(crypto.encrypted_rsa_private_key);
      const encSymByPass = fromBase64(crypto.encrypted_sym_key_by_pass);
      const rsaPub = fromBase64(crypto.rsa_public_key);

      const passKey = await deriveKey(passphrase, saltPassphrase, {
        memory_kb: crypto.kdf_params.memory_kb,
        iterations: crypto.kdf_params.iterations,
        parallelism: crypto.kdf_params.parallelism,
      });

      let rsaPriv: Uint8Array;
      let symKey: Uint8Array;
      try {
        rsaPriv = await aesGcmDecrypt(encRsaPriv, passKey);
        symKey = await aesGcmDecrypt(encSymByPass, passKey);
      } catch {
        setError(t("unlock.wrongPassphrase"));
        setPageState("ready");
        return;
      }

      setUnlocked(rsaPriv, symKey, rsaPub);
      notifications.show({ color: "green", message: t("auth.unlockSuccess") });
      navigate("/", { replace: true });
    } catch (err) {
      let msg = t("errors.serverError");
      if (err instanceof ApiError) {
        if (err.isFirstLogin) {
          navigate("/first-login", { replace: true });
          return;
        }
        if (err.isUnauthorized) {
          navigate("/login", { replace: true });
          return;
        }
        msg = err.message;
      }
      setError(msg);
      setPageState("ready");
    }
  }

  if (pageState === "check-auth") {
    return (
      <Center h="100vh">
        <Loader size="lg" color="brand" />
      </Center>
    );
  }

  return (
    <Center h="100vh" style={{ background: "var(--mantine-color-body)" }}>
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
            {t("unlock.title")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("unlock.subtitle")}
          </Text>
        </Box>

        {/* Form */}
        <Stack gap="md">
          {error && (
            <Alert color="red" variant="light" title={t("common.error")}>
              {error}
            </Alert>
          )}

          <PasswordInput
            label={t("unlock.passphraseLabel")}
            value={passphrase}
            onChange={(e) => setPassphrase(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleUnlock();
            }}
            autoComplete="current-password"
            autoFocus
            disabled={pageState === "unlocking"}
          />

          <Button
            fullWidth
            onClick={() => void handleUnlock()}
            loading={pageState === "unlocking"}
            disabled={!passphrase}
            color="brand"
          >
            {t("unlock.unlockButton")}
          </Button>

          {/* Lien discret vers le flow de recovery par 24 mots BIP-39. */}
          <Button
            variant="subtle"
            size="xs"
            onClick={() => navigate("/recover/start")}
            color="gray"
          >
            {t("unlock.forgotPassphrase")}
          </Button>
        </Stack>

        <Text
          mt="xl"
          size="xs"
          c="dimmed"
          ta="center"
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "0.65rem",
            letterSpacing: "0.06em",
          }}
        >
          AES-256-GCM · Argon2id · RSA-4096
        </Text>
      </Stack>
    </Center>
  );
}
