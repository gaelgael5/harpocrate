import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import i18n from "@/lib/i18n";
import { PairingWizardPage } from "@/pages/PairingWizardPage";
import * as installModeLib from "@/lib/installMode";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <I18nextProvider i18n={i18n}>
          <MemoryRouter initialEntries={["/admin/pairing/abc-sid"]}>
            <Routes>
              <Route path="/admin/pairing/:sessionId" element={<PairingWizardPage />} />
            </Routes>
          </MemoryRouter>
        </I18nextProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe("PairingWizardPage (exec mode)", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("affiche la modale credentials en mode natif", async () => {
    vi.spyOn(installModeLib, "fetchInstallMode").mockResolvedValueOnce({
      mode: "native",
      docker_socket_accessible: false,
      pg_container_data_host_path: null,
    });
    renderPage();
    expect(await screen.findByText(/identifiants ssh|ssh credentials/i)).toBeInTheDocument();
  });
});
