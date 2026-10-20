/**
 * Page Intégration — distribution des SDK par registre officiel (manifest 1.1).
 *
 * Couvre :
 * - SDK déclaré sur un registre : commandes d'installation + lien du paquet,
 *   aucun bouton de téléchargement de fichier même si des fichiers sont listés
 * - SDK distribué par fichier : boutons de téléchargement inchangés
 * - manifest 1.0 (sans champ `registry`) toujours lu
 * - bloc registre au lien non https : ignoré, le catalogue reste affiché
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";
import { MemoryRouter } from "react-router-dom";

import fr from "@/i18n/fr.json";
import { api } from "@/lib/api-client";
import { IntegrationPage } from "@/pages/IntegrationPage";

vi.mock("@/lib/api-client", () => ({ api: { get: vi.fn() } }));

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "fr",
  resources: { fr: { translation: fr } },
  interpolation: { escapeValue: false },
});

const WHEEL = {
  kind: "wheel",
  version: "0.6.0",
  filename: "harpocrate-0.6.0-py3-none-any.whl",
  media_type: "application/octet-stream",
  url: "/v1/sdk/by-filename/harpocrate-0.6.0-py3-none-any.whl",
  available: true,
  size_bytes: 10,
};

const PYPI = {
  name: "pypi",
  label: "PyPI",
  package: "harpocrate",
  version: "0.8.0",
  url: "https://pypi.org/project/harpocrate/",
  install_commands: ["pip install harpocrate", "uv add harpocrate"],
};

function pythonSdk(extra: Record<string, unknown>) {
  return {
    id: "python",
    name: "Python",
    icon: "🐍",
    status: "available",
    artifacts: [WHEEL],
    docs: {},
    ...extra,
  };
}

function renderPage(manifest: unknown) {
  vi.mocked(api.get).mockResolvedValue(manifest);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <I18nextProvider i18n={i18nTest}>
          <MemoryRouter>
            <IntegrationPage />
          </MemoryRouter>
        </I18nextProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe("IntegrationPage — distribution par registre", () => {
  beforeEach(() => vi.mocked(api.get).mockReset());

  it("affiche les commandes PyPI et le lien du paquet, sans bouton de wheel", async () => {
    renderPage({
      schema_version: "1.1",
      sdks: [pythonSdk({ registry: PYPI })],
    });

    expect(
      await screen.findByText("pip install harpocrate"),
    ).toBeInTheDocument();
    expect(screen.getByText("uv add harpocrate")).toBeInTheDocument();
    expect(screen.getByText(/0\.8\.0/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Voir le paquet sur PyPI/ });
    expect(link).toHaveAttribute(
      "href",
      "https://pypi.org/project/harpocrate/",
    );
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByText("Wheel (.whl)")).not.toBeInTheDocument();
  });

  it("garde les boutons de téléchargement d'un SDK distribué par fichier", async () => {
    renderPage({
      schema_version: "1.1",
      sdks: [pythonSdk({ registry: null })],
    });

    expect(await screen.findByText("Wheel (.whl)")).toBeInTheDocument();
    expect(
      screen.queryByText("pip install harpocrate"),
    ).not.toBeInTheDocument();
  });

  it("lit un manifest 1.0 sans champ registry", async () => {
    renderPage({ schema_version: "1.0", sdks: [pythonSdk({})] });

    expect(await screen.findByText("Wheel (.whl)")).toBeInTheDocument();
  });

  it("ignore un bloc registre dont le lien n'est pas https", async () => {
    renderPage({
      schema_version: "1.1",
      sdks: [pythonSdk({ registry: { ...PYPI, url: "javascript:alert(1)" } })],
    });

    expect(await screen.findByText("Wheel (.whl)")).toBeInTheDocument();
    expect(
      screen.queryByText("pip install harpocrate"),
    ).not.toBeInTheDocument();
  });
});
