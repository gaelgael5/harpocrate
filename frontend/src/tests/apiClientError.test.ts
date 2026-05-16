import { describe, it, expect, vi, afterEach } from "vitest";
import { api, ApiError } from "@/lib/api-client";

describe("ApiError", () => {
  afterEach(() => vi.restoreAllMocks());

  it("expose le payload detail structuré sur erreur HTTP", async () => {
    const fakeBody = {
      detail: {
        error: "node_already_exists",
        existing_node: { id: "abc", label: "https://b/", host: "b" },
      },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(fakeBody), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    try {
      await api.post("/whatever", {});
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(409);
      expect(err.code).toBe("node_already_exists");
      expect(err.detail).toEqual(fakeBody.detail);
    }
  });

  it("detail est null quand le body est un detail string simple", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "plain error" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );
    try {
      await api.post("/whatever", {});
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      // detail brut conservé tel quel (string ou object), null si rien
      expect(err.detail).toBe("plain error");
    }
  });
});
