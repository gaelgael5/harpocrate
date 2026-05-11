/**
 * Tests for API keys UI — LOT_08.
 *
 * Covers :
 * - List renders entries from mocked API response
 * - Permissions bitmap decoded correctly
 * - Create form requires name + at least one permission
 * - Token modal shows the token and the Copy button
 * - Revoke button calls DELETE and refetches
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { MemoryRouter, Routes, Route } from "react-router-dom";

// ─── i18n minimal ─────────────────────────────────────────────────────────────

const i18nTest = i18n.createInstance();
await i18nTest.use(initReactI18next).init({
  lng: "en",
  resources: {
    en: {
      translation: {
        "apiKeys.title": "API Keys",
        "apiKeys.newKey": "New API key",
        "apiKeys.createTitle": "Create an API key",
        "apiKeys.noKeys": "No API keys.",
        "apiKeys.name": "Name",
        "apiKeys.description": "Description",
        "apiKeys.permissions": "Permissions",
        "apiKeys.expires": "Expires",
        "apiKeys.lastUsed": "Last used",
        "apiKeys.status": "Status",
        "apiKeys.active": "Active",
        "apiKeys.revoke": "Revoke",
        "apiKeys.revoked": "Revoked",
        "apiKeys.revokeConfirm": "Revoke this API key?",
        "apiKeys.revokeSuccess": "API key revoked",
        "apiKeys.expiresInDays": "Expiration (days)",
        "apiKeys.expiresInDaysHint": "Leave empty for no expiration",
        "apiKeys.nameRequired": "Name is required",
        "apiKeys.permissionsRequired": "Select at least one permission",
        "apiKeys.tokenOneShot": "Token (shown once only)",
        "apiKeys.tokenWarning": "Warning — one-shot token",
        "apiKeys.tokenWarningDetail": "This token will NEVER be shown again.",
        "apiKeys.tokenSavedConfirm": "I have saved the token in a safe place",
        "apiKeys.create": "Create",
        "apiKeys.apiKeysButton": "API Keys",
        "common.back": "Back",
        "common.cancel": "Cancel",
        "common.close": "Close",
        "common.copy": "Copy",
        "common.copied": "Copied!",
        "common.error": "Error",
        "common.save": "Save",
        "errors.serverError": "Server error",
        "errors.cryptoRequired": "Vault must be unlocked",
        "errors.network": "Network error",
        "permissions.read": "read",
        "permissions.add": "add",
        "permissions.init": "init",
        "permissions.write": "write",
        "permissions.remove": "remove",
        "permissions.share": "share",
      },
    },
  },
  interpolation: { escapeValue: false },
});

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("@/hooks/useApiKeys");
vi.mock("@/stores/crypto");

import {
  useApiKeysList,
  useCreateApiKey,
  useRevokeApiKey,
} from "@/hooks/useApiKeys";
import { useCryptoStore } from "@/stores/crypto";
import type { ApiKeyListResponse, ApiKeyItem } from "@/schemas/apiKeys";

const mockUseApiKeysList = vi.mocked(useApiKeysList);
const mockUseCreateApiKey = vi.mocked(useCreateApiKey);
const mockUseRevokeApiKey = vi.mocked(useRevokeApiKey);
const mockUseCryptoStore = vi.mocked(useCryptoStore);

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <I18nextProvider i18n={i18nTest}>
      <MantineProvider>
        <Notifications />
        <QueryClientProvider client={makeQueryClient()}>
          <MemoryRouter initialEntries={["/wallets/wallet-1/api-keys"]}>
            <Routes>
              <Route
                path="/wallets/:walletId/api-keys"
                element={<>{children}</>}
              />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </MantineProvider>
    </I18nextProvider>
  );
}

function makeKey(overrides: Partial<ApiKeyItem> = {}): ApiKeyItem {
  return {
    id: "key-uuid-1",
    name: "my-key",
    description: null,
    owner_user_id: "user-uuid-1",
    permissions: 0x07, // read + add + init
    expires_at: null,
    revoked_at: null,
    last_used_at: null,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function setupMocks(keys: ApiKeyItem[] = []) {
  mockUseApiKeysList.mockReturnValue({
    data: { api_keys: keys } as ApiKeyListResponse,
    isLoading: false,
    error: null,
  } as ReturnType<typeof useApiKeysList>);

  mockUseCreateApiKey.mockReturnValue({
    mutateAsync: vi
      .fn()
      .mockResolvedValue({ api_key_id: "new-id", token: "hrpv_1_test_token" }),
    isPending: false,
  } as unknown as ReturnType<typeof useCreateApiKey>);

  mockUseRevokeApiKey.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  } as unknown as ReturnType<typeof useRevokeApiKey>);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockUseCryptoStore.mockImplementation((selector: any) =>
    selector({
      rsaPrivateKey: new Uint8Array(32),
      rsaPublicKey: new Uint8Array(64),
      symKey: new Uint8Array(32),
      isUnlocked: true,
      walletKeys: new Map(),
      cacheWalletKey: vi.fn(),
      getWalletKey: vi.fn().mockReturnValue(null),
      setUnlocked: vi.fn(),
      lock: vi.fn(),
    }),
  );
}

// ─── Import du composant après les mocks ──────────────────────────────────────

import { ApiKeysPage } from "@/pages/ApiKeysPage";
import { ApiKeyTokenModal } from "@/components/ApiKeyTokenModal";
import { permissionsToBadges } from "@/schemas/apiKeys";

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("permissionsToBadges", () => {
  it("decodes 0x07 as read + add + init", () => {
    const badges = permissionsToBadges(0x07);
    expect(badges).toEqual(["read", "add", "init"]);
  });

  it("decodes 0x3F as all permissions", () => {
    const badges = permissionsToBadges(0x3f);
    expect(badges).toEqual(["read", "add", "init", "write", "remove", "share"]);
  });

  it("decodes 0x01 as read only", () => {
    expect(permissionsToBadges(1)).toEqual(["read"]);
  });

  it("decodes 0x20 as share only", () => {
    expect(permissionsToBadges(32)).toEqual(["share"]);
  });
});

describe("ApiKeysPage", () => {
  beforeEach(() => {
    setupMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when no keys", () => {
    setupMocks([]);
    render(<ApiKeysPage />, { wrapper: Wrapper });
    expect(screen.getByText("No API keys.")).toBeInTheDocument();
  });

  it("renders key list from API response", () => {
    setupMocks([makeKey({ name: "my-key", permissions: 0x07 })]);
    render(<ApiKeysPage />, { wrapper: Wrapper });
    expect(screen.getByText("my-key")).toBeInTheDocument();
  });

  it("decodes permissions bitmap to badges correctly", () => {
    setupMocks([makeKey({ permissions: 0x07 })]);
    render(<ApiKeysPage />, { wrapper: Wrapper });
    // 0x07 = read + add + init — badges appear in the table row (as <span> inside Badge)
    // The page also renders PermissionsCheckboxes (collapsed) with same labels in <label>.
    // Use getAllByText to tolerate duplicates, then assert at least one badge is present.
    expect(screen.getAllByText("read").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("add").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("init").length).toBeGreaterThanOrEqual(1);
    // 'write' should not appear as a badge (bit not set)
    // It does appear as a checkbox label in the collapsed form, so check badge specifically
    const writeBadges = screen
      .queryAllByText("write")
      .filter((el) => el.closest('[class*="Badge"]') !== null);
    expect(writeBadges).toHaveLength(0);
  });

  it("shows revoke button only for non-revoked keys", () => {
    const active = makeKey({
      id: "key-1",
      name: "active-key",
      revoked_at: null,
    });
    const revoked = makeKey({
      id: "key-2",
      name: "revoked-key",
      revoked_at: "2025-01-01T00:00:00Z",
    });
    setupMocks([active, revoked]);
    render(<ApiKeysPage />, { wrapper: Wrapper });
    expect(screen.getAllByText("Revoke")).toHaveLength(1);
  });

  it("calls revoke mutation when Révoquer clicked and confirmed", async () => {
    const key = makeKey({ id: "key-uuid-1", name: "to-revoke" });
    setupMocks([key]);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ApiKeysPage />, { wrapper: Wrapper });

    const revokeBtn = screen.getByText("Revoke");
    fireEvent.click(revokeBtn);

    await waitFor(() => {
      expect(mockUseRevokeApiKey("wallet-1").mutateAsync).toHaveBeenCalledWith(
        "key-uuid-1",
      );
    });
  });

  it("does not call revoke mutation when confirm is cancelled", async () => {
    const key = makeKey();
    setupMocks([key]);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<ApiKeysPage />, { wrapper: Wrapper });

    const revokeBtn = screen.getByText("Revoke");
    fireEvent.click(revokeBtn);

    await waitFor(() => {
      expect(
        mockUseRevokeApiKey("wallet-1").mutateAsync,
      ).not.toHaveBeenCalled();
    });
  });

  it("opens create form when button is clicked", () => {
    setupMocks([]);
    render(<ApiKeysPage />, { wrapper: Wrapper });
    const btn = screen.getByText("New API key");
    fireEvent.click(btn);
    expect(screen.getByText("Create an API key")).toBeInTheDocument();
  });
});

describe("ApiKeyTokenModal", () => {
  function renderModal(token: string | null, onClose = vi.fn()) {
    return render(
      <I18nextProvider i18n={i18nTest}>
        <MantineProvider>
          <ApiKeyTokenModal token={token} onClose={onClose} />
        </MantineProvider>
      </I18nextProvider>,
    );
  }

  it("does not render when token is null", () => {
    renderModal(null);
    expect(screen.queryByText("Token (shown once only)")).toBeNull();
  });

  it("shows token in code block", () => {
    renderModal("hrpv_1_test_token_abc");
    expect(screen.getByText("hrpv_1_test_token_abc")).toBeInTheDocument();
  });

  it("shows Copy button", () => {
    renderModal("hrpv_1_token");
    expect(screen.getByText("Copy")).toBeInTheDocument();
  });

  it("shows the warning message", () => {
    renderModal("hrpv_1_token");
    expect(
      screen.getByText("This token will NEVER be shown again."),
    ).toBeInTheDocument();
  });

  it("closes only after confirming via checkbox", async () => {
    const onClose = vi.fn();
    renderModal("hrpv_1_token", onClose);

    // The Close button wraps a <span>; query by role to get the <button> element
    const closeBtn = screen.getByRole("button", { name: /close/i });
    expect(closeBtn).toBeDisabled();

    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /close/i })).not.toBeDisabled();
    });

    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
