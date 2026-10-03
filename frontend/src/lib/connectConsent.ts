/**
 * Règles de l'écran de consentement (feature 3, décision D3) : l'utilisateur ne peut que
 * RÉDUIRE ce que l'application demande, et jamais dépasser ses propres droits sur le
 * wallet. Le serveur applique les mêmes bornes ; ici, elles empêchent de proposer
 * l'impossible.
 */
import { PERM_ALL } from "@/schemas/grants";

export const NEW_WALLET = "__new__";
export const WALLET_NAME_MAX = 255;
export const TTL_DAYS_MAX = 3650;

/** Bits accordables : demandés ∩ droits sur le wallet (tous pour un wallet créé). */
export function grantablePermissions(
  requested: number,
  walletPermissions: number | null,
): number {
  return requested & (walletPermissions ?? PERM_ALL);
}

/** Durée maximale acceptable : celle demandée, ou la borne générale si aucune. */
export function maxTtlDays(requestedTtlDays: number | null): number {
  return requestedTtlDays ?? TTL_DAYS_MAX;
}

/** Une durée vide n'est admise que si la demande est sans expiration. */
export function isTtlAllowed(
  ttlDays: number | null,
  requestedTtlDays: number | null,
): boolean {
  if (ttlDays === null) return requestedTtlDays === null;
  return (
    Number.isInteger(ttlDays) &&
    ttlDays >= 1 &&
    ttlDays <= maxTtlDays(requestedTtlDays)
  );
}
