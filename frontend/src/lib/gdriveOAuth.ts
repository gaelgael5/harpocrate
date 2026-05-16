/**
 * Helper pour le flux OAuth Google Drive via popup + postMessage.
 *
 * Ouvre une popup vers l'URL d'autorisation Google, attend le callback
 * postMessage depuis la fenêtre de callback, puis récupère la session OAuth.
 */
import {
  startGDriveOAuth,
  fetchGDriveOAuthSession,
  type StartGDriveOAuthPayload,
} from "./adminApi";

// ── Erreurs typées ────────────────────────────────────────────────────────────

export class PopupBlockedError extends Error {
  constructor() {
    super("popup_blocked");
    this.name = "PopupBlockedError";
  }
}

export class OAuthAbortedError extends Error {
  constructor() {
    super("oauth_aborted");
    this.name = "OAuthAbortedError";
  }
}

export class OAuthError extends Error {
  constructor(public readonly reason: string) {
    super(reason);
    this.name = "OAuthError";
  }
}

// ── Types internes ────────────────────────────────────────────────────────────

interface GDrivePostMessage {
  type: "gdrive_oauth_done";
  state: string;
  ok: boolean;
  error?: string;
}

// ── Constantes ────────────────────────────────────────────────────────────────

const POPUP_FEATURES = "popup=1,width=520,height=720,resizable=1,scrollbars=1";
const POPUP_POLL_MS = 400;

// ── API publique ──────────────────────────────────────────────────────────────

/**
 * Lance le flux OAuth Google Drive complet :
 * 1. Obtient l'URL d'autorisation via l'API backend
 * 2. Ouvre une popup vers cette URL
 * 3. Attend le postMessage de confirmation du callback OAuth
 * 4. Récupère la session OAuth pour obtenir l'email de l'utilisateur
 *
 * @throws {PopupBlockedError} Si la popup est bloquée par le navigateur
 * @throws {OAuthAbortedError} Si l'utilisateur ferme la popup sans autoriser
 * @throws {OAuthError} Si l'autorisation échoue (accès refusé, erreur serveur…)
 */
export async function runGDriveOAuthFlow(
  params: StartGDriveOAuthPayload,
): Promise<{ state: string; user_email: string }> {
  const { auth_url, state } = await startGDriveOAuth(params);

  const popup = window.open(auth_url, "gdrive_oauth", POPUP_FEATURES);
  if (!popup) throw new PopupBlockedError();

  const message = await waitForOAuthMessage(state, popup);
  if (!message.ok) throw new OAuthError(message.error ?? "oauth_failed");

  const session = await fetchGDriveOAuthSession(state);
  if (session.status !== "authorized" || !session.result?.user_email) {
    throw new OAuthError(session.result?.error ?? "session_not_authorized");
  }

  return { state, user_email: session.result.user_email };
}

// ── Interne ───────────────────────────────────────────────────────────────────

/**
 * Attend le postMessage du callback OAuth ou le fermeture de la popup.
 *
 * Filtre strict :
 * - event.origin doit correspondre à window.location.origin
 * - event.data.type doit être 'gdrive_oauth_done'
 * - event.data.state doit correspondre à l'état attendu
 *
 * Un interval surveille popup.closed pour rejeter avec OAuthAbortedError
 * si l'utilisateur ferme la popup sans compléter le flux.
 */
function waitForOAuthMessage(
  expectedState: string,
  popup: Window,
): Promise<GDrivePostMessage> {
  return new Promise<GDrivePostMessage>((resolve, reject) => {
    const listener = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as GDrivePostMessage | undefined;
      if (!data || data.type !== "gdrive_oauth_done") return;
      if (data.state !== expectedState) return;
      cleanup();
      resolve(data);
    };

    const poll = window.setInterval(() => {
      if (popup.closed) {
        cleanup();
        reject(new OAuthAbortedError());
      }
    }, POPUP_POLL_MS);

    const cleanup = () => {
      window.removeEventListener("message", listener);
      window.clearInterval(poll);
    };

    window.addEventListener("message", listener);
  });
}
