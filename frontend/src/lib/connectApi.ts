/**
 * Client API du flux « Se connecter avec Harpocrate » — /v1/connect/* (features 2 à 4).
 */
import { api } from "@/lib/api-client";
import type { ConnectParams } from "@/lib/connectResume";
import type { ApiKeyMaterialBody } from "@/crypto/api-key-material";
import {
  ConnectApiKeyResponseSchema,
  ConnectRedirectSchema,
  ConnectRequestViewSchema,
  type ConnectApiKeyResponse,
  type ConnectRequestView,
} from "@/schemas/connectFlow";
import { WalletListResponseSchema, type WalletItem } from "@/schemas/wallets";

function requestPath(params: ConnectParams, action = ""): string {
  const query = new URLSearchParams({ client_id: params.clientId });
  const ref = encodeURIComponent(params.requestUri);
  return `/connect/requests/${ref}${action}?${query.toString()}`;
}

export async function fetchConnectRequest(
  params: ConnectParams,
): Promise<ConnectRequestView> {
  return ConnectRequestViewSchema.parse(
    await api.get<unknown>(requestPath(params)),
  );
}

export async function denyConnectRequest(
  params: ConnectParams,
): Promise<string> {
  return ConnectRedirectSchema.parse(
    await api.post<unknown>(requestPath(params, "/deny"), {}),
  ).redirect_to;
}

/** Création de la clé SANS dkey : le corps ne contient que le matériel chiffré (D4). */
export async function createConnectApiKey(
  params: ConnectParams,
  body: ApiKeyMaterialBody & {
    wallet_id: string;
    permissions: number;
    ttl_days: number | null;
  },
): Promise<ConnectApiKeyResponse> {
  return ConnectApiKeyResponseSchema.parse(
    await api.post<unknown>(requestPath(params, "/api-key"), body),
  );
}

export async function sealConnectRequest(
  params: ConnectParams,
  jwe: string,
): Promise<string> {
  return ConnectRedirectSchema.parse(
    await api.post<unknown>(requestPath(params, "/sealed"), { jwe }),
  ).redirect_to;
}

/** Tous les wallets actifs de l'utilisateur (pages de 200, jusqu'au bout). */
export async function fetchAllWallets(): Promise<WalletItem[]> {
  const wallets: WalletItem[] = [];
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ limit: "200" });
    if (cursor) query.set("cursor", cursor);
    const page = WalletListResponseSchema.parse(
      await api.get<unknown>(`/wallets?${query.toString()}`),
    );
    wallets.push(...page.wallets);
    cursor = page.next_cursor;
  } while (cursor);
  return wallets;
}
