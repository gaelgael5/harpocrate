import { describe, it, expect } from "vitest";
import {
  encodeOpen,
  encodeData,
  encodeResize,
  encodeClose,
  parseServerMessage,
} from "@/lib/sshTerminalSocket";

describe("sshTerminalSocket", () => {
  it("encodes open message with password", () => {
    const m = encodeOpen({
      host: "h",
      port: 22,
      username: "u",
      authType: "password",
      password: "p",
    });
    expect(JSON.parse(m)).toEqual({
      type: "open",
      host: "h",
      port: 22,
      username: "u",
      auth_type: "password",
      password: "p",
    });
  });

  it("encodes open message with private key + passphrase", () => {
    const m = encodeOpen({
      host: "h",
      port: 22,
      username: "u",
      authType: "privkey",
      privateKey: "-----BEGIN OPENSSH PRIVATE KEY-----\n...",
      passphrase: "pp",
    });
    const parsed = JSON.parse(m);
    expect(parsed.private_key).toContain("BEGIN");
    expect(parsed.passphrase).toBe("pp");
    expect(parsed.password).toBeUndefined();
  });

  it("encodes data as base64 (UTF-8 safe)", () => {
    const m = JSON.parse(encodeData("hello"));
    expect(m.type).toBe("data");
    expect(atob(m.payload)).toBe("hello");
  });

  it("encodes data with non-ASCII characters correctly", () => {
    const m = JSON.parse(encodeData("café ✓"));
    expect(m.type).toBe("data");
    // Decode base64 then re-decode UTF-8
    const bin = atob(m.payload);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    expect(new TextDecoder().decode(bytes)).toBe("café ✓");
  });

  it("encodes resize", () => {
    const m = JSON.parse(encodeResize(80, 24));
    expect(m).toEqual({ type: "resize", cols: 80, rows: 24 });
  });

  it("parses server data into Uint8Array", () => {
    const r = parseServerMessage(
      JSON.stringify({ type: "data", payload: btoa("xy") }),
    );
    expect(r).not.toBeNull();
    if (r?.type === "data") {
      expect(new TextDecoder().decode(r.data)).toBe("xy");
    }
  });

  it("parses error message", () => {
    const r = parseServerMessage(
      JSON.stringify({
        type: "error",
        code: "ssh_auth_failed",
        message: "denied",
      }),
    );
    expect(r).not.toBeNull();
    if (r?.type === "error") {
      expect(r.errorCode).toBe("ssh_auth_failed");
      expect(r.message).toBe("denied");
    }
  });

  it("encodes open with private key — no passphrase defaults to empty string", () => {
    const m = JSON.parse(
      encodeOpen({
        host: "h",
        port: 22,
        username: "u",
        authType: "privkey",
        privateKey: "KEY",
      }),
    );
    expect(m.passphrase).toBe("");
  });

  it('encodes close as {type:"close"}', () => {
    expect(JSON.parse(encodeClose())).toEqual({ type: "close" });
  });

  it("parses ready message", () => {
    const r = parseServerMessage(JSON.stringify({ type: "ready" }));
    expect(r).toEqual({ type: "ready" });
  });

  it("parses returns null on invalid JSON", () => {
    expect(parseServerMessage("not json{")).toBeNull();
  });

  it("parses returns null on data frame without payload", () => {
    const r = parseServerMessage(JSON.stringify({ type: "data" }));
    expect(r).toBeNull();
  });
});
