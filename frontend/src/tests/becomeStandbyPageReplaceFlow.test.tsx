/**
 * Tests du flux de remplacement de node dans BecomeStandbyPage.
 *
 * Scénario : l'API retourne 409 node_already_exists → la modale s'ouvre →
 * l'admin clique "Remplacer le node" → acceptPairingV2 est rappelé avec
 * force=true → navigation vers /admin/pairing/<sid>.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { BecomeStandbyPage } from "@/pages/BecomeStandbyPage";
import * as adminApi from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";

// ─── i18n dédié ───────────────────────────────────────────────────────────────

const testI18n = i18n.createInstance();
void testI18n.use(initReactI18next).init({
  lng: "fr",
  resources: {
    fr: {
      translation: {
        "common.error": "Erreur",
        "admin.replication.pairing.becomeStandby.title":
          "Ajouter en tant que standby",
        "admin.replication.pairing.becomeStandby.subtitle":
          "Colle l'URL d'appairage.",
        "admin.replication.pairing.becomeStandby.pairingUrl": "URL d'appairage",
        "admin.replication.pairing.becomeStandby.pairingUrlHint":
          "Format : https://master.example/pair?sid=…&t=…",
        "admin.replication.pairing.becomeStandby.submit":
          "Ajouter en tant que standby",
        "admin.replication.pairing.becomeStandby.replaceModal.title":
          "Un node existe déjà côté master",
        "admin.replication.pairing.becomeStandby.replaceModal.intro":
          "Un node de réplication portant cette URL est déjà enregistré.",
        "admin.replication.pairing.becomeStandby.replaceModal.existingLabel":
          "URL :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingHost":
          "Hôte :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingAppName":
          "Application name :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingState":
          "Dernier état :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingSeen":
          "Vu pour la dernière fois :",
        "admin.replication.pairing.becomeStandby.replaceModal.neverSeen":
          "jamais",
        "admin.replication.pairing.becomeStandby.replaceModal.cancel":
          "Annuler",
        "admin.replication.pairing.becomeStandby.replaceModal.replace":
          "Remplacer le node",
      },
    },
  },
});

// ─── Helper ───────────────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <I18nextProvider i18n={testI18n}>
          <MemoryRouter initialEntries={["/admin/replication/become-standby"]}>
            <Routes>
              <Route
                path="/admin/replication/become-standby"
                element={<BecomeStandbyPage />}
              />
              <Route
                path="/admin/pairing/:sid"
                element={<div>WizardPage</div>}
              />
            </Routes>
          </MemoryRouter>
        </I18nextProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("BecomeStandbyPage replace flow", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("affiche la modale puis relance avec force=true sur 409 node_already_exists", async () => {
    const acceptSpy = vi.spyOn(adminApi, "acceptPairingV2");

    acceptSpy.mockRejectedValueOnce(
      new ApiError(409, "node_already_exists", "node_already_exists", {
        error: "node_already_exists",
        existing_node: {
          id: "11111111-1111-1111-1111-111111111111",
          label: "https://b/",
          host: "b",
          application_name: "b",
          last_state: "disconnected",
          last_seen_at: null,
        },
      }),
    );
    acceptSpy.mockResolvedValueOnce({
      session_id: "22222222-2222-2222-2222-222222222222",
    });

    renderPage();

    // Saisir l'URL d'appairage
    const input = screen.getByPlaceholderText(/harpo-1/i);
    fireEvent.change(input, {
      target: { value: "https://a/pair?sid=x&t=y" },
    });

    // Cliquer sur le bouton de soumission
    const submitBtn = screen.getByRole("button", {
      name: /ajouter en tant que standby/i,
    });
    fireEvent.click(submitBtn);

    // Attendre l'apparition de la modale
    await screen.findByText(/un node existe déjà côté master/i);

    // Vérifier que l'hôte du node existant est affiché (peut apparaître plusieurs fois)
    expect(screen.getAllByText("b").length).toBeGreaterThanOrEqual(1);

    // Premier appel sans force
    expect(acceptSpy).toHaveBeenCalledWith(
      "https://a/pair?sid=x&t=y",
      false,
    );

    // Cliquer sur "Remplacer le node"
    fireEvent.click(
      screen.getByRole("button", { name: /remplacer le node/i }),
    );

    // Navigation vers le wizard
    await waitFor(() => {
      expect(screen.getByText("WizardPage")).toBeInTheDocument();
    });

    // Deuxième appel avec force=true
    expect(acceptSpy).toHaveBeenLastCalledWith(
      "https://a/pair?sid=x&t=y",
      true,
    );
  });
});
