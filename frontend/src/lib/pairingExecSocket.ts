import { parseExecEvent, type ExecEvent } from "@/schemas/pairingExec";

export function buildExecWsUrl(sessionId: string, jwt: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/v1/admin/replication/pairing/${sessionId}/exec/ws?token=${encodeURIComponent(jwt)}`;
}

export function parseFrame(raw: string): ExecEvent | null {
  try {
    return parseExecEvent(JSON.parse(raw));
  } catch {
    return null;
  }
}

export type OpenDockerFrame = { type: "open_docker"; from_step_idx?: number };
export type OpenNativeFrame = {
  type: "open_native";
  username: string;
  auth_type: "password" | "privkey";
  password?: string;
  private_key?: string;
  passphrase?: string;
  from_step_idx?: number;
};
export type OpenFrame = OpenDockerFrame | OpenNativeFrame;

export function encodeOpen(frame: OpenFrame): string {
  return JSON.stringify(frame);
}
