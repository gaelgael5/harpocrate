/**
 * Terminal SSH dans le navigateur — xterm.js + WebSocket bridge backend.
 * L'admin saisit ses creds dans la modale ; rien n'est persisté côté front.
 *
 * Usage : <SSHTerminal /> à intégrer dans une page. Le composant gère son
 * propre cycle de vie (modale d'ouverture → WS bridge → fermeture).
 *
 * JWT : résolution asynchrone via getAccessToken() (OIDC) avec fallback sur
 * useSessionStore.getState().localAdminToken — même logique que le tokenProvider
 * configuré dans lib/oidc.ts.
 */
import { useEffect, useRef, useState } from "react";
import { Card, Stack, Group, Badge, Button, Alert } from "@mantine/core";
import { Terminal } from "xterm";
import { FitAddon } from "@xterm/addon-fit";
import { useTranslation } from "react-i18next";
import "xterm/css/xterm.css";

import { SSHCredentialsModal } from "./SSHCredentialsModal";
import {
  encodeOpen,
  encodeData,
  encodeResize,
  parseServerMessage,
  buildWsUrl,
} from "@/lib/sshTerminalSocket";
import type { SshOpenArgs } from "@/lib/sshTerminalSocket";
import { getAccessToken } from "@/lib/oidc";
import { useSessionStore } from "@/stores/session";

type Status = "idle" | "connecting" | "connected" | "disconnected" | "error";

/** Résout le JWT actif : OIDC en priorité, sinon token admin local. */
async function resolveJwt(): Promise<string | null> {
  try {
    const oidcToken = await getAccessToken();
    if (oidcToken) return oidcToken;
  } catch {
    // OIDC non initialisé — on passe au fallback
  }
  return useSessionStore.getState().localAdminToken;
}

export function SSHTerminal() {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const aliveRef = useRef(true);
  const onDataDisposeRef = useRef<{ dispose: () => void } | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [credModalOpen, setCredModalOpen] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;
    const term = new Terminal({
      convertEol: true,
      cursorBlink: true,
      fontFamily: "monospace",
      fontSize: 13,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const onResize = () => {
      fit.fit();
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(encodeResize(term.cols, term.rows));
      }
    };
    window.addEventListener("resize", onResize);
    return () => {
      aliveRef.current = false;
      onDataDisposeRef.current?.dispose();
      window.removeEventListener("resize", onResize);
      wsRef.current?.close();
      term.dispose();
    };
  }, []);

  function openConnection(creds: SshOpenArgs) {
    setStatus("connecting");
    setErrorMsg(null);

    resolveJwt()
      .then((jwt) => {
        if (!aliveRef.current) return;

        if (!jwt) {
          setErrorMsg("no_jwt");
          setStatus("error");
          return;
        }

        if (!aliveRef.current) return;
        const ws = new WebSocket(buildWsUrl(jwt));
        wsRef.current = ws;

        ws.onopen = () => ws.send(encodeOpen(creds));
        ws.onmessage = (ev) => {
          const m = parseServerMessage(String(ev.data));
          if (m === null) return;
          if (m.type === "ready") {
            setStatus("connected");
            const term = termRef.current;
            if (!term) return;
            ws.send(encodeResize(term.cols, term.rows));
            onDataDisposeRef.current?.dispose();
            onDataDisposeRef.current = term.onData((d: string) =>
              ws.send(encodeData(d)),
            );
          } else if (m.type === "data") {
            termRef.current?.write(m.data);
          } else if (m.type === "error") {
            setErrorMsg(m.message ?? m.errorCode);
            setStatus("error");
          }
        };
        ws.onclose = () => {
          setStatus((prev) => (prev === "error" ? "error" : "disconnected"));
        };
        ws.onerror = () => {
          setStatus("error");
          setErrorMsg("ws_error");
        };
      })
      .catch(() => {
        if (!aliveRef.current) return;
        setErrorMsg("jwt_resolve_error");
        setStatus("error");
      });
  }

  return (
    <Card withBorder p="sm">
      <Stack gap="xs">
        <Group justify="space-between">
          <Group gap="xs">
            <StatusBadge status={status} />
            {(status === "idle" || status === "disconnected") && (
              <Button size="xs" onClick={() => setCredModalOpen(true)}>
                {t("admin.ssh.credentials.connect")}
              </Button>
            )}
          </Group>
        </Group>
        {errorMsg !== null && (
          <Alert color="red">
            {t("admin.ssh.terminal.errorGeneric")}: {errorMsg}
          </Alert>
        )}
        <div
          ref={containerRef}
          style={{ width: "100%", height: 480, background: "#000" }}
        />
        <SSHCredentialsModal
          opened={credModalOpen}
          onClose={() => setCredModalOpen(false)}
          onSubmit={(creds) => {
            setCredModalOpen(false);
            openConnection(creds);
          }}
        />
      </Stack>
    </Card>
  );
}

interface StatusBadgeProps {
  status: Status;
}

function StatusBadge({ status }: StatusBadgeProps) {
  const { t } = useTranslation();
  if (status === "connected") {
    return <Badge color="green">{t("admin.ssh.terminal.connected")}</Badge>;
  }
  if (status === "connecting") {
    return <Badge color="blue">{t("admin.ssh.terminal.connecting")}</Badge>;
  }
  if (status === "error") {
    return <Badge color="red">{t("admin.ssh.terminal.errorGeneric")}</Badge>;
  }
  return <Badge color="gray">{t("admin.ssh.terminal.disconnected")}</Badge>;
}
