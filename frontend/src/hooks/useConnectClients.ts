/**
 * Hooks TanStack Query du registre des applications — /v1/admin/connect-clients (feature 1).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createConnectClient,
  fetchConnectClients,
  updateConnectClient,
} from "@/lib/connectClientsApi";
import type {
  ConnectClient,
  ConnectClientCreateBody,
  ConnectClientList,
  ConnectClientUpdateBody,
} from "@/schemas/connectClients";

export const CONNECT_CLIENTS_QUERY_KEY = ["admin-connect-clients"] as const;

export function useConnectClients() {
  return useQuery<ConnectClientList>({
    queryKey: CONNECT_CLIENTS_QUERY_KEY,
    queryFn: fetchConnectClients,
  });
}

export function useCreateConnectClient() {
  const queryClient = useQueryClient();
  return useMutation<ConnectClient, Error, ConnectClientCreateBody>({
    mutationFn: createConnectClient,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: CONNECT_CLIENTS_QUERY_KEY,
      });
    },
  });
}

export function useUpdateConnectClient() {
  const queryClient = useQueryClient();
  return useMutation<
    ConnectClient,
    Error,
    { id: string; body: ConnectClientUpdateBody }
  >({
    mutationFn: ({ id, body }) => updateConnectClient(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: CONNECT_CLIENTS_QUERY_KEY,
      });
    },
  });
}
