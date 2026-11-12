/**
 * Écran admin des cultures — feature 1 de l'épic « Cultures et templates Listmonk
 * paramétrés en base ».
 *
 * Couvre :
 * - filtre « activées » par défaut, bascule « toutes », recherche
 * - activation / désactivation, culture par défaut non désactivable
 * - désignation de la culture par défaut
 * - traduction des refus métier du backend (409)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";

import fr from "@/i18n/fr.json";
import { ApiError } from "@/lib/api-client";
import { AdminCulturesPage } from "@/pages/AdminCulturesPage";
import { useCultures, useUpdateCulture } from "@/hooks/useCultures";
import type { Culture } from "@/schemas/cultures";

vi.mock("@/hooks/useCultures");
vi.mock("@mantine/notifications", () => ({
  notifications: { show: vi.fn() },
}));

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "fr",
  resources: { fr: { translation: fr } },
  interpolation: { escapeValue: false },
});

function culture(
  code: string,
  english: string,
  native: string | null,
  enabled = false,
  isDefault = false,
): Culture {
  return {
    code,
    english_name: english,
    native_name: native,
    enabled,
    is_default: isDefault,
    updated_at: "2026-11-11T10:00:00Z",
  };
}

const ITEMS = [
  culture("en", "English", "English", true, true),
  culture("fr", "French", "français", true),
  culture("de", "German", "Deutsch"),
];

const mutate = vi.fn();

function mockHooks(items: Culture[] = ITEMS) {
  vi.mocked(useCultures).mockReturnValue({
    data: { items },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useCultures>);
  vi.mocked(useUpdateCulture).mockReturnValue({
    mutate,
    isPending: false,
  } as unknown as ReturnType<typeof useUpdateCulture>);
}

function renderPage() {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18nTest}>
        <QueryClientProvider client={new QueryClient()}>
          <AdminCulturesPage />
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

const t = (key: string, opts?: Record<string, string>) => i18nTest.t(key, opts);

beforeEach(() => {
  vi.clearAllMocks();
  mockHooks();
});

describe("AdminCulturesPage", () => {
  it("affiche par défaut seulement les cultures activées", () => {
    renderPage();
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getByText("français")).toBeInTheDocument();
    expect(screen.queryByText("German")).not.toBeInTheDocument();
  });

  it("affiche toutes les cultures avec le filtre « Toutes »", () => {
    renderPage();
    fireEvent.click(screen.getByText(t("admin.cultures.filterAll")));
    expect(screen.getByText("German")).toBeInTheDocument();
    expect(screen.getByText("Deutsch")).toBeInTheDocument();
  });

  it("filtre par nom natif dans la recherche", () => {
    renderPage();
    fireEvent.click(screen.getByText(t("admin.cultures.filterAll")));
    fireEvent.change(screen.getByPlaceholderText(t("admin.cultures.search")), {
      target: { value: "deutsch" },
    });
    expect(screen.getByText("German")).toBeInTheDocument();
    expect(screen.queryByText("French")).not.toBeInTheDocument();
  });

  it("active une culture désactivée", () => {
    renderPage();
    fireEvent.click(screen.getByText(t("admin.cultures.filterAll")));
    fireEvent.click(
      screen.getByLabelText(
        t("admin.cultures.toggleLabel", { name: "German" }),
      ),
    );
    expect(mutate).toHaveBeenCalledWith(
      { code: "de", body: { enabled: true } },
      expect.anything(),
    );
  });

  it("grise l'interrupteur de la culture par défaut", () => {
    renderPage();
    expect(
      screen.getByLabelText(
        t("admin.cultures.toggleLabel", { name: "English" }),
      ),
    ).toBeDisabled();
    expect(
      screen.getByLabelText(
        t("admin.cultures.toggleLabel", { name: "French" }),
      ),
    ).not.toBeDisabled();
  });

  it("désigne une culture activée comme culture par défaut", () => {
    renderPage();
    const buttons = screen.getAllByText(t("admin.cultures.makeDefault"));
    // Seule « fr » (activée, non par défaut) propose le bouton.
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]!);
    expect(mutate).toHaveBeenCalledWith(
      { code: "fr", body: { is_default: true } },
      expect.anything(),
    );
  });

  it("traduit le refus « culture par défaut non désactivable »", async () => {
    mutate.mockImplementation((_vars, opts: { onError: (e: Error) => void }) =>
      opts.onError(
        new ApiError(409, "default_culture_cannot_be_disabled", "raw message"),
      ),
    );
    renderPage();
    fireEvent.click(
      screen.getByLabelText(
        t("admin.cultures.toggleLabel", { name: "French" }),
      ),
    );
    await waitFor(() =>
      expect(notifications.show).toHaveBeenCalledWith(
        expect.objectContaining({
          message: t(
            "admin.cultures.errors.default_culture_cannot_be_disabled",
          ),
        }),
      ),
    );
  });

  it("affiche le message brut d'une erreur inconnue", async () => {
    mutate.mockImplementation((_vars, opts: { onError: (e: Error) => void }) =>
      opts.onError(new ApiError(500, "error", "boom")),
    );
    renderPage();
    fireEvent.click(
      screen.getByLabelText(
        t("admin.cultures.toggleLabel", { name: "French" }),
      ),
    );
    await waitFor(() =>
      expect(notifications.show).toHaveBeenCalledWith(
        expect.objectContaining({ message: "boom" }),
      ),
    );
  });
});
