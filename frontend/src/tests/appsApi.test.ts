/**
 * Tests for appsApi.ts — mock fetch, validate Zod schema applied to response.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { setTokenProvider } from "@/lib/api-client";

describe("fetchApps", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    setTokenProvider(async () => "test-token");
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    setTokenProvider(async () => null);
    vi.resetModules();
  });

  it("calls /v1/apps and returns validated entries", async () => {
    const mockPayload = {
      urls: [
        {
          key: "docker",
          label: "Docker",
          icon: "https://docker-agflow.yoops.org/favicon.ico",
          url: "https://docker-agflow.yoops.org/",
        },
      ],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(mockPayload),
    });

    const { fetchApps } = await import("@/lib/appsApi");
    const result = await fetchApps();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/v1/apps",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer test-token",
        }),
      }),
    );
    expect(result.urls).toHaveLength(1);
    expect(result.urls[0]?.key).toBe("docker");
    expect(result.urls[0]?.label).toBe("Docker");
  });

  it("returns empty urls when response has invalid entry (bad URL)", async () => {
    const mockPayload = {
      urls: [
        {
          key: "bad",
          label: "Bad",
          icon: "not-a-url",
          url: "also-not-a-url",
        },
      ],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(mockPayload),
    });

    const { fetchApps } = await import("@/lib/appsApi");
    const result = await fetchApps();

    expect(result.urls).toHaveLength(0);
  });

  it("returns empty urls when response is not an object", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify([]),
    });

    const { fetchApps } = await import("@/lib/appsApi");
    const result = await fetchApps();

    expect(result.urls).toHaveLength(0);
  });

  it("propagates ApiError on 401", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      text: async () =>
        JSON.stringify({ error: "unauthorized", message: "Not authorized" }),
    });

    const { fetchApps } = await import("@/lib/appsApi");
    await expect(fetchApps()).rejects.toMatchObject({ status: 401 });
  });
});
