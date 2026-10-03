/**
 * Approbation d'une demande « Se connecter avec Harpocrate » (features 3 et 4).
 *
 * Dans le navigateur, et seulement là :
 * 1. wallet choisi (wallet key déchiffré du grant) ou créé (wallet key généré) ;
 * 2. éléments de la clé générés — la dkey reste ici ;
 * 3. création de la clé SANS dkey : le serveur signe le token avec le segment de
 *    substitution (D4) ;
 * 4. scellement {token, dkey} pour la clé publique éphémère de l'application (D5) ;
 * 5. dépôt du scellé → URL de retour avec le code à usage unique.
 */
import { generateApiKeyMaterial } from "@/crypto/api-key-material";
import { sealForApplication } from "@/crypto/jwe-seal";
import { createConnectApiKey, sealConnectRequest } from "@/lib/connectApi";
import type { ConnectParams } from "@/lib/connectResume";
import {
  CryptoLockedError,
  createWalletWithKey,
  loadWalletKey,
} from "@/lib/walletKeyAccess";
import type {
  ConnectDecision,
  ConnectRequestView,
} from "@/schemas/connectFlow";
import { useCryptoStore } from "@/stores/crypto";

export class UnexpectedRedirectError extends Error {
  constructor() {
    super("unexpected_redirect");
    this.name = "UnexpectedRedirectError";
  }
}

/**
 * Défense en profondeur : on ne quitte Harpocrate que vers l'URL de retour DÉCLARÉE de
 * la demande (le serveur la construit déjà ainsi ; une réponse altérée est refusée).
 */
export function assertDeclaredRedirect(
  redirectTo: string,
  declared: string,
): string {
  const target = new URL(redirectTo);
  const expected = new URL(declared);
  if (
    target.origin !== expected.origin ||
    target.pathname !== expected.pathname
  ) {
    throw new UnexpectedRedirectError();
  }
  return redirectTo;
}

async function resolveWallet(
  decision: ConnectDecision,
): Promise<{ walletId: string; walletKey: Uint8Array }> {
  if (decision.wallet.kind === "new") {
    return createWalletWithKey(decision.wallet.name);
  }
  const walletId = decision.wallet.walletId;
  return { walletId, walletKey: await loadWalletKey(walletId) };
}

export async function approveConnectRequest(
  params: ConnectParams,
  request: ConnectRequestView,
  decision: ConnectDecision,
): Promise<string> {
  const ownerPublicKey = useCryptoStore.getState().rsaPublicKey;
  if (!ownerPublicKey) throw new CryptoLockedError();
  const { walletId, walletKey } = await resolveWallet(decision);
  const material = await generateApiKeyMaterial(walletKey, ownerPublicKey);
  const created = await createConnectApiKey(params, {
    ...material.body,
    wallet_id: walletId,
    permissions: decision.permissions,
    ttl_days: decision.ttlDays,
  });
  const jwe = await sealForApplication(
    { token: created.token, dkey: material.decryptionKey },
    request.app_public_jwk,
  );
  const redirectTo = await sealConnectRequest(params, jwe);
  return assertDeclaredRedirect(redirectTo, request.redirect_uri);
}
