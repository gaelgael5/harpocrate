/**
 * Helper WebSocket pour SSHTerminal — encode/parse les messages, résout l'URL WS.
 * Pas de logique de UI ici, juste de la sérialisation.
 */

export type SshOpenArgs =
  | {
      host: string;
      port: number;
      username: string;
      authType: "password";
      password: string;
    }
  | {
      host: string;
      port: number;
      username: string;
      authType: "privkey";
      privateKey: string;
      passphrase?: string;
    };

export function encodeOpen(args: SshOpenArgs): string {
  const base = {
    type: "open",
    host: args.host,
    port: args.port,
    username: args.username,
  };
  if (args.authType === "password") {
    return JSON.stringify({
      ...base,
      auth_type: "password",
      password: args.password,
    });
  }
  return JSON.stringify({
    ...base,
    auth_type: "privkey",
    private_key: args.privateKey,
    passphrase: args.passphrase ?? "",
  });
}

export function encodeData(text: string): string {
  // btoa attend une chaîne latin-1 ; pour de l'UTF-8 robuste on passe par TextEncoder
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) {
    const byte = bytes[i];
    if (byte === undefined) continue;
    bin += String.fromCharCode(byte);
  }
  return JSON.stringify({ type: "data", payload: btoa(bin) });
}

export function encodeResize(cols: number, rows: number): string {
  return JSON.stringify({ type: "resize", cols, rows });
}

export function encodeClose(): string {
  return JSON.stringify({ type: "close" });
}

export type ServerMessage =
  | { type: "ready" }
  | { type: "data"; data: Uint8Array }
  | { type: "error"; errorCode: string; message?: string };

/**
 * Parse un message du backend SSH bridge.
 * Renvoie `null` si l'entrée n'est pas du JSON valide OU si la forme du
 * message ne correspond à aucun type connu (frame `data` sans payload, etc.).
 * Le caller doit traiter `null` comme un frame à ignorer.
 */
export function parseServerMessage(raw: string): ServerMessage | null {
  let m: { type?: string; payload?: string; code?: string; message?: string };
  try {
    m = JSON.parse(raw) as typeof m;
  } catch {
    return null;
  }
  if (m.type === "ready") return { type: "ready" };
  if (m.type === "data") {
    if (typeof m.payload !== "string") return null;
    const bin = atob(m.payload);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return { type: "data", data: out };
  }
  if (m.type === "error") {
    return {
      type: "error",
      errorCode: m.code ?? "unknown",
      message: m.message,
    };
  }
  return null;
}

/**
 * Construit l'URL WebSocket vers /v1/admin/ssh-terminal/ws avec le JWT
 * passé en query string (Authorization header n'est pas disponible en WS).
 *
 * **Ne JAMAIS logger l'URL retournée** : elle contient le JWT en clair.
 */
export function buildWsUrl(jwt: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/v1/admin/ssh-terminal/ws?token=${encodeURIComponent(jwt)}`;
}
