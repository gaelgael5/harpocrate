/**
 * Typed API client for /v1/wallets/{id}/api-keys/* endpoints — LOT_08.
 *
 * SÉCURITÉ : le body de création contient auth_secret et decryption_key
 * (secrets cryptographiques). Aucun log de ce body ne doit exister.
 */
import { api } from "@/lib/api-client";
import {
  ApiKeyCreateResponseSchema,
  ApiKeyListResponseSchema,
  type ApiKeyCreateRequest,
  type ApiKeyCreateResponse,
  type ApiKeyListResponse,
  type ApiKeyPatchRequest,
} from "@/schemas/apiKeys";

/** Liste les API keys d'un wallet. */
export async function fetchApiKeys(
  walletId: string,
): Promise<ApiKeyListResponse> {
  const raw = await api.get<unknown>(`/wallets/${walletId}/api-keys`);
  return ApiKeyListResponseSchema.parse(raw);
}

/**
 * Crée une API key. Retourne le token complet (one-shot).
 * Le body contient des secrets cryptographiques — ne jamais logger.
 */
export async function createApiKey(
  walletId: string,
  body: ApiKeyCreateRequest,
): Promise<ApiKeyCreateResponse> {
  const raw = await api.post<unknown>(`/wallets/${walletId}/api-keys`, body);
  return ApiKeyCreateResponseSchema.parse(raw);
}

/** Met à jour les métadonnées (name/description) d'une API key. */
export async function patchApiKey(
  walletId: string,
  apiKeyId: string,
  body: ApiKeyPatchRequest,
): Promise<void> {
  await api.patch<unknown>(`/wallets/${walletId}/api-keys/${apiKeyId}`, body);
}

/** Révoque une API key (soft delete, revoked_at = NOW()). */
export async function revokeApiKey(
  walletId: string,
  apiKeyId: string,
): Promise<void> {
  await api.delete<unknown>(`/wallets/${walletId}/api-keys/${apiKeyId}`);
}
