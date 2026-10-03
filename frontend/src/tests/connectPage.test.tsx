/**
 * Page /connect et reprise de la demande — feature 2 de l'épic
 * « Connecter une application à un wallet ».
 *
 * Couvre :
 * - validation des paramètres et du chemin de reprise (pas de redirection ouverte)
 * - instance sans Keycloak → parcours indisponible (D15)
 * - non connecté → redirection DIRECTE vers Keycloak (D15), demande mémorisée
 * - connecté mais verrouillé → déverrouillage
 * - demande lisible → nom DÉCLARÉ de l'application ; demande expirée → message, reprise abandonnée
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import fr from "@/i18n/fr.json";
import { ApiError } from "@/lib/api-client";
import {
  connectPath,
  parseConnectParams,
  peekConnectResume,
  saveConnectResume,
} from "@/lib/connectResume";
import { fetchConnectRequest } from "@/lib/connectApi";
import { getUserManager, startLogin } from "@/lib/oidc";
import { useLocalLoginAvailable } from "@/hooks/useLocalLoginAvailable";
import { useCryptoStore } from "@/stores/crypto";
import { ConnectPage } from "@/pages/ConnectPage";

vi.mock("@/lib/oidc", () => ({
  getUserManager: vi.fn(),
  startLogin: vi.fn(() => Promise.resolve()),
}));
vi.mock("@/lib/connectApi", () => ({ fetchConnectRequest: vi.fn() }));
vi.mock("@/hooks/useLocalLoginAvailable", () => ({
  useLocalLoginAvailable: vi.fn(),
}));

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "fr",
  resources: { fr: { translation: fr } },
  interpolation: { escapeValue: false },
});

const REQUEST_URI = `urn:ietf:params:oauth:request_uri:${"a".repeat(43)}`;
const PARAMS = { clientId: "ragflow", requestUri: REQUEST_URI };
const VIEW = {
  client: {
    client_id: "ragflow",
    name: "Ragflow (déclaré)",
    description: null,
  },
  redirect_uri: "https://rag.example/cb",
  requested_permissions: 3,
  requested_ttl_days: 90,
  app_public_jwk: { kty: "EC", crv: "P-256", x: "x", y: "y" },
  expires_at: "2026-10-03T12:15:00Z",
};

function mockSession(loggedIn: boolean, oidc = true) {
  vi.mocked(useLocalLoginAvailable).mockReturnValue({
    localLoginAvailable: true,
    oidcAvailable: oidc,
  });
  vi.mocked(getUserManager).mockReturnValue({
    getUser: () =>
      Promise.resolve(loggedIn ? { expired: false, access_token: "t" } : null),
  } as unknown as ReturnType<typeof getUserManager>);
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <I18nextProvider i18n={i18nTest}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/connect" element={<ConnectPage />} />
              <Route path="/unlock" element={<div>page-unlock</div>} />
            </Routes>
          </MemoryRouter>
        </I18nextProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  useCryptoStore.setState({ isUnlocked: false });
});

describe("connectResume", () => {
  it("accepte des paramètres bien formés et refuse le reste", () => {
    expect(
      parseConnectParams(new URLSearchParams(connectPath(PARAMS).slice(9))),
    ).toEqual(PARAMS);
    expect(
      parseConnectParams(
        new URLSearchParams({ client_id: "Ragflow", request_uri: REQUEST_URI }),
      ),
    ).toBeNull();
    expect(
      parseConnectParams(
        new URLSearchParams({ client_id: "ragflow", request_uri: "//evil" }),
      ),
    ).toBeNull();
  });

  it("ne rend jamais un chemin de reprise altéré", () => {
    sessionStorage.setItem(
      "harpocrate.connect.resume",
      "https://evil.example/",
    );
    expect(peekConnectResume()).toBeNull();
    sessionStorage.setItem(
      "harpocrate.connect.resume",
      "/connect?client_id=ragflow&request_uri=//evil",
    );
    expect(peekConnectResume()).toBeNull();
    saveConnectResume(PARAMS);
    expect(peekConnectResume()).toBe(connectPath(PARAMS));
  });
});

describe("ConnectPage", () => {
  it("refuse un lien mal formé", async () => {
    mockSession(true);
    renderAt("/connect?client_id=ragflow&request_uri=bad");
    expect(await screen.findByText(fr.connect.invalidTitle)).toBeTruthy();
    expect(startLogin).not.toHaveBeenCalled();
  });

  it("annonce le parcours indisponible sans Keycloak", async () => {
    mockSession(false, false);
    renderAt(connectPath(PARAMS));
    expect(await screen.findByText(fr.connect.unavailableTitle)).toBeTruthy();
    expect(startLogin).not.toHaveBeenCalled();
  });

  it("redirige directement vers Keycloak et mémorise la demande", async () => {
    mockSession(false);
    renderAt(connectPath(PARAMS));
    await waitFor(() => expect(startLogin).toHaveBeenCalledTimes(1));
    expect(peekConnectResume()).toBe(connectPath(PARAMS));
    expect(fetchConnectRequest).not.toHaveBeenCalled();
  });

  it("envoie au déverrouillage un utilisateur connecté mais verrouillé", async () => {
    mockSession(true);
    renderAt(connectPath(PARAMS));
    expect(await screen.findByText("page-unlock")).toBeTruthy();
    expect(fetchConnectRequest).not.toHaveBeenCalled();
  });

  it("affiche le nom déclaré de l'application une fois déverrouillé", async () => {
    mockSession(true);
    useCryptoStore.setState({ isUnlocked: true });
    vi.mocked(fetchConnectRequest).mockResolvedValue(VIEW as never);
    renderAt(connectPath(PARAMS));
    expect(await screen.findByText("Ragflow (déclaré)")).toBeTruthy();
    expect(fetchConnectRequest).toHaveBeenCalledWith(PARAMS);
  });

  it("explique une demande expirée et abandonne la reprise", async () => {
    mockSession(true);
    useCryptoStore.setState({ isUnlocked: true });
    vi.mocked(fetchConnectRequest).mockRejectedValue(
      new ApiError(410, "request_expired", "expired"),
    );
    renderAt(connectPath(PARAMS));
    expect(
      await screen.findByText(fr.connect.errors.request_expired),
    ).toBeTruthy();
    await waitFor(() => expect(peekConnectResume()).toBeNull());
  });
});
