/**
 * Client API du registre des applications — /v1/admin/connect-clients (feature 1).
 */
import { api } from "@/lib/api-client";
import {
  ConnectClientListSchema,
  ConnectClientSchema,
  type ConnectClient,
  type ConnectClientCreateBody,
  type ConnectClientList,
  type ConnectClientUpdateBody,
} from "@/schemas/connectClients";

const BASE = "/admin/connect-clients";

export async function fetchConnectClients(): Promise<ConnectClientList> {
  return ConnectClientListSchema.parse(await api.get<unknown>(BASE));
}

export async function createConnectClient(
  body: ConnectClientCreateBody,
): Promise<ConnectClient> {
  return ConnectClientSchema.parse(await api.post<unknown>(BASE, body));
}

export async function updateConnectClient(
  id: string,
  body: ConnectClientUpdateBody,
): Promise<ConnectClient> {
  return ConnectClientSchema.parse(
    await api.patch<unknown>(`${BASE}/${id}`, body),
  );
}
