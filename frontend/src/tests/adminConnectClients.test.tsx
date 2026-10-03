/**
 * Écran admin du registre des applications — feature 1 de l'épic
 * « Connecter une application à un wallet ».
 *
 * Couvre :
 * - liste, état vide, statut actif / désactivé
 * - formulaire : validation des URLs de retour avant envoi, découpage ligne à ligne
 * - création, désactivation, conflit d'identifiant (409)
 * - validateur d'URL côté navigateur (miroir des règles du backend)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";
import { MemoryRouter } from "react-router-dom";

import fr from "@/i18n/fr.json";
import { ApiError } from "@/lib/api-client";
import { AdminConnectClientsPage } from "@/pages/AdminConnectClientsPage";
import {
  redirectUriProblem,
  parseRedirectUris,
} from "@/schemas/connectClients";
import {
  useConnectClients,
  useCreateConnectClient,
  useUpdateConnectClient,
} from "@/hooks/useConnectClients";

vi.mock("@/hooks/useConnectClients");

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "fr",
  resources: { fr: { translation: fr } },
  interpolation: { escapeValue: false },
});

const CLIENT = {
  id: "11111111-1111-1111-1111-111111111111",
  client_id: "ragflow",
  name: "Ragflow",
  description: "Moteur RAG",
  redirect_uris: ["https://rag.example/cb"],
  active: true,
  created_at: "2026-10-03T10:00:00Z",
  updated_at: "2026-10-03T10:00:00Z",
};

const createMutate = vi.fn();
const updateMutate = vi.fn();

function mockHooks(items: (typeof CLIENT)[], createError: unknown = null) {
  vi.mocked(useConnectClients).mockReturnValue({
    data: { items },
    isLoading: false,
    error: null,
  } as unknown as ReturnType<typeof useConnectClients>);
  createMutate.mockImplementation(() =>
    createError ? Promise.reject(createError) : Promise.resolve(CLIENT),
  );
  updateMutate.mockResolvedValue({ ...CLIENT, active: false });
  vi.mocked(useCreateConnectClient).mockReturnValue({
    mutateAsync: createMutate,
    isPending: false,
  } as unknown as ReturnType<typeof useCreateConnectClient>);
  vi.mocked(useUpdateConnectClient).mockReturnValue({
    mutateAsync: updateMutate,
    isPending: false,
  } as unknown as ReturnType<typeof useUpdateConnectClient>);
}

function renderPage() {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18nTest}>
        <QueryClientProvider client={new QueryClient()}>
          <MemoryRouter>
            <AdminConnectClientsPage />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

const t = (key: string) => i18nTest.t(key);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AdminConnectClientsPage", () => {
  it("affiche les applications déclarées avec leur statut", () => {
    mockHooks([
      CLIENT,
      {
        ...CLIENT,
        id: "22222222-2222-2222-2222-222222222222",
        client_id: "docflow",
        name: "Docflow",
        description: null,
        redirect_uris: ["https://doc.example/cb"],
        active: false,
      },
    ] as (typeof CLIENT)[]);
    renderPage();
    expect(screen.getByText("Ragflow")).toBeInTheDocument();
    expect(screen.getByText("ragflow")).toBeInTheDocument();
    expect(screen.getByText("https://rag.example/cb")).toBeInTheDocument();
    expect(
      screen.getByText(t("admin.connectClients.statusActive")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(t("admin.connectClients.statusDisabled")),
    ).toBeInTheDocument();
  });

  it("affiche un état vide explicite", () => {
    mockHooks([]);
    renderPage();
    expect(
      screen.getByText(t("admin.connectClients.empty")),
    ).toBeInTheDocument();
  });

  it("refuse une URL de retour en http hors poste local, sans appeler l'API", async () => {
    mockHooks([]);
    renderPage();
    fireEvent.click(
      screen.getByRole("button", { name: t("admin.connectClients.declare") }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.clientId"), {
        exact: false,
      }),
      {
        target: { value: "planner" },
      },
    );
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.name"), {
        exact: false,
      }),
      {
        target: { value: "Planner" },
      },
    );
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.redirectUris"), {
        exact: false,
      }),
      {
        target: { value: "http://planner.example/cb" },
      },
    );
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: t("admin.connectClients.save"),
      }),
    );
    expect(
      await within(dialog).findByText(
        t("admin.connectClients.errors.httpNotLocal"),
        { exact: false },
      ),
    ).toBeInTheDocument();
    expect(createMutate).not.toHaveBeenCalled();
  });

  it("crée une application avec les URLs découpées ligne à ligne", async () => {
    mockHooks([]);
    renderPage();
    fireEvent.click(
      screen.getByRole("button", { name: t("admin.connectClients.declare") }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.clientId"), {
        exact: false,
      }),
      {
        target: { value: "planner" },
      },
    );
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.name"), {
        exact: false,
      }),
      {
        target: { value: "Planner" },
      },
    );
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.redirectUris"), {
        exact: false,
      }),
      {
        target: {
          value: " https://planner.example/cb \n\nhttp://localhost:5173/cb\n",
        },
      },
    );
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: t("admin.connectClients.save"),
      }),
    );
    await waitFor(() =>
      expect(createMutate).toHaveBeenCalledWith({
        client_id: "planner",
        name: "Planner",
        description: null,
        redirect_uris: [
          "https://planner.example/cb",
          "http://localhost:5173/cb",
        ],
      }),
    );
  });

  it("affiche un message clair quand l'identifiant est déjà pris", async () => {
    mockHooks([], new ApiError(409, "client_id_taken", "taken"));
    renderPage();
    fireEvent.click(
      screen.getByRole("button", { name: t("admin.connectClients.declare") }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.clientId"), {
        exact: false,
      }),
      {
        target: { value: "ragflow" },
      },
    );
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.name"), {
        exact: false,
      }),
      {
        target: { value: "Ragflow" },
      },
    );
    fireEvent.change(
      within(dialog).getByLabelText(t("admin.connectClients.redirectUris"), {
        exact: false,
      }),
      {
        target: { value: "https://rag.example/cb" },
      },
    );
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: t("admin.connectClients.save"),
      }),
    );
    expect(
      await within(dialog).findByText(
        t("admin.connectClients.errors.clientIdTaken"),
      ),
    ).toBeInTheDocument();
  });

  it("désactive une application active", async () => {
    mockHooks([CLIENT]);
    renderPage();
    fireEvent.click(
      screen.getByRole("button", { name: t("admin.connectClients.disable") }),
    );
    await waitFor(() =>
      expect(updateMutate).toHaveBeenCalledWith({
        id: CLIENT.id,
        body: { active: false },
      }),
    );
  });
});

describe("redirectUriProblem", () => {
  it.each([
    "https://rag.example/oauth/cb",
    "https://portal.example:8443/cb?x=1",
    "http://localhost:5173/cb",
    "http://127.0.0.1:8000/cb",
  ])("accepte %s", (uri) => {
    expect(redirectUriProblem(uri)).toBeNull();
  });

  it.each([
    ["http://rag.example/cb", "httpNotLocal"],
    ["ftp://rag.example/cb", "notAbsoluteHttp"],
    ["/callback", "notAbsoluteHttp"],
    ["https://rag.example/cb#x", "fragment"],
    ["https://*.example/cb", "wildcard"],
    ["https://user:pw@rag.example/cb", "credentials"],
  ])("refuse %s (%s)", (uri, reason) => {
    expect(redirectUriProblem(uri)).toBe(reason);
  });
});

describe("parseRedirectUris", () => {
  it("découpe, rogne et retire les lignes vides et les doublons", () => {
    expect(
      parseRedirectUris(
        " https://a.example/cb \n\nhttps://b.example/cb\nhttps://a.example/cb",
      ),
    ).toEqual(["https://a.example/cb", "https://b.example/cb"]);
  });
});
