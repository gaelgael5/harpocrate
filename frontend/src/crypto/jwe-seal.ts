/**
 * Scellement de l'API key pour l'application (feature 4, décisions D4, D5, D11).
 *
 * JWE compact ECDH-ES (accord de clé direct) sur P-256 + A256GCM, pour la clé publique
 * éphémère que l'application a déposée avec sa demande. Seule sa clé privée, restée chez
 * elle, ouvre le scellé : Harpocrate le transporte sans pouvoir le lire.
 * Bibliothèque `jose` : l'ECDH-ES impose une Concat KDF qu'on ne réécrit pas à la main.
 */
import { CompactEncrypt, importJWK } from "jose";

import type { AppPublicJwk } from "@/schemas/connectFlow";

/** Contenu scellé : le token signé (segment dkey de substitution) et la vraie dkey. */
export interface SealedApiKeyPayload {
  token: string;
  dkey: string;
}

export const SEAL_ALG = "ECDH-ES";
export const SEAL_ENC = "A256GCM";

export async function sealForApplication(
  payload: SealedApiKeyPayload,
  appPublicJwk: AppPublicJwk,
): Promise<string> {
  // Seuls les membres publics sont importés : une `d` éventuelle ne passerait de toute
  // façon pas la validation du dépôt (PAR).
  const key = await importJWK(
    {
      kty: appPublicJwk.kty,
      crv: appPublicJwk.crv,
      x: appPublicJwk.x,
      y: appPublicJwk.y,
    },
    SEAL_ALG,
  );
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  return new CompactEncrypt(plaintext)
    .setProtectedHeader({ alg: SEAL_ALG, enc: SEAL_ENC })
    .encrypt(key);
}
