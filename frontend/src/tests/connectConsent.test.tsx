/**
 * Consentement et approbation — features 3 et 4 de l'épic
 * « Connecter une application à un wallet ».
 *
 * Couvre :
 * - règles de réduction (D3) : bits accordables = demandés ∩ droits, durée bornée
 * - écran : bit hors droits non cochable, refus, décision « nouveau coffre »
 * - orchestration : la dkey ne part jamais au serveur, elle est scellée avec le token ;
 *   une URL de retour inattendue est refusée
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";

import fr from "@/i18n/fr.json";
import { ConnectConsentForm } from "@/components/ConnectConsentForm";
import {
  createConnectApiKey,
  fetchAllWallets,
  sealConnectRequest,
} from "@/lib/connectApi";
import {
  approveConnectRequest,
  assertDeclaredRedirect,
} from "@/lib/connectApprove";
import {
  grantablePermissions,
  isTtlAllowed,
  maxTtlDays,
} from "@/lib/connectConsent";
import { sealForApplication } from "@/crypto/jwe-seal";
import { generateApiKeyMaterial } from "@/crypto/api-key-material";
import { loadWalletKey, createWalletWithKey } from "@/lib/walletKeyAccess";
import { useCryptoStore } from "@/stores/crypto";

vi.mock("@/lib/connectApi", () => ({
  fetchAllWallets: vi.fn(),
  createConnectApiKey: vi.fn(),
  sealConnectRequest: vi.fn(),
  denyConnectRequest: vi.fn(),
  fetchConnectRequest: vi.fn(),
}));
vi.mock("@/lib/walletKeyAccess", () => ({
  loadWalletKey: vi.fn(),
  createWalletWithKey: vi.fn(),
  CryptoLockedError: class extends Error {},
}));
vi.mock("@/crypto/jwe-seal", () => ({ sealForApplication: vi.fn() }));
vi.mock("@/crypto/api-key-material", () => ({
  generateApiKeyMaterial: vi.fn(),
}));
vi.mock("@/hooks/useApiKeys", () => ({
  useApiKeysList: () => ({ data: { api_keys: [] } }),
  useRevokeApiKey: () => ({ mutate: vi.fn(), isPending: false }),
}));

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "fr",
  resources: { fr: { translation: fr } },
  interpolation: { escapeValue: false },
});

const REDIRECT = "https://rag.example/cb";
const REQUEST = {
  client: { client_id: "ragflow", name: "Ragflow", description: null },
  redirect_uri: REDIRECT,
  requested_permissions: 0x01 | 0x02, // read + add
  requested_ttl_days: 90,
  app_public_jwk: { kty: "EC" as const, crv: "P-256" as const, x: "x", y: "y" },
  expires_at: "2026-10-03T12:15:00Z",
};
const PARAMS = {
  clientId: "ragflow",
  requestUri: `urn:ietf:params:oauth:request_uri:${"a".repeat(43)}`,
};
const WALLET = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Prod",
  description: null,
  tags: [],
  owner_user_id: "22222222-2222-2222-2222-222222222222",
  is_owner: true,
  my_permissions: 0x20 | 0x01, // share + read : pas « add »
  valued_secrets_count: 0,
  placeholder_secrets_count: 0,
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-01T10:00:00Z",
};

function renderForm(onApprove = vi.fn(), onDeny = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <I18nextProvider i18n={i18nTest}>
          <ConnectConsentForm
            request={REQUEST}
            onApprove={onApprove}
            onDeny={onDeny}
            approving={false}
            denying={false}
            error={null}
          />
        </I18nextProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
  return { onApprove, onDeny };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchAllWallets).mockResolvedValue([WALLET]);
});

describe("règles de consentement", () => {
  it("n'accorde que l'intersection demande ∩ droits", () => {
    expect(grantablePermissions(0x03, 0x21)).toBe(0x01);
    expect(grantablePermissions(0x03, null)).toBe(0x03);
  });

  it("borne la durée à celle demandée", () => {
    expect(maxTtlDays(90)).toBe(90);
    expect(isTtlAllowed(90, 90)).toBe(true);
    expect(isTtlAllowed(91, 90)).toBe(false);
    expect(isTtlAllowed(null, 90)).toBe(false);
    expect(isTtlAllowed(null, null)).toBe(true);
    expect(isTtlAllowed(0, null)).toBe(false);
  });
});

describe("ConnectConsentForm", () => {
  it("propose par défaut un nouveau coffre avec tout ce qui est demandé", async () => {
    const { onApprove } = renderForm();
    const approve = screen.getByRole("button", { name: fr.connect.approve });
    await waitFor(() => expect(approve).toBeEnabled());
    fireEvent.click(approve);
    expect(onApprove).toHaveBeenCalledWith({
      wallet: { kind: "new", name: "Ragflow" },
      permissions: 0x03,
      ttlDays: 90,
    });
  });

  it("refuse sans rien créer", () => {
    const { onDeny, onApprove } = renderForm();
    fireEvent.click(screen.getByText(fr.connect.deny));
    expect(onDeny).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("ne laisse pas cocher une permission hors des droits sur le coffre", async () => {
    const { onApprove } = renderForm();
    await waitFor(() => expect(fetchAllWallets).toHaveBeenCalled());
    fireEvent.click(
      screen.getByRole("textbox", { name: fr.connect.walletLabel }),
    );
    fireEvent.click(await screen.findByText("Prod"));

    const add = screen.getByRole("checkbox", { name: fr.permissions.add });
    expect(add).toBeDisabled();
    expect(add).not.toBeChecked();
    fireEvent.click(screen.getByText(fr.connect.approve));
    expect(onApprove).toHaveBeenCalledWith({
      wallet: { kind: "existing", walletId: WALLET.id },
      permissions: 0x01,
      ttlDays: 90,
    });
  });
});

describe("approveConnectRequest", () => {
  beforeEach(() => {
    useCryptoStore.setState({ rsaPublicKey: new Uint8Array([1, 2, 3]) });
    vi.mocked(loadWalletKey).mockResolvedValue(new Uint8Array(32));
    vi.mocked(createWalletWithKey).mockResolvedValue({
      walletId: "new-wallet",
      walletKey: new Uint8Array(32),
    });
    vi.mocked(generateApiKeyMaterial).mockResolvedValue({
      body: {
        auth_secret: "s",
        auth_hash: "h",
        auth_salt: "salt",
        auth_kdf_memory_kb: 65536,
        auth_kdf_iterations: 3,
        auth_kdf_parallelism: 4,
        encrypted_wallet_key: "ewk",
        encrypted_decryption_key_for_owner: "edk",
      },
      decryptionKey: "DKEY-SECRETE",
    });
    vi.mocked(createConnectApiKey).mockResolvedValue({
      api_key_id: "33333333-3333-3333-3333-333333333333",
      token: "hrpv_token_with_placeholder",
    });
    vi.mocked(sealForApplication).mockResolvedValue("jwe.compact");
  });

  it("scelle token et dkey sans jamais envoyer la dkey au serveur", async () => {
    vi.mocked(sealConnectRequest).mockResolvedValue(
      `${REDIRECT}?code=c&state=s`,
    );
    const url = await approveConnectRequest(PARAMS, REQUEST, {
      wallet: { kind: "new", name: "Mon coffre" },
      permissions: 0x01,
      ttlDays: 30,
    });

    expect(url).toBe(`${REDIRECT}?code=c&state=s`);
    expect(createWalletWithKey).toHaveBeenCalledWith("Mon coffre");
    const sent = vi.mocked(createConnectApiKey).mock.calls[0]?.[1];
    expect(sent).toMatchObject({
      wallet_id: "new-wallet",
      permissions: 1,
      ttl_days: 30,
    });
    expect(JSON.stringify(sent)).not.toContain("DKEY-SECRETE");
    expect(sealForApplication).toHaveBeenCalledWith(
      { token: "hrpv_token_with_placeholder", dkey: "DKEY-SECRETE" },
      REQUEST.app_public_jwk,
    );
    expect(sealConnectRequest).toHaveBeenCalledWith(PARAMS, "jwe.compact");
  });

  it("refuse de partir vers une autre adresse que celle déclarée", async () => {
    vi.mocked(sealConnectRequest).mockResolvedValue(
      "https://evil.example/cb?code=c",
    );
    await expect(
      approveConnectRequest(PARAMS, REQUEST, {
        wallet: { kind: "existing", walletId: WALLET.id },
        permissions: 0x01,
        ttlDays: 30,
      }),
    ).rejects.toThrow("unexpected_redirect");
    expect(loadWalletKey).toHaveBeenCalledWith(WALLET.id);
  });

  it("accepte la même adresse avec ses paramètres", () => {
    expect(
      assertDeclaredRedirect(`${REDIRECT}?error=access_denied`, REDIRECT),
    ).toBe(`${REDIRECT}?error=access_denied`);
    expect(() => assertDeclaredRedirect(`${REDIRECT}x`, REDIRECT)).toThrow();
  });
});
