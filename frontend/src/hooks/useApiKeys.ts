/**
 * TanStack Query hooks for /v1/wallets/{id}/api-keys/* — LOT_08.
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchApiKeys, createApiKey, revokeApiKey } from "@/lib/apiKeysApi";
import type {
  ApiKeyCreateRequest,
  ApiKeyCreateResponse,
  ApiKeyListResponse,
} from "@/schemas/apiKeys";

/** Clé de query pour la liste des API keys d'un wallet. */
export function apiKeysQueryKey(walletId: string) {
  return ["api-keys", walletId] as const;
}

/** Hook de listage : GET /v1/wallets/{id}/api-keys. */
export function useApiKeysList(walletId: string | undefined) {
  return useQuery<ApiKeyListResponse>({
    queryKey: apiKeysQueryKey(walletId ?? ""),
    queryFn: () => fetchApiKeys(walletId ?? ""),
    enabled: !!walletId,
  });
}

/** Hook de création : POST /v1/wallets/{id}/api-keys. */
export function useCreateApiKey(walletId: string) {
  const queryClient = useQueryClient();

  return useMutation<ApiKeyCreateResponse, Error, ApiKeyCreateRequest>({
    mutationFn: (body) => createApiKey(walletId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: apiKeysQueryKey(walletId),
      });
    },
  });
}

/** Hook de révocation : DELETE /v1/wallets/{id}/api-keys/{key_id}. */
export function useRevokeApiKey(walletId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: (apiKeyId) => revokeApiKey(walletId, apiKeyId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: apiKeysQueryKey(walletId),
      });
    },
  });
}
