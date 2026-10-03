/**
 * Reprise de la demande « Se connecter avec Harpocrate » après Keycloak et le
 * déverrouillage (feature 2).
 *
 * La page /connect mémorise la demande en cours dans sessionStorage ; le retour de
 * Keycloak (`/oauth-callback`), le premier login et le déverrouillage y ramènent au lieu
 * de `/`. Seul un chemin RECONSTRUIT à partir de paramètres validés est mémorisé, et seul
 * un chemin `/connect?…` est rendu : aucune valeur lue ici ne peut servir de redirection
 * ouverte.
 */

const STORAGE_KEY = "harpocrate.connect.resume";
const CLIENT_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{2,63}$/;
const REQUEST_URI_PATTERN =
  /^urn:ietf:params:oauth:request_uri:[A-Za-z0-9_-]{43}$/;

export interface ConnectParams {
  clientId: string;
  requestUri: string;
}

/** Paramètres de /connect, ou null s'ils sont absents ou mal formés. */
export function parseConnectParams(
  search: URLSearchParams,
): ConnectParams | null {
  const clientId = search.get("client_id");
  const requestUri = search.get("request_uri");
  if (!clientId || !requestUri) return null;
  if (!CLIENT_ID_PATTERN.test(clientId)) return null;
  if (!REQUEST_URI_PATTERN.test(requestUri)) return null;
  return { clientId, requestUri };
}

export function connectPath(params: ConnectParams): string {
  const query = new URLSearchParams({
    client_id: params.clientId,
    request_uri: params.requestUri,
  });
  return `/connect?${query.toString()}`;
}

export function saveConnectResume(params: ConnectParams): void {
  sessionStorage.setItem(STORAGE_KEY, connectPath(params));
}

/** Chemin de reprise, revalidé à la lecture (le stockage a pu être modifié). */
export function peekConnectResume(): string | null {
  const stored = sessionStorage.getItem(STORAGE_KEY);
  if (!stored?.startsWith("/connect?")) return null;
  const params = parseConnectParams(
    new URLSearchParams(stored.slice("/connect?".length)),
  );
  return params ? connectPath(params) : null;
}

export function clearConnectResume(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
