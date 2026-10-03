/**
 * Hooks TanStack Query du flux « Se connecter avec Harpocrate » (features 2 à 4).
 */
import { useQuery } from "@tanstack/react-query";

import { fetchConnectRequest } from "@/lib/connectApi";
import type { ConnectParams } from "@/lib/connectResume";
import type { ConnectRequestView } from "@/schemas/connectFlow";

export function connectRequestQueryKey(params: ConnectParams | null) {
  return ["connect-request", params?.requestUri ?? null] as const;
}

/** Demande en cours ; `enabled` attend l'authentification et le déverrouillage. */
export function useConnectRequest(
  params: ConnectParams | null,
  enabled: boolean,
) {
  return useQuery<ConnectRequestView>({
    queryKey: connectRequestQueryKey(params),
    queryFn: () => {
      if (!params) throw new Error("connect params missing");
      return fetchConnectRequest(params);
    },
    enabled: enabled && params !== null,
    // Une erreur de demande (expirée, inconnue) est définitive : pas de nouvel essai.
    retry: false,
    staleTime: Infinity,
  });
}
