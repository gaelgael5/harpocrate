/**
 * Page wizard côté standby — exécution serveur des 7 étapes du pairing.
 *
 * Au mount :
 *  1) GET /admin/install-mode → décide quelle UI :
 *     - docker_compose_auto : ouvre directement le WS avec `open_docker`.
 *     - native              : affiche `SshCredsForExecModal`, à submit ouvre
 *                              le WS avec `open_native` + creds.
 *  2) Le WS push step_started/step_done/step_error/execution_complete →
 *     met à jour le `StepperState`.
 *  3) Bouton "Réessayer depuis l'étape N" → ferme le WS, en ouvre un
 *     nouveau avec `from_step_idx=N`.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Group, Loader, Stack, Title, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import {
  PairingExecutionStepper,
  type StepperState,
  type StepMeta,
  type StepResult,
} from "@/components/PairingExecutionStepper";
import { SshCredsForExecModal, type ExecCreds } from "@/components/SshCredsForExecModal";
import { fetchInstallMode } from "@/lib/installMode";
import { buildExecWsUrl, parseFrame, encodeOpen, type OpenFrame } from "@/lib/pairingExecSocket";
import { getAccessToken } from "@/lib/oidc";
import { useSessionStore } from "@/stores/session";

const STEP_KINDS = [
  "verify_master_reachable",
  "stop_pg_container",
  "backup_pg_data_dir",
  "pg_basebackup_from_master",
  "verify_standby_signal",
  "verify_auto_conf",
  "write_db_credentials_override",
  "start_pg_container",
  "verify_streaming",
] as const;

async function resolveJwt(): Promise<string | null> {
  try {
    const t = await getAccessToken();
    if (t) return t;
  } catch {
    // fallback ci-dessous
  }
  return useSessionStore.getState().localAdminToken;
}

export function PairingWizardPage() {
  const { t } = useTranslation();
  const { sessionId } = useParams<{ sessionId: string }>();
  const nav = useNavigate();

  const installMode = useQuery({
    queryKey: ["install-mode"],
    queryFn: fetchInstallMode,
  });

  const steps: StepMeta[] = STEP_KINDS.map((kind, idx) => ({
    idx,
    title: t(`pairingExec.steps.${kind}.title`),
    description: t(`pairingExec.steps.${kind}.description`),
  }));

  const [credsModalOpen, setCredsModalOpen] = useState(false);
  const [state, setState] = useState<StepperState>({ runningIdx: null, results: {} });
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!installMode.data || !sessionId) return;
    if (installMode.data.mode === "docker_compose_auto") {
      void openWs({ type: "open_docker" });
    } else {
      setCredsModalOpen(true);
    }
    return () => {
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installMode.data, sessionId]);

  async function openWs(open: OpenFrame): Promise<void> {
    if (!sessionId) return;
    const jwt = await resolveJwt();
    if (!jwt) return;
    wsRef.current?.close();
    const ws = new WebSocket(buildExecWsUrl(sessionId, jwt));
    wsRef.current = ws;
    ws.onopen = () => ws.send(encodeOpen(open));
    ws.onmessage = (ev) => {
      // Avant parse via schema d'event : intercepte les frames d'erreur
      // émises par le backend AVANT le lancement effectif de l'exécution
      // (token KO, self_ssh_host_not_configured, session_not_found, etc.).
      // Sans ça l'utilisateur voit le WS se fermer en silence.
      try {
        const raw = JSON.parse(String(ev.data)) as Record<string, unknown>;
        if (raw["type"] === "error") {
          const code = String(raw["code"] ?? "unknown");
          notifications.show({
            color: "red",
            title: t("pairingExec.error"),
            message: t(`pairingExec.errors.${code}`, { defaultValue: code }),
          });
          return;
        }
      } catch {
        // pas du JSON ou non-error → tombe sur parseFrame ci-dessous
      }
      const frame = parseFrame(String(ev.data));
      if (!frame) return;
      setState((prev) => {
        const next: StepperState = { runningIdx: prev.runningIdx, results: { ...prev.results } };
        if (frame.type === "step_started") {
          next.runningIdx = frame.step_idx;
        } else if (frame.type === "step_done") {
          next.runningIdx = null;
          const r: StepResult = {
            ok: true,
            exitCode: frame.exit_code,
            stdout: frame.stdout,
            stderr: frame.stderr,
          };
          next.results[frame.step_idx] = r;
        } else if (frame.type === "step_error") {
          next.runningIdx = null;
          const r: StepResult = {
            ok: false,
            exitCode: frame.exit_code,
            stdout: frame.stdout,
            stderr: frame.stderr,
          };
          next.results[frame.step_idx] = r;
        }
        return next;
      });
    };
  }

  function retryFromStep(idx: number): void {
    setState((prev) => {
      const cleaned: Record<number, StepResult> = {};
      Object.entries(prev.results).forEach(([k, v]) => {
        if (Number(k) < idx) cleaned[Number(k)] = v;
      });
      return { runningIdx: null, results: cleaned };
    });
    if (installMode.data?.mode === "docker_compose_auto") {
      void openWs({ type: "open_docker", from_step_idx: idx });
    } else {
      setCredsModalOpen(true);
    }
  }

  if (installMode.isLoading) return <Loader />;
  if (installMode.error) return <Alert color="red">{String(installMode.error)}</Alert>;

  return (
    <Stack>
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t("admin.replication.pairing.wizard.title")}</Title>
          <Text c="dimmed" size="sm">
            {t("admin.replication.pairing.wizard.subtitleA")}
          </Text>
        </Stack>
        <Button variant="subtle" color="gray" onClick={() => nav("/admin/replication")}>
          {t("admin.replication.pairing.wizard.abort")}
        </Button>
      </Group>
      <PairingExecutionStepper steps={steps} state={state} onRetry={retryFromStep} />
      <SshCredsForExecModal
        opened={credsModalOpen}
        onClose={() => setCredsModalOpen(false)}
        onSubmit={(c: ExecCreds) => {
          setCredsModalOpen(false);
          void openWs({ type: "open_native", ...c });
        }}
      />
    </Stack>
  );
}
