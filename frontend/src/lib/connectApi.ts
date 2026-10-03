/**
 * Client API du flux « Se connecter avec Harpocrate » — /v1/connect/* (features 2 à 4).
 */
import { api } from "@/lib/api-client";
import type { ConnectParams } from "@/lib/connectResume";
import {
  ConnectRequestViewSchema,
  type ConnectRequestView,
} from "@/schemas/connectFlow";

function requestPath(params: ConnectParams): string {
  return `/connect/requests/${encodeURIComponent(params.requestUri)}`;
}

export async function fetchConnectRequest(
  params: ConnectParams,
): Promise<ConnectRequestView> {
  const query = new URLSearchParams({ client_id: params.clientId });
  return ConnectRequestViewSchema.parse(
    await api.get<unknown>(`${requestPath(params)}?${query.toString()}`),
  );
}
