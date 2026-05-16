/**
 * Tests for export/import UI — LOT_07 follow-up.
 *
 * Covers:
 * - Export: download triggers blob URL creation and revocation
 * - Import preview: shows wallet name and secrets from parsed file
 * - Import confirm: calls POST and navigates on success
 * - Invalid JSON: shows error message
 * - Zod validation: rejects malformed payloads
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
        "common.back": "Back",
        "common.cancel": "Cancel",
        "common.error": "Error",
        "wallets.export.button": "Export",
        "wallets.export.success": "Export downloaded",
        "wallets.export.error": "Export failed",
        "wallets.import.button": "Import",
        "wallets.import.title": "Import a vault",
        "wallets.import.fileLabel": "Export JSON file",
        "wallets.import.filePlaceholder": "Choose a .json file",
        "wallets.import.preview": "Preview",
        "wallets.import.walletName": "Vault name",
        "wallets.import.description": "Description",
        "wallets.import.tags": "Tags",
        "wallets.import.secrets": "Secrets ({{count}})",
        "wallets.import.noSecrets": "No secrets in this export.",
        "wallets.import.placeholder": "Placeholder",
        "wallets.import.hasValue": "Structure",
        "wallets.import.confirm": "Confirm import",
        "wallets.import.importing": "Importing...",
        "wallets.import.success": "Vault imported successfully",
        "wallets.import.successDetail": "{{count}} secret(s) created",
        "wallets.import.invalidJson": "Invalid JSON file",
        "wallets.import.invalidFormat": "Invalid export format",
        "wallets.import.cryptoRequired": "Vault must be unlocked to import",
        "wallets.import.skipped": "{{count}} secret(s) skipped: {{names}}",
        "wallets.title": "My vaults",
        "wallets.create": "New vault",
        "grants.title": "Shares",
        "apiKeys.apiKeysButton": "API Keys",
        "secrets.create": "New secret",
        "secrets.title": "Secrets",
        "secrets.noSecrets": "No secrets in this vault.",
        "errors.serverError": "Server error",
        "errors.cryptoRequired": "Vault must be unlocked",
      },
    },
  },
  interpolation: { escapeValue: false },
});

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("@/lib/exportImportApi");
vi.mock("@/stores/crypto");
vi.mock("@/crypto/rsa-oaep", () => ({
  rsaOaepEncrypt: vi.fn().mockResolvedValue(new Uint8Array(64)),
}));
vi.mock("@/crypto/helpers", () => ({
  randomBytes: vi.fn().mockReturnValue(new Uint8Array(32)),
  toBase64: vi.fn().mockReturnValue("bW9ja2VkZW5jcnlwdGVka2V5"),
}));
vi.mock("@/lib/api-client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public code: string,
      message: string,
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { exportWallet, importWallet } from "@/lib/exportImportApi";
import { useCryptoStore } from "@/stores/crypto";
import {
  WalletExportSchema,
  WalletImportRequestSchema,
} from "@/schemas/exportImport";

const mockExportWallet = vi.mocked(exportWallet);
const mockImportWallet = vi.mocked(importWallet);
const mockUseCryptoStore = vi.mocked(useCryptoStore);

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function WalletDetailWrapper({ children }: { children: React.ReactNode }) {
  return (
    <I18nextProvider i18n={i18nTest}>
      <MantineProvider>
        <Notifications />
        <QueryClientProvider client={makeQueryClient()}>
          <MemoryRouter initialEntries={["/wallets/wallet-1"]}>
            <Routes>
              <Route path="/wallets/:walletId" element={<>{children}</>} />
              <Route
                path="/wallets/:walletId/secrets/new"
                element={<div>new secret</div>}
              />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </MantineProvider>
    </I18nextProvider>
  );
}

function ImportWrapper({ children }: { children: React.ReactNode }) {
  return (
    <I18nextProvider i18n={i18nTest}>
      <MantineProvider>
        <Notifications />
        <QueryClientProvider client={makeQueryClient()}>
          <MemoryRouter initialEntries={["/wallets/import"]}>
            <Routes>
              <Route path="/wallets/import" element={<>{children}</>} />
              <Route
                path="/wallets/:walletId"
                element={<div data-testid="wallet-detail">wallet detail</div>}
              />
              <Route path="/wallets" element={<div>wallets list</div>} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </MantineProvider>
    </I18nextProvider>
  );
}

function setupCryptoMock(hasKey = true) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockUseCryptoStore.mockImplementation((selector: any) =>
    selector({
      rsaPrivateKey: hasKey ? new Uint8Array(32) : null,
      rsaPublicKey: hasKey ? new Uint8Array(64) : null,
      symKey: new Uint8Array(32),
      isUnlocked: hasKey,
      walletKeys: new Map(),
      cacheWalletKey: vi.fn(),
      getWalletKey: vi.fn().mockReturnValue(null),
      setUnlocked: vi.fn(),
      lock: vi.fn(),
    }),
  );
}

/** Creates a File object from a JSON-serializable value. */
function makeJsonFile(content: unknown, name = "export.json"): File {
  const json = JSON.stringify(content);
  return new File([json], name, { type: "application/json" });
}

