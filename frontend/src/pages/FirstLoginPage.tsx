/**
 * First-login / bootstrap page.
 *
 * Flow:
 * 1. User enters passphrase (+ confirm)
 * 2. Client generates all crypto material (RSA keypair, sym_key, recovery seed)
 * 3. Displays 24-word recovery phrase — user must confirm
 * 4. POST /v1/me/bootstrap with encrypted blobs
 * 5. Store crypto state in RAM, redirect to /
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Center,
  Stack,
  Text,
  Button,
  Stepper,
  Alert,
  PasswordInput,
  Box,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/lib/api-client";
import { getUserManager } from "@/lib/oidc";
import { deriveKey, DEFAULT_KDF_PARAMS } from "@/crypto/argon2";
import { aesGcmEncrypt } from "@/crypto/aes-gcm";
import { generateRsaKeypair } from "@/crypto/rsa-oaep";
import { encodeBip39 } from "@/crypto/bip39";
import { toBase64, randomBytes } from "@/crypto/helpers";
import { useCryptoStore } from "@/stores/crypto";
import { useSessionStore } from "@/stores/session";
import { BootstrapResponseSchema, MeResponseSchema } from "@/schemas/auth";
import { RecoveryPhraseDisplay } from "@/components/RecoveryPhraseDisplay";

export function FirstLoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setUnlocked = useCryptoStore((s) => s.setUnlocked);
  const setUser = useSessionStore((s) => s.setUser);

  // Guard : si pas de session (ni OIDC ni local-admin), retour /login.
  // Sinon le bootstrap call serait fait sans Authorization header → 401 cryptique.
  useEffect(() => {
    void (async () => {
      const hasLocalToken = !!useSessionStore.getState().localAdminToken;
      const hasUser = !!useSessionStore.getState().user;
      let hasOidcSession = false;
      try {
        const oidcUser = await getUserManager().getUser();
        hasOidcSession = !!oidcUser?.access_token && !oidcUser.expired;
      } catch {
        /* OIDC pas initialisé */
      }
      if (!hasLocalToken && !hasUser && !hasOidcSession) {
        notifications.show({
          color: "orange",
          title: t("firstLogin.error"),
          message: t("firstLogin.no_session"),
        });
        navigate("/login", { replace: true });
      }
    })();
  }, [navigate, t]);

  const [step, setStep] = useState(0);
  const [passphrase, setPassphrase] = useState("");
  const [passphraseConfirm, setPassphraseConfirm] = useState("");
  const [passphraseError, setPassphraseError] = useState<string | null>(null);

  // Recovery phrase state
  const [recoveryWords, setRecoveryWords] = useState<string[]>([]);
  const [recoveryConfirmed, setRecoveryConfirmed] = useState(false);

  const [isWorking, setIsWorking] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");

  // Persisted crypto material between steps (NOT stored to any storage)
  const cryptoRef = {
    rsaPriv: null as Uint8Array | null,
    rsaPub: null as Uint8Array | null,
    symKey: null as Uint8Array | null,
    saltPassphrase: null as Uint8Array | null,
    saltRecovery: null as Uint8Array | null,
  };

  // Use a closure ref to persist across re-renders without React state
  const [cryptoMaterial] = useState(() => ({
    rsaPriv: null as Uint8Array | null,
    rsaPub: null as Uint8Array | null,
    symKey: null as Uint8Array | null,
    saltPassphrase: null as Uint8Array | null,
    saltRecovery: null as Uint8Array | null,
    recoverySeed: null as Uint8Array | null,
  }));
  void cryptoRef;

  function validatePassphrase(): boolean {
    if (passphrase.length < 12) {
      setPassphraseError(t("auth.passphraseTooShort"));
      return false;
    }
    if (passphrase !== passphraseConfirm) {
      setPassphraseError(t("auth.passphrasesMustMatch"));
      return false;
    }
    setPassphraseError(null);
    return true;
  }

  async function generateCryptoMaterial() {
    if (!validatePassphrase()) return;

    setIsWorking(true);
    setStatusMsg(t("firstLogin.generating"));
    try {
      // 1. Generate RSA keypair
      const { publicKey, privateKey } = await generateRsaKeypair(2048);
      cryptoMaterial.rsaPub = publicKey;
      cryptoMaterial.rsaPriv = privateKey;

      // 2. Generate sym_key (32 random bytes)
      cryptoMaterial.symKey = randomBytes(32);

      // 3. Generate salts
      cryptoMaterial.saltPassphrase = randomBytes(16);
      cryptoMaterial.saltRecovery = randomBytes(16);

      // 4. Generate recovery seed (32 bytes) and encode as BIP-39
      cryptoMaterial.recoverySeed = randomBytes(32);
      const words = await encodeBip39(cryptoMaterial.recoverySeed);
      setRecoveryWords(words);

      setStep(1);
    } catch (err) {
      notifications.show({
        color: "red",
        title: t("firstLogin.error"),
        message: String(err),
      });
    } finally {
      setIsWorking(false);
    }
  }

  async function submitBootstrap() {
    if (!recoveryConfirmed) return;
    if (
      !cryptoMaterial.rsaPriv ||
      !cryptoMaterial.rsaPub ||
      !cryptoMaterial.symKey ||
      !cryptoMaterial.saltPassphrase ||
      !cryptoMaterial.saltRecovery ||
      !cryptoMaterial.recoverySeed
    ) {
      return;
    }

    setIsWorking(true);
    setStatusMsg(t("firstLogin.bootstrapping"));

    try {
      const kdfParams = DEFAULT_KDF_PARAMS;

      // Derive pass_key
      const passKey = await deriveKey(
        passphrase,
        cryptoMaterial.saltPassphrase,
        kdfParams,
      );

      // Derive recovery_key from seed bytes
      const { deriveKeyFromSeed } = await import("@/crypto/argon2");
      const recoveryKey = await deriveKeyFromSeed(
        cryptoMaterial.recoverySeed,
        cryptoMaterial.saltRecovery,
        kdfParams,
      );

      // Encrypt rsa_priv with pass_key
      const encRsaPriv = await aesGcmEncrypt(cryptoMaterial.rsaPriv, passKey);

      // Encrypt sym_key with pass_key
      const encSymByPass = await aesGcmEncrypt(cryptoMaterial.symKey, passKey);

      // Encrypt sym_key with recovery_key
      const encSymByRecovery = await aesGcmEncrypt(
        cryptoMaterial.symKey,
        recoveryKey,
      );

      // LOT_57 fix : Encrypt rsa_priv with recovery_key — indispensable
      // pour rendre le flow recovery zero-knowledge fonctionnel. Sans cette
      // copie, l'utilisateur récupère sym_key via les 24 mots mais reste
      // sans accès à rsa_priv (chiffrée uniquement avec pass_key).
      const encRsaPrivByRecovery = await aesGcmEncrypt(
        cryptoMaterial.rsaPriv,
        recoveryKey,
      );

      // POST bootstrap
      const body = {
        rsa_public_key: toBase64(cryptoMaterial.rsaPub),
        salt_passphrase: toBase64(cryptoMaterial.saltPassphrase),
        salt_recovery: toBase64(cryptoMaterial.saltRecovery),
        encrypted_rsa_private_key: toBase64(encRsaPriv),
        encrypted_sym_key_by_pass: toBase64(encSymByPass),
        encrypted_sym_key_by_recovery: toBase64(encSymByRecovery),
        encrypted_rsa_private_key_by_recovery: toBase64(encRsaPrivByRecovery),
        kdf_memory_kb: kdfParams.memory_kb,
        kdf_iterations: kdfParams.iterations,
        kdf_parallelism: kdfParams.parallelism,
        rsa_key_size: 2048,
      };

      const resp = await api.post<unknown>("/me/bootstrap", body);
      BootstrapResponseSchema.parse(resp);

      // Fetch user info
      const me = await api.get<unknown>("/me");
      const meData = MeResponseSchema.parse(me);
      setUser({
        id: meData.id,
        keycloak_sub: meData.keycloak_sub,
        email: meData.email,
        display_name: meData.display_name,
        has_bootstrap: true,
        rsa_key_size: meData.rsa_key_size,
        kdf_params: meData.kdf_params,
      });

      // Store in RAM
      setUnlocked(
        cryptoMaterial.rsaPriv,
        cryptoMaterial.symKey,
        cryptoMaterial.rsaPub,
      );

      notifications.show({
        color: "green",
        message: t("firstLogin.success"),
      });

      navigate("/", { replace: true });
    } catch (err) {
      let msg = String(err);
      if (err instanceof ApiError) msg = err.message;
      notifications.show({
        color: "red",
        title: t("firstLogin.error"),
        message: msg,
      });
    } finally {
      setIsWorking(false);
    }
  }

  return (
    <Center
      mih="100vh"
      py="xl"
      style={{ background: "var(--mantine-color-body)" }}
    >
      <Stack w={600} gap="xl">
        <Stack align="center" gap="xs">
          <Box
            style={{
              width: 40,
              height: 40,
              background: "#1e40af",
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
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
              fontSize: "1.6rem",
              fontWeight: 400,
              color: "#0a0a0a",
            }}
          >
            {t("firstLogin.title")}
          </Text>
          <Text c="dimmed" size="sm">
            {t("firstLogin.subtitle")}
          </Text>
        </Stack>

        <Stepper active={step} allowNextStepsSelect={false}>
          <Stepper.Step label={t("firstLogin.step1")}>
            <Stack mt="md" gap="md">
              <PasswordInput
                label={t("firstLogin.passphraseLabel")}
                description={t("auth.passphraseHint")}
                value={passphrase}
                onChange={(e) => setPassphrase(e.currentTarget.value)}
                autoComplete="new-password"
                required
              />
              <PasswordInput
                label={t("firstLogin.passphraseConfirmLabel")}
                value={passphraseConfirm}
                onChange={(e) => setPassphraseConfirm(e.currentTarget.value)}
                autoComplete="new-password"
                error={passphraseError}
                required
              />
              <Button
                onClick={() => void generateCryptoMaterial()}
                loading={isWorking}
                // loading
                disabled={!passphrase || !passphraseConfirm}
              >
                {t("common.confirm")}
              </Button>
            </Stack>
          </Stepper.Step>

          <Stepper.Step label={t("firstLogin.step2")}>
            <Stack mt="md" gap="md">
              {recoveryWords.length > 0 && (
                <RecoveryPhraseDisplay
                  words={recoveryWords}
                  onConfirmed={() => void submitBootstrap()}
                  confirmed={recoveryConfirmed}
                  onConfirmedChange={setRecoveryConfirmed}
                />
              )}
              <Button
                onClick={() => void submitBootstrap()}
                loading={isWorking}
                // loading
                disabled={!recoveryConfirmed}
              >
                {t("common.confirm")}
              </Button>
            </Stack>
          </Stepper.Step>
        </Stepper>

        {isWorking && statusMsg && (
          <Alert color="brand" variant="light">
            {statusMsg}
          </Alert>
        )}
      </Stack>
    </Center>
  );
}
