import { describe, it, expect, vi, afterEach } from "vitest";
import { acceptPairingV2 } from "@/lib/adminApi";

describe("acceptPairingV2", () => {
  afterEach(() => vi.restoreAllMocks());

  it("envoie force=false par défaut", async () => {
    let capturedBody: unknown = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      capturedBody = JSON.parse(String((init as RequestInit).body));
      return new Response(
        JSON.stringify({
          session_id: "00000000-0000-0000-0000-000000000000",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    await acceptPairingV2("https://a/pair?sid=x&t=y");
    expect(capturedBody).toMatchObject({
      pairing_url: "https://a/pair?sid=x&t=y",
      force: false,
    });
  });

  it("envoie force=true quand demandé", async () => {
    let capturedBody: unknown = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      capturedBody = JSON.parse(String((init as RequestInit).body));
      return new Response(
        JSON.stringify({
          session_id: "00000000-0000-0000-0000-000000000000",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    await acceptPairingV2("https://a/pair?sid=x&t=y", true);
    expect(capturedBody).toMatchObject({ force: true });
  });
});
