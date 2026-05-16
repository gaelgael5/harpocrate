import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchInstallMode } from "@/lib/installMode";

describe("fetchInstallMode", () => {
  afterEach(() => vi.restoreAllMocks());

  it("retourne le mode parsé", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({
        mode: "docker_compose_auto",
        docker_socket_accessible: true,
        pg_container_data_host_path: null,
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    const m = await fetchInstallMode();
    expect(m.mode).toBe("docker_compose_auto");
  });
});
