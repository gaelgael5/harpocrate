/**
 * Écran « Paramétrage Listmonk » — feature 2 de l'épic « Cultures et templates
 * Listmonk paramétrés en base ».
 *
 * Couvre :
 * - état de la connexion (lecture seule), une ligne par culture activée seulement
 * - enregistrement d'un ID, refus d'un ID invalide, retrait d'un template
 * - alerte quand la culture par défaut n'a pas de template
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";

import fr from "@/i18n/fr.json";
import { AdminListmonkPage } from "@/pages/AdminListmonkPage";
import { useCultures } from "@/hooks/useCultures";
import {
  useDeleteListmonkTemplate,
  useListmonkSettings,
  useSetListmonkTemplate,
} from "@/hooks/useListmonk";
import type { Culture } from "@/schemas/cultures";
import type { ListmonkTemplate } from "@/schemas/listmonk";

vi.mock("@/hooks/useCultures");
vi.mock("@/hooks/useListmonk");
vi.mock("@mantine/notifications", () => ({
  notifications: { show: vi.fn() },
}));

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "fr",
  resources: { fr: { translation: fr } },
  interpolation: { escapeValue: false },
});

const t = (key: string, opts?: Record<string, string>) => i18nTest.t(key, opts);

function culture(
  code: string,
  name: string,
  enabled: boolean,
  isDefault = false,
): Culture {
  return {
    code,
    english_name: name,
    native_name: null,
    enabled,
    is_default: isDefault,
    updated_at: "2026-11-11T10:00:00Z",
  };
}

const CULTURES = [
  culture("en", "English", true, true),
  culture("fr", "French", true),
  culture("de", "German", false),
];

function template(cultureCode: string, templateId: number): ListmonkTemplate {
  return {
    purpose: "recovery",
    culture_code: cultureCode,
    template_id: templateId,
    updated_at: "2026-11-11T10:00:00Z",
  };
}

const saveMutate = vi.fn();
const deleteMutate = vi.fn();

function mockHooks(templates: ListmonkTemplate[], configured = true) {
  vi.mocked(useCultures).mockReturnValue({
    data: { items: CULTURES },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useCultures>);
  vi.mocked(useListmonkSettings).mockReturnValue({
    data: {
      configured,
      url: configured ? "https://listmonk.example/" : "",
      purposes: ["recovery"],
      templates,
    },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useListmonkSettings>);
  vi.mocked(useSetListmonkTemplate).mockReturnValue({
    mutate: saveMutate,
    isPending: false,
  } as unknown as ReturnType<typeof useSetListmonkTemplate>);
  vi.mocked(useDeleteListmonkTemplate).mockReturnValue({
    mutate: deleteMutate,
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteListmonkTemplate>);
}

function renderPage() {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18nTest}>
        <QueryClientProvider client={new QueryClient()}>
          <AdminListmonkPage />
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

const input = (name: string) =>
  screen.getByLabelText(t("admin.listmonk.templateIdLabel", { name }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AdminListmonkPage", () => {
  it("affiche l'état de la connexion et une ligne par culture activée", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    expect(
      screen.getByText(t("admin.listmonk.configured")),
    ).toBeInTheDocument();
    expect(screen.getByText("https://listmonk.example/")).toBeInTheDocument();
    expect(input("English")).toHaveValue("6");
    expect(input("French")).toHaveValue("");
    expect(screen.queryByText("German")).not.toBeInTheDocument();
  });

  it("signale une connexion non configurée", () => {
    mockHooks([template("en", 6)], false);
    renderPage();
    expect(
      screen.getByText(t("admin.listmonk.notConfigured")),
    ).toBeInTheDocument();
  });

  it("enregistre l'ID saisi pour une culture", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    fireEvent.change(input("French"), { target: { value: "5" } });
    const saveButtons = screen.getAllByText(t("admin.listmonk.save"));
    // Lignes dans l'ordre des cultures : English puis French.
    fireEvent.click(saveButtons[1]!);
    expect(saveMutate).toHaveBeenCalledWith(
      { purpose: "recovery", cultureCode: "fr", templateId: 5 },
      expect.anything(),
    );
  });

  it("n'active pas l'enregistrement sans changement ni pour un ID nul", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    const [enSave, frSave] = screen
      .getAllByText(t("admin.listmonk.save"))
      .map((el) => el.closest("button"));
    expect(enSave).toBeDisabled();
    fireEvent.change(input("French"), { target: { value: "0" } });
    expect(frSave).toBeDisabled();
  });

  it("retire le template d'une culture", () => {
    mockHooks([template("en", 6), template("fr", 5)]);
    renderPage();
    fireEvent.click(screen.getAllByText(t("admin.listmonk.remove"))[1]!);
    expect(deleteMutate).toHaveBeenCalledWith(
      { purpose: "recovery", cultureCode: "fr" },
      expect.anything(),
    );
  });

  it("alerte quand la culture par défaut n'a pas de template", () => {
    mockHooks([template("fr", 5)]);
    renderPage();
    expect(
      screen.getByText(t("admin.listmonk.missingDefault", { name: "English" })),
    ).toBeInTheDocument();
  });

  it("n'alerte pas quand la culture par défaut a un template", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    expect(
      screen.queryByText(
        t("admin.listmonk.missingDefault", { name: "English" }),
      ),
    ).not.toBeInTheDocument();
  });
});
