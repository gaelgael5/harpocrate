/**
 * API client tests — mock fetch, verify auth header, error mapping.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError, setTokenProvider } from "@/lib/api-client";

describe("api-client", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // Set a test token provider
    setTokenProvider(async () => "test-access-token");
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    // Reset token provider
    setTokenProvider(async () => null);
  });

  it("includes Authorization header when token is available", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ foo: "bar" }),
    });
    globalThis.fetch = mockFetch;

    await api.get("/test");

    expect(mockFetch).toHaveBeenCalledWith(
      "/v1/test",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer test-access-token",
        }),
      }),
    );
  });

  it("does not include Authorization header when no token", async () => {
    setTokenProvider(async () => null);

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ foo: "bar" }),
    });
    globalThis.fetch = mockFetch;

    await api.get("/test");

    const callArgs = mockFetch.mock.calls[0]?.[1] as RequestInit | undefined;
    const headers = callArgs?.headers as Record<string, string> | undefined;
    expect(headers?.["Authorization"]).toBeUndefined();
  });

  it("throws ApiError on 401", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      text: async () =>
        JSON.stringify({ error: "unauthorized", message: "Not authorized" }),
    });

    await expect(api.get("/protected")).rejects.toMatchObject({
      status: 401,
      code: "unauthorized",
    });
  });

  it("throws ApiError with first_login code on 404 first_login", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      text: async () =>
        JSON.stringify({
          error: "first_login",
          message: "User must bootstrap",
        }),
    });

    let caught: ApiError | null = null;
    try {
      await api.get("/me");
    } catch (e) {
      if (e instanceof ApiError) caught = e;
    }

    expect(caught).not.toBeNull();
    expect(caught?.isFirstLogin).toBe(true);
    expect(caught?.isNotFound).toBe(true);
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ id: "abc", name: "test" }),
    });

    const result = await api.get<{ id: string; name: string }>("/resource");
    expect(result.id).toBe("abc");
    expect(result.name).toBe("test");
  });

  it("handles 204 No Content gracefully", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      text: async () => "",
    });

    const result = await api.delete("/resource");
    expect(result).toBeUndefined();
  });
});
