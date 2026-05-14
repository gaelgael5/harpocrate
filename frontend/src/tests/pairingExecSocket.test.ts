import { describe, it, expect } from "vitest";
import { buildExecWsUrl, parseFrame } from "@/lib/pairingExecSocket";

describe("pairingExecSocket", () => {
  it("buildExecWsUrl insère le token et le sid", () => {
    const u = buildExecWsUrl("abc-sid", "jwt-token");
    expect(u).toMatch(/\/v1\/admin\/replication\/pairing\/abc-sid\/exec\/ws\?token=jwt-token/);
  });

  it("parseFrame renvoie un ExecEvent valide", () => {
    const ev = parseFrame(JSON.stringify({ type: "step_done", step_idx: 0, exit_code: 0, stdout: "", stderr: "" }));
    expect(ev?.type).toBe("step_done");
  });
  it("parseFrame renvoie null pour JSON invalide", () => {
    expect(parseFrame("garbage")).toBeNull();
  });
});
