/**
 * OIDC configuration and UserManager setup via oidc-client-ts.
 *
 * Configured dynamically from /v1/config/keycloak so the frontend
 * doesn't hard-code Keycloak URLs.
 *
 * Token provider priority:
 *  1. OIDC session (Keycloak)
 *  2. Local admin token stored in session store
 */
import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import type { KeycloakConfig } from "@/schemas/auth";
import { setTokenProvider } from "./api-client";
import { useSessionStore } from "@/stores/session";

let _userManager: UserManager | null = null;

/**
 * Initialize the UserManager from Keycloak config fetched from backend.
 * Must be called once at app startup.
 */
export function initOidc(config: KeycloakConfig): UserManager {
  const redirectUri = `${window.location.origin}/oauth-callback`;
  const silentRedirectUri = `${window.location.origin}/silent-renew.html`;

  _userManager = new UserManager({
    authority: config.issuer,
    client_id: config.client_id,
    redirect_uri: redirectUri,
    silent_redirect_uri: silentRedirectUri,
    scope: "openid email profile",
    response_type: "code",
    automaticSilentRenew: true,
    userStore: new WebStorageStateStore({ store: sessionStorage }),
    // Silent renew uses a hidden iframe; no popup
    silentRequestTimeoutInSeconds: 10,
  });

  // Wire the token provider so api-client can attach Bearer headers.
  // OIDC token takes priority; local admin token is the fallback.
  setTokenProvider(async () => {
    if (_userManager) {
      const user = await _userManager.getUser();
      if (user?.access_token && !user.expired) {
        return user.access_token;
      }
    }
    return useSessionStore.getState().localAdminToken;
  });

  return _userManager;
}

export function getUserManager(): UserManager {
  if (!_userManager) {
    throw new Error("OIDC not initialized — call initOidc() first");
  }
  return _userManager;
}

/** Redirect to Keycloak login page */
export async function startLogin(): Promise<void> {
  const mgr = getUserManager();
  await mgr.signinRedirect();
}

/** Process the OIDC redirect callback */
export async function handleCallback(): Promise<void> {
  const mgr = getUserManager();
  await mgr.signinRedirectCallback();
}

/** Get current access token, if any */
export async function getAccessToken(): Promise<string | null> {
  if (!_userManager) return null;
  const user = await _userManager.getUser();
  return user?.access_token ?? null;
}

/** Log out — clears OIDC session */
export async function logout(): Promise<void> {
  if (!_userManager) return;
  await _userManager.removeUser();
}
