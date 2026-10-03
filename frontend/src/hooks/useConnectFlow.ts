/**
 * Hooks TanStack Query du flux « Se connecter avec Harpocrate » (features 2 à 4).
 */
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  denyConnectRequest,
  fetchAllWallets,
  fetchConnectRequest,
} from "@/lib/connectApi";
import {
  approveConnectRequest,
  assertDeclaredRedirect,
} from "@/lib/connectApprove";
import type { ConnectParams } from "@/lib/connectResume";
import type {
  ConnectDecision,
  ConnectRequestView,
} from "@/schemas/connectFlow";
import { PERM_SHARE } from "@/schemas/grants";
import type { WalletItem } from "@/schemas/wallets";

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

/** Wallets proposables : actifs, et sur lesquels l'utilisateur a [share]. */
export function useShareableWallets(enabled: boolean) {
  return useQuery<WalletItem[]>({
    queryKey: ["connect-wallets"],
    queryFn: async () =>
      (await fetchAllWallets()).filter(
        (w) => !w.deleted_at && (w.my_permissions & PERM_SHARE) !== 0,
      ),
    enabled,
  });
}

export function useApproveConnect(
  params: ConnectParams | null,
  request: ConnectRequestView | undefined,
) {
  return useMutation<string, Error, ConnectDecision>({
    mutationFn: (decision) => {
      if (!params || !request) throw new Error("connect request missing");
      return approveConnectRequest(params, request, decision);
    },
  });
}

export function useDenyConnect(
  params: ConnectParams | null,
  request: ConnectRequestView | undefined,
) {
  return useMutation<string, Error, void>({
    mutationFn: async () => {
      if (!params || !request) throw new Error("connect request missing");
      return assertDeclaredRedirect(
        await denyConnectRequest(params),
        request.redirect_uri,
      );
    },
  });
}
