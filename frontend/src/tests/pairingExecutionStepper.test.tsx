import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";

import { PairingExecutionStepper } from "@/components/PairingExecutionStepper";

const STEPS = [
  { idx: 0, title: "Arrêter PG", description: "…" },
  { idx: 1, title: "Backup data dir", description: "…" },
];

function renderStepper(state: {
  runningIdx: number | null;
  results: Record<number, { ok: boolean; exitCode?: number; stdout: string; stderr: string }>;
}) {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <PairingExecutionStepper steps={STEPS} state={state} onRetry={vi.fn()} />
      </I18nextProvider>
    </MantineProvider>,
  );
}

describe("PairingExecutionStepper", () => {
  it("affiche pending sur toutes les étapes au départ", () => {
    renderStepper({ runningIdx: null, results: {} });
    // Deux badges "en attente" (un par étape)
    expect(screen.getAllByText(/en attente|pending/i).length).toBe(2);
  });
  it("affiche running sur l'étape courante", () => {
    renderStepper({ runningIdx: 0, results: {} });
    expect(screen.getByText(/en cours|running/i)).toBeInTheDocument();
  });
  it("affiche error et stderr quand une étape échoue", () => {
    renderStepper({
      runningIdx: null,
      results: { 0: { ok: false, exitCode: 2, stdout: "", stderr: "boom" } },
    });
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });
});
