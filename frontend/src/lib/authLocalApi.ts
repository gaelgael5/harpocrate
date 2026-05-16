/**
 * Client typé pour les endpoints d'authentification locale.
 *
 * Utilise fetch directement (sans token OIDC) car ces endpoints sont publics.
 */

export interface LocalLoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthModesResponse {
  oidc: boolean;
  local_login: boolean;
  dev_mode?: boolean;
  dev_mode_label?: string;
}

export class LocalAuthError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "LocalAuthError";
  }

  get isInvalidCredentials(): boolean {
    return this.status === 401;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

async function _parseError(response: Response): Promise<LocalAuthError> {
  let code = "error";
  let message = response.statusText;
  try {
    const json = (await response.json()) as Record<string, unknown>;
    code = (json["error"] as string | undefined) ?? code;
    message = (json["message"] as string | undefined) ?? message;
  } catch {
    // ignore parse errors
  }
  return new LocalAuthError(response.status, code, message);
}

/**
 * Interroge GET /v1/config/auth-modes pour connaître les modes disponibles.
 * Ne lève pas d'erreur — retourne null si l'appel échoue.
 */
export async function fetchAuthModes(): Promise<AuthModesResponse | null> {
  try {
    const response = await fetch("/v1/config/auth-modes", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    return (await response.json()) as AuthModesResponse;
  } catch {
    return null;
  }
}

/**
 * POST /v1/auth/local-login — retourne le token ou lève LocalAuthError.
 */
export async function localLogin(
  username: string,
  password: string,
): Promise<LocalLoginResponse> {
  const response = await fetch("/v1/auth/local-login", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    throw await _parseError(response);
  }

  return (await response.json()) as LocalLoginResponse;
}
