/**
 * Écran « Paramétrage Listmonk » — feature 2 de l'épic « Cultures et templates
 * Listmonk paramétrés en base ».
 *
 * Couvre :
 * - connexion : préremplie sans token, test, enregistrement avec ou sans nouveau token
 * - une ligne par culture activée seulement
 * - enregistrement d'un ID, refus d'un ID invalide, retrait d'un template
 * - alerte quand la culture par défaut n'a pas de template
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { notifications } from "@mantine/notifications";
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
  useSaveListmonkConnection,
  useSetListmonkTemplate,
  useTestListmonkConnection,
} from "@/hooks/useListmonk";
import type { Culture } from "@/schemas/cultures";
import type {
  ConnectionTestResult,
  ListmonkConnection,
  ListmonkTemplate,
} from "@/schemas/listmonk";

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

const CONNECTION: ListmonkConnection = {
  url: "http://mail.home.lan:9000",
  api_user: "harpocrate-api",
  token_readable: true,
  updated_at: "2026-11-12T10:00:00Z",
};

const saveMutate = vi.fn();
const deleteMutate = vi.fn();
const saveConnectionMutate = vi.fn();
const testConnectionMutate = vi.fn();
const testConnectionReset = vi.fn();

function mockHooks(
  templates: ListmonkTemplate[],
  connection: ListmonkConnection | null = CONNECTION,
  testResult: ConnectionTestResult | undefined = undefined,
) {
  vi.mocked(useCultures).mockReturnValue({
    data: { items: CULTURES },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useCultures>);
  vi.mocked(useListmonkSettings).mockReturnValue({
    data: { connection, purposes: ["recovery"], templates },
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
  vi.mocked(useSaveListmonkConnection).mockReturnValue({
    mutate: saveConnectionMutate,
    isPending: false,
  } as unknown as ReturnType<typeof useSaveListmonkConnection>);
  vi.mocked(useTestListmonkConnection).mockReturnValue({
    mutate: testConnectionMutate,
    reset: testConnectionReset,
    isPending: false,
    data: testResult,
  } as unknown as ReturnType<typeof useTestListmonkConnection>);
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
  it("affiche une ligne par culture activée", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    expect(input("English")).toHaveValue("6");
    expect(input("French")).toHaveValue("");
    expect(screen.queryByText("German")).not.toBeInTheDocument();
  });

  it("signale une connexion non configurée", () => {
    mockHooks([template("en", 6)], null);
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
    // Le premier « Enregistrer » est celui de la connexion ; puis English, French.
    fireEvent.click(saveButtons[2]!);
    expect(saveMutate).toHaveBeenCalledWith(
      { purpose: "recovery", cultureCode: "fr", templateId: 5 },
      expect.anything(),
    );
  });

  it("n'active pas l'enregistrement sans changement ni pour un ID nul", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    const [, enSave, frSave] = screen
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

describe("ListmonkConnectionCard", () => {
  const field = (key: string) => screen.getByLabelText(t(key));
  const button = (key: string) => screen.getByText(t(key)).closest("button");
  // Le bouton « Enregistrer » de la connexion est le premier de la page.
  const saveConnection = () =>
    screen.getAllByText(t("admin.listmonk.save"))[0]!.closest("button");

  it("préremplit URL et utilisateur, jamais le token", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    expect(field("admin.listmonk.url")).toHaveValue(CONNECTION.url);
    expect(field("admin.listmonk.apiUser")).toHaveValue(CONNECTION.api_user);
    expect(field("admin.listmonk.token")).toHaveValue("");
    expect(saveConnection()).toBeDisabled(); // rien n'a changé
  });

  it("enregistre un nouvel utilisateur en gardant le token", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    fireEvent.change(field("admin.listmonk.apiUser"), {
      target: { value: "other" },
    });
    fireEvent.click(saveConnection()!);
    expect(saveConnectionMutate).toHaveBeenCalledWith(
      { url: CONNECTION.url, api_user: "other" },
      expect.anything(),
    );
  });

  it("exige le token quand l'URL change", () => {
    mockHooks([template("en", 6)]);
    renderPage();
    fireEvent.change(field("admin.listmonk.url"), {
      target: { value: "https://listmonk.example" },
    });
    expect(saveConnection()).toBeDisabled();
    expect(button("admin.listmonk.test")).toBeDisabled();
  });

  it("efface le résultat du test dès qu'un champ change", () => {
    mockHooks([template("en", 6)], CONNECTION, { ok: true, http_status: 200 });
    renderPage();
    fireEvent.change(field("admin.listmonk.apiUser"), {
      target: { value: "other" },
    });
    expect(testConnectionReset).toHaveBeenCalled();
  });

  it("exige un token pour un premier réglage", () => {
    mockHooks([template("en", 6)], null);
    renderPage();
    fireEvent.change(field("admin.listmonk.url"), {
      target: { value: "http://mail.lan:9000" },
    });
    fireEvent.change(field("admin.listmonk.apiUser"), {
      target: { value: "api" },
    });
    expect(saveConnection()).toBeDisabled();
    expect(button("admin.listmonk.test")).toBeDisabled();
    fireEvent.change(field("admin.listmonk.token"), {
      target: { value: "s3cret" },
    });
    fireEvent.click(button("admin.listmonk.test")!);
    expect(testConnectionMutate).toHaveBeenCalledWith(
      { url: "http://mail.lan:9000", api_user: "api", token: "s3cret" },
      expect.anything(),
    );
  });

  it("exige de ressaisir un token devenu illisible", () => {
    mockHooks([template("en", 6)], { ...CONNECTION, token_readable: false });
    renderPage();
    expect(
      screen.getByText(t("admin.listmonk.tokenUnreadable")),
    ).toBeInTheDocument();
    expect(button("admin.listmonk.test")).toBeDisabled();
  });

  it("affiche le refus de Listmonk avec son statut HTTP", () => {
    mockHooks([template("en", 6)], CONNECTION, { ok: false, http_status: 403 });
    renderPage();
    expect(
      screen.getByText(t("admin.listmonk.testRefused", { status: "403" })),
    ).toBeInTheDocument();
  });

  it("annonce l'enregistrement réussi", () => {
    saveConnectionMutate.mockImplementation(
      (_body, opts: { onSuccess: () => void }) => opts.onSuccess(),
    );
    mockHooks([template("en", 6)]);
    renderPage();
    fireEvent.change(field("admin.listmonk.token"), {
      target: { value: "new-token" },
    });
    fireEvent.click(saveConnection()!);
    expect(notifications.show).toHaveBeenCalledWith(
      expect.objectContaining({ message: t("admin.listmonk.connectionSaved") }),
    );
  });
});
