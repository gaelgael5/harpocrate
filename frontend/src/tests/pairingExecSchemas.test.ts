import { describe, it, expect } from "vitest";
import { InstallModeResponseSchema } from "@/schemas/installMode";
import {
  StepStartedEventSchema,
  StepDoneEventSchema,
  StepErrorEventSchema,
  ExecutionCompleteEventSchema,
  parseExecEvent,
} from "@/schemas/pairingExec";

describe("install mode schema", () => {
  it("parse mode docker_compose_auto", () => {
    const r = InstallModeResponseSchema.parse({
      mode: "docker_compose_auto",
      docker_socket_accessible: true,
      pg_container_data_host_path: null,
    });
    expect(r.mode).toBe("docker_compose_auto");
  });
});

describe("pairing exec events", () => {
  it("schemas are exported", () => {
    expect(StepStartedEventSchema).toBeDefined();
    expect(StepDoneEventSchema).toBeDefined();
    expect(StepErrorEventSchema).toBeDefined();
    expect(ExecutionCompleteEventSchema).toBeDefined();
  });
  it("parse step_started", () => {
    const ev = parseExecEvent({ type: "step_started", step_idx: 0, title: "stop", command: "stop_pg_container" });
    expect(ev?.type).toBe("step_started");
  });
  it("parse step_done", () => {
    const ev = parseExecEvent({ type: "step_done", step_idx: 0, exit_code: 0, stdout: "ok", stderr: "" });
    expect(ev?.type).toBe("step_done");
  });
  it("parse step_error", () => {
    const ev = parseExecEvent({
      type: "step_error",
      step_idx: 1,
      exit_code: 2,
      stdout: "",
      stderr: "boom",
      error_type: "NonZeroExit",
    });
    expect(ev?.type).toBe("step_error");
  });
  it("returns null for unknown type", () => {
    expect(parseExecEvent({ type: "garbage" })).toBeNull();
  });
});