const VALID_EXPORT = {
  format_version: "1",
  exported_at: "2026-05-01T00:00:00Z",
  exported_from: "vault.dev.example.org",
  wallet: {
    name: "My Test Wallet",
    description: "A test wallet",
    tags: ["test"],
  },
  secrets: [
    {
      name: "API_KEY",
      description: "An API key",
      tags: ["api"],
      is_placeholder: true,
      generation_version: 1,
    },
    {
      name: "DB_PASSWORD",
      description: null,
      tags: [],
      is_placeholder: true,
      generation_version: 1,
    },
  ],
};

// ─── Import du composant après les mocks ──────────────────────────────────────

import { WalletImportPage } from "@/pages/WalletImportPage";
import { WalletDetailPage } from "@/pages/WalletDetailPage";

// ─── Tests Zod schemas ────────────────────────────────────────────────────────

describe("WalletExportSchema", () => {
  it("accepts a valid export payload", () => {
    const result = WalletExportSchema.safeParse(VALID_EXPORT);
    expect(result.success).toBe(true);
  });

  it('rejects format_version != "1"', () => {
    const bad = { ...VALID_EXPORT, format_version: "2" };
    const result = WalletExportSchema.safeParse(bad);
    expect(result.success).toBe(false);
  });

  it("rejects duplicate secret names", () => {
    const bad = {
      ...VALID_EXPORT,
      secrets: [
        { name: "DUPE", is_placeholder: true, tags: [], generation_version: 1 },
        { name: "DUPE", is_placeholder: true, tags: [], generation_version: 1 },
      ],
    };
    const result = WalletExportSchema.safeParse(bad);
    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).toContain("Duplicate secret names");
  });

  it("rejects linked_secret_name that does not exist in secrets", () => {
    const bad = {
      ...VALID_EXPORT,
      secrets: [
        {
          name: "SECRET_A",
          is_placeholder: true,
          tags: [],
          generation_version: 1,
          linked_secret_name: "NONEXISTENT",
        },
      ],
    };
    const result = WalletExportSchema.safeParse(bad);
    expect(result.success).toBe(false);
  });

  it("rejects secret name with invalid characters", () => {
    const bad = {
      ...VALID_EXPORT,
      secrets: [
        {
          name: "INVALID NAME!",
          is_placeholder: true,
          tags: [],
          generation_version: 1,
        },
      ],
    };
    const result = WalletExportSchema.safeParse(bad);
    expect(result.success).toBe(false);
  });
});

describe("WalletImportRequestSchema", () => {
  it("accepts a valid import request", () => {
    const payload = {
      format_version: "1",
      wallet: { name: "Test", tags: [] },
      secrets: [],
      encrypted_wallet_key_for_owner: "base64encodedkey==",
    };
    expect(WalletImportRequestSchema.safeParse(payload).success).toBe(true);
  });

  it("rejects missing encrypted_wallet_key_for_owner", () => {
    const payload = {
      format_version: "1",
      wallet: { name: "Test", tags: [] },
      secrets: [],
    };
    expect(WalletImportRequestSchema.safeParse(payload).success).toBe(false);
  });

  it("rejects empty encrypted_wallet_key_for_owner", () => {
    const payload = {
      format_version: "1",
      wallet: { name: "Test", tags: [] },
      secrets: [],
      encrypted_wallet_key_for_owner: "",
    };
    expect(WalletImportRequestSchema.safeParse(payload).success).toBe(false);
  });

  it("rejects duplicate secret names", () => {
    const payload = {
      format_version: "1",
      wallet: { name: "Test", tags: [] },
      secrets: [
        { name: "DUPE", is_placeholder: true, tags: [], generation_version: 1 },
        { name: "DUPE", is_placeholder: true, tags: [], generation_version: 1 },
      ],
      encrypted_wallet_key_for_owner: "validkey==",
    };
    const result = WalletImportRequestSchema.safeParse(payload);
    expect(result.success).toBe(false);
  });
});

// ─── Tests WalletImportPage ───────────────────────────────────────────────────

