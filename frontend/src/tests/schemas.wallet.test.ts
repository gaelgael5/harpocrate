/**
 * Zod schema validation tests for wallet schemas.
 */
import { describe, it, expect } from "vitest";
import {
  WalletCreateRequestSchema,
  WalletItemSchema,
  WalletListResponseSchema,
} from "@/schemas/wallets";

describe("WalletCreateRequestSchema", () => {
  const validInput = {
    name: "My wallet",
    description: "Test",
    tags: ["prod"],
    encrypted_wallet_key_for_owner: "abc123",
  };

  it("accepts valid input", () => {
    const result = WalletCreateRequestSchema.safeParse(validInput);
    expect(result.success).toBe(true);
  });

  it("rejects empty name", () => {
    const result = WalletCreateRequestSchema.safeParse({
      ...validInput,
      name: "",
    });
    expect(result.success).toBe(false);
  });

  it("rejects name longer than 255 chars", () => {
    const result = WalletCreateRequestSchema.safeParse({
      ...validInput,
      name: "a".repeat(256),
    });
    expect(result.success).toBe(false);
  });

  it("accepts name exactly 255 chars", () => {
    const result = WalletCreateRequestSchema.safeParse({
      ...validInput,
      name: "a".repeat(255),
    });
    expect(result.success).toBe(true);
  });

  it("rejects empty encrypted_wallet_key_for_owner", () => {
    const result = WalletCreateRequestSchema.safeParse({
      ...validInput,
      encrypted_wallet_key_for_owner: "",
    });
    expect(result.success).toBe(false);
  });
});

describe("WalletItemSchema", () => {
  const validItem = {
    id: "123e4567-e89b-12d3-a456-426614174000",
    name: "Test wallet",
    description: null,
    tags: ["dev"],
    owner_user_id: "123e4567-e89b-12d3-a456-426614174001",
    is_owner: true,
    my_permissions: 63,
    valued_secrets_count: 5,
    placeholder_secrets_count: 2,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  };

  it("accepts valid wallet item", () => {
    const result = WalletItemSchema.safeParse(validItem);
    expect(result.success).toBe(true);
  });

  it("rejects invalid UUID", () => {
    const result = WalletItemSchema.safeParse({
      ...validItem,
      id: "not-a-uuid",
    });
    expect(result.success).toBe(false);
  });
});

describe("WalletListResponseSchema", () => {
  it("accepts valid list response", () => {
    const result = WalletListResponseSchema.safeParse({
      wallets: [],
      next_cursor: null,
    });
    expect(result.success).toBe(true);
  });

  it("accepts list with next_cursor", () => {
    const result = WalletListResponseSchema.safeParse({
      wallets: [],
      next_cursor: "some-cursor",
    });
    expect(result.success).toBe(true);
  });
});
