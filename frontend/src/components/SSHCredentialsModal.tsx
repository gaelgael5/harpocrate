/**
 * Modale Mantine de saisie des identifiants SSH.
 *
 * Les credentials sont passés à `onSubmit` sans persistance — c'est le caller
 * (SSHTerminal) qui les transmet immédiatement au backend via WebSocket et
 * les oublie. Ne JAMAIS persister.
 */
import { useState, useEffect } from "react";
import {
  Modal,
  Stack,
  TextInput,
  NumberInput,
  SegmentedControl,
  Textarea,
  PasswordInput,
  Group,
  Button,
  Text,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { SshOpenArgs } from "@/lib/sshTerminalSocket";

interface Props {
  opened: boolean;
  onClose: () => void;
  onSubmit: (creds: SshOpenArgs) => void;
}

export function SSHCredentialsModal({ opened, onClose, onSubmit }: Props) {
  const { t } = useTranslation();
  const [host, setHost] = useState("");
  const [port, setPort] = useState<number | string>(22);
  const [username, setUsername] = useState("");
  const [authType, setAuthType] = useState<"password" | "privkey">("password");
  const [password, setPassword] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");

  useEffect(() => {
    if (!opened) {
      setHost("");
      setPort(22);
      setUsername("");
      setAuthType("password");
      setPassword("");
      setPrivateKey("");
      setPassphrase("");
    }
  }, [opened]);

  function submit() {
    const portN =
      typeof port === "number" ? port : parseInt(String(port), 10) || 22;
    if (authType === "password") {
      onSubmit({ host, port: portN, username, authType, password });
    } else {
      onSubmit({
        host,
        port: portN,
        username,
        authType,
        privateKey,
        passphrase,
      });
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("admin.ssh.credentials.title")}
      size="lg"
      closeOnClickOutside={false}
    >
      <Stack>
        <Text size="sm" c="dimmed">
          {t("admin.ssh.credentials.subtitle")}
        </Text>
        <TextInput
          label={t("admin.ssh.credentials.host")}
          value={host}
          onChange={(e) => setHost(e.currentTarget.value)}
          required
        />
        <NumberInput
          label={t("admin.ssh.credentials.port")}
          value={port}
          onChange={setPort}
          min={1}
          max={65535}
          required
        />
        <TextInput
          label={t("admin.ssh.credentials.username")}
          value={username}
          onChange={(e) => setUsername(e.currentTarget.value)}
          required
        />
        <SegmentedControl
          value={authType}
          onChange={(v) => setAuthType(v as "password" | "privkey")}
          data={[
            { value: "password", label: t("admin.ssh.credentials.password") },
            { value: "privkey", label: t("admin.ssh.credentials.privateKey") },
          ]}
        />
        {authType === "password" ? (
          <PasswordInput
            label={t("admin.ssh.credentials.password")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
          />
        ) : (
          <>
            <Textarea
              label={t("admin.ssh.credentials.privateKey")}
              autosize
              minRows={6}
              maxRows={12}
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              value={privateKey}
              onChange={(e) => setPrivateKey(e.currentTarget.value)}
            />
            <PasswordInput
              label={t("admin.ssh.credentials.passphrase")}
              value={passphrase}
              onChange={(e) => setPassphrase(e.currentTarget.value)}
            />
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t("admin.ssh.credentials.cancel")}
          </Button>
          <Button onClick={submit} disabled={!host || !username}>
            {t("admin.ssh.credentials.connect")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
