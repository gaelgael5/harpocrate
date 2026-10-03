/**
 * Registre des applications autorisées à demander une connexion (feature 1).
 *
 * Le validateur d'URL de retour reproduit les règles du backend
 * (`app/services/connect_clients.py::validate_redirect_uri`) pour signaler l'erreur
 * avant l'envoi. C'est un confort de saisie : le backend reste l'autorité et
 * rejette de toute façon une URL non conforme (422).
 */
import { z } from "zod";

export const ConnectClientSchema = z.object({
  id: z.string().uuid(),
  client_id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  redirect_uris: z.array(z.string()),
  active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ConnectClient = z.infer<typeof ConnectClientSchema>;

export const ConnectClientListSchema = z.object({
  items: z.array(ConnectClientSchema),
});
export type ConnectClientList = z.infer<typeof ConnectClientListSchema>;

export interface ConnectClientCreateBody {
  client_id: string;
  name: string;
  description: string | null;
  redirect_uris: string[];
}

export interface ConnectClientUpdateBody {
  name?: string;
  description?: string | null;
  redirect_uris?: string[];
  active?: boolean;
}

export const CLIENT_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{2,63}$/;
export const MAX_REDIRECT_URIS = 10;
const MAX_REDIRECT_URI_LENGTH = 2048;
// HTTP en clair seulement vers le poste local (application en développement).
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** Motif de refus d'une URL de retour (clé i18n `admin.connectClients.errors.*`), ou null. */
export type RedirectUriProblem =
  | "empty"
  | "wildcard"
  | "notAbsoluteHttp"
  | "credentials"
  | "fragment"
  | "httpNotLocal";

export function redirectUriProblem(uri: string): RedirectUriProblem | null {
  if (!uri || uri.length > MAX_REDIRECT_URI_LENGTH) return "empty";
  if (uri.includes("*") || /\s/.test(uri)) return "wildcard";
  let url: URL;
  try {
    url = new URL(uri);
  } catch {
    return "notAbsoluteHttp";
  }
  if (
    (url.protocol !== "https:" && url.protocol !== "http:") ||
    !url.hostname
  ) {
    return "notAbsoluteHttp";
  }
  if (url.username || url.password) return "credentials";
  if (uri.includes("#")) return "fragment";
  if (url.protocol === "http:" && !LOCAL_HOSTS.has(url.hostname))
    return "httpNotLocal";
  return null;
}

/** Une URL par ligne : rogne, ignore les lignes vides, retire les doublons (ordre conservé). */
export function parseRedirectUris(text: string): string[] {
  const seen = new Set<string>();
  for (const line of text.split("\n")) {
    const uri = line.trim();
    if (uri) seen.add(uri);
  }
  return [...seen];
}
