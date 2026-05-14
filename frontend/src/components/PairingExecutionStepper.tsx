/**
 * Stepper de progression de l'exécution serveur du wizard pairing.
 *
 * Chaque étape a un statut :
 *   - pending   : pas encore lancée
 *   - running   : en cours (spinner)
 *   - done      : succès (badge vert)
 *   - error     : échec (badge rouge + stderr)
 *
 * Sur une étape en erreur, un bouton « Réessayer depuis cette étape » apparaît.
 */
import { Badge, Button, Card, Code, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";

export interface StepMeta {
  idx: number;
  title: string;
  description: string;
}

export interface StepResult {
  ok: boolean;
  exitCode?: number;
  stdout: string;
  stderr: string;
}

export interface StepperState {
  runningIdx: number | null;
  results: Record<number, StepResult>;
}

interface Props {
  steps: StepMeta[];
  state: StepperState;
  onRetry: (fromStepIdx: number) => void;
}

export function PairingExecutionStepper({ steps, state, onRetry }: Props) {
  const { t } = useTranslation();
  return (
    <Stack>
      {steps.map((s) => {
        const r = state.results[s.idx];
        const isRunning = state.runningIdx === s.idx;
        return (
          <Card key={s.idx} withBorder>
            <Group justify="space-between" align="flex-start">
              <Stack gap={4} style={{ flex: 1 }}>
                <Group gap="sm">
                  <Title order={5}>{s.idx + 1}. {s.title}</Title>
                  {!r && !isRunning && <Badge color="gray">{t("pairingExec.pending")}</Badge>}
                  {isRunning && (
                    <Badge color="blue" leftSection={<Loader size="xs" />}>
                      {t("pairingExec.running")}
                    </Badge>
                  )}
                  {r?.ok && <Badge color="green">{t("pairingExec.done")}</Badge>}
                  {r && !r.ok && <Badge color="red">{t("pairingExec.error")}</Badge>}
                </Group>
                <Text size="sm" c="dimmed">{s.description}</Text>
                {r && !r.ok && (
                  <Code block style={{ background: "#330000", color: "#ff8888" }}>
                    {r.stderr || r.stdout}
                  </Code>
                )}
              </Stack>
              {r && !r.ok && (
                <Button color="orange" variant="outline" size="xs" onClick={() => onRetry(s.idx)}>
                  {t("pairingExec.retryFrom", { n: s.idx + 1 })}
                </Button>
              )}
            </Group>
          </Card>
        );
      })}
    </Stack>
  );
}
