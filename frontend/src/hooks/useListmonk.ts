/**
 * Hooks TanStack Query du paramétrage Listmonk — /v1/admin/listmonk (feature 2).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteListmonkTemplate,
  fetchListmonkSettings,
  saveListmonkConnection,
  setListmonkTemplate,
  testListmonkConnection,
} from "@/lib/listmonkApi";
import type {
  ConnectionTestResult,
  ListmonkConnectionBody,
  ListmonkSettings,
  ListmonkTemplate,
} from "@/schemas/listmonk";

export const LISTMONK_QUERY_KEY = ["admin-listmonk"] as const;

interface TemplateKey {
  purpose: string;
  cultureCode: string;
}

export function useListmonkSettings() {
  return useQuery<ListmonkSettings>({
    queryKey: LISTMONK_QUERY_KEY,
    queryFn: fetchListmonkSettings,
  });
}

export function useSetListmonkTemplate() {
  const queryClient = useQueryClient();
  return useMutation<
    ListmonkTemplate,
    Error,
    TemplateKey & { templateId: number }
  >({
    mutationFn: ({ purpose, cultureCode, templateId }) =>
      setListmonkTemplate(purpose, cultureCode, templateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LISTMONK_QUERY_KEY });
    },
  });
}

export function useDeleteListmonkTemplate() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, TemplateKey>({
    mutationFn: ({ purpose, cultureCode }) =>
      deleteListmonkTemplate(purpose, cultureCode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LISTMONK_QUERY_KEY });
    },
  });
}

export function useSaveListmonkConnection() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, ListmonkConnectionBody>({
    mutationFn: saveListmonkConnection,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LISTMONK_QUERY_KEY });
    },
  });
}

/** N'invalide rien : un test n'enregistre pas. */
export function useTestListmonkConnection() {
  return useMutation<ConnectionTestResult, Error, ListmonkConnectionBody>({
    mutationFn: testListmonkConnection,
  });
}