describe("WalletImportPage", () => {
  beforeEach(() => {
    setupCryptoMock(true);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows file input and title", () => {
    render(<WalletImportPage />, { wrapper: ImportWrapper });
    expect(screen.getByText("Import a vault")).toBeInTheDocument();
    expect(screen.getByText("Export JSON file")).toBeInTheDocument();
  });

  it("shows error on invalid JSON", async () => {
    render(<WalletImportPage />, { wrapper: ImportWrapper });

    const file = new File(["not-json-at-all"], "bad.json", {
      type: "application/json",
    });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Invalid JSON file")).toBeInTheDocument();
    });
  });

  it("shows error on invalid export format (wrong format_version)", async () => {
    render(<WalletImportPage />, { wrapper: ImportWrapper });

    const file = makeJsonFile({
      format_version: "2",
      wallet: { name: "test", tags: [] },
      secrets: [],
    });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/Invalid export format/)).toBeInTheDocument();
    });
  });

  it("shows preview with wallet name and secrets after valid file", async () => {
    render(<WalletImportPage />, { wrapper: ImportWrapper });

    const file = makeJsonFile(VALID_EXPORT);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("My Test Wallet")).toBeInTheDocument();
    });

    expect(screen.getByText("API_KEY")).toBeInTheDocument();
    expect(screen.getByText("DB_PASSWORD")).toBeInTheDocument();
    expect(screen.getByText("Confirm import")).toBeInTheDocument();
  });

  it("shows preview with description when present", async () => {
    render(<WalletImportPage />, { wrapper: ImportWrapper });

    const file = makeJsonFile(VALID_EXPORT);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("A test wallet")).toBeInTheDocument();
    });
  });

  it("calls importWallet and navigates on confirm", async () => {
    mockImportWallet.mockResolvedValue({
      wallet_id: "new-wallet-uuid",
      secrets_created: 2,
      skipped: [],
    });

    render(<WalletImportPage />, { wrapper: ImportWrapper });

    const file = makeJsonFile(VALID_EXPORT);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Confirm import")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Confirm import"));

    await waitFor(() => {
      expect(mockImportWallet).toHaveBeenCalledOnce();
      const call = mockImportWallet.mock.calls[0]?.[0];
      expect(call?.format_version).toBe("1");
      expect(call?.wallet.name).toBe("My Test Wallet");
      expect(call?.secrets).toHaveLength(2);
      expect(call?.encrypted_wallet_key_for_owner).toBeTruthy();
    });

    await waitFor(() => {
      expect(screen.getByTestId("wallet-detail")).toBeInTheDocument();
    });
  });

  it("shows error notification when importWallet fails", async () => {
    const { ApiError } = await import("@/lib/api-client");
    mockImportWallet.mockRejectedValue(
      new ApiError(422, "validation_error", "Duplicate wallet name"),
    );

    render(<WalletImportPage />, { wrapper: ImportWrapper });

    const file = makeJsonFile(VALID_EXPORT);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Confirm import")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Confirm import"));

    await waitFor(() => {
      expect(screen.getByText("Duplicate wallet name")).toBeInTheDocument();
    });
  });
});

// ─── Tests export button (WalletDetailPage) ───────────────────────────────────

describe("WalletDetailPage export", () => {
  beforeEach(() => {
    setupCryptoMock(true);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("export button triggers blob download and revokes URL", async () => {
    const { api } = await import("@/lib/api-client");
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === "/wallets/wallet-1") {
        return Promise.resolve({
          id: "00000000-0000-0000-0000-000000000001",
          name: "Test Wallet",
          description: null,
          tags: [],
          owner_user_id: "00000000-0000-0000-0000-000000000002",
          is_owner: true,
          my_permissions: 63,
          valued_secrets_count: 0,
          placeholder_secrets_count: 0,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      if (path === "/wallets/wallet-1/secrets") {
        return Promise.resolve({ secrets: [], next_cursor: null });
      }
      return Promise.resolve({});
    });

    mockExportWallet.mockResolvedValue({
      format_version: "1",
      wallet: { name: "Test Wallet", description: null, tags: [] },
      secrets: [],
    });

    const createObjectURL = vi.fn().mockReturnValue("blob:fake-url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

    // Mock anchor click
    const mockClick = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(
      (tag: string, options?: ElementCreationOptions) => {
        if (tag === "a") {
          const el = originalCreateElement("a", options);
          el.click = mockClick;
          return el;
        }
        return originalCreateElement(tag, options);
      },
    );

    render(<WalletDetailPage />, { wrapper: WalletDetailWrapper });

    await waitFor(() => {
      expect(screen.getByText("Test Wallet")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Export"));

    await waitFor(() => {
      expect(mockExportWallet).toHaveBeenCalledWith("wallet-1");
      expect(createObjectURL).toHaveBeenCalledOnce();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");
    });
  });
});
