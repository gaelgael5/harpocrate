/**
 * Modale Mantine — saisie unique des credentials SSH pour le wizard pairing
 * en mode natif. Le host/port viennent de la configuration backend
 * (`HARPOCRATE_SELF_SSH_HOST` / `_PORT`), donc cette modale ne les demande pas.
 */
import { useState, useEffect } from "react";
import {
  Modal,
  Stack,
  TextInput,
  SegmentedControl,
  PasswordInput,
  Textarea,
  Group,
  Button,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

export interface ExecCreds {
  username: string;
  auth_type: "password" | "privkey";
  password?: string;
  private_key?: string;
  passphrase?: string;
}

interface Props {
  opened: boolean;
  onClose: () => void;
  onSubmit: (c: ExecCreds) => void;
}

export function SshCredsForExecModal({ opened, onClose, onSubmit }: Props) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [authType, setAuthType] = useState<"password" | "privkey">("password");
  const [password, setPassword] = useState("");
  const [privKey, setPrivKey] = useState("");
  const [passphrase, setPassphrase] = useState("");

  useEffect(() => {
    if (!opened) {
      setUsername("");
      setPassword("");
      setPrivKey("");
      setPassphrase("");
      setAuthType("password");
    }
  }, [opened]);

  function submit() {
    if (authType === "password") {
      onSubmit({ username, auth_type: "password", password });
    } else {
      onSubmit({ username, auth_type: "privkey", private_key: privKey, passphrase });
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("pairingExec.credsModal.title")}
      closeOnClickOutside={false}
    >
      <Stack>
        <TextInput
          label={t("pairingExec.credsModal.username")}
          value={username}
          onChange={(e) => setUsername(e.currentTarget.value)}
          required
        />
        <SegmentedControl
          value={authType}
          onChange={(v) => setAuthType(v as "password" | "privkey")}
          data={[
            { value: "password", label: t("pairingExec.credsModal.password") },
            { value: "privkey", label: t("pairingExec.credsModal.privKey") },
          ]}
        />
        {authType === "password" ? (
          <PasswordInput
            label={t("pairingExec.credsModal.password")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
          />
        ) : (
          <>
            <Textarea
              label={t("pairingExec.credsModal.privKey")}
              autosize
              minRows={6}
              value={privKey}
              onChange={(e) => setPrivKey(e.currentTarget.value)}
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
            />
            <PasswordInput
              label={t("pairingExec.credsModal.passphrase")}
              value={passphrase}
              onChange={(e) => setPassphrase(e.currentTarget.value)}
            />
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} disabled={!username}>
            {t("pairingExec.credsModal.start")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
