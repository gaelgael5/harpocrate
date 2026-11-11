/**
 * Hooks TanStack Query des cultures — /v1/admin/cultures (feature 1).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCultures, updateCulture } from "@/lib/culturesApi";
import type {
  Culture,
  CultureList,
  CultureUpdateBody,
} from "@/schemas/cultures";

export const CULTURES_QUERY_KEY = ["admin-cultures"] as const;

export function useCultures() {
  return useQuery<CultureList>({
    queryKey: CULTURES_QUERY_KEY,
    queryFn: fetchCultures,
  });
}

export function useUpdateCulture() {
  const queryClient = useQueryClient();
  return useMutation<Culture, Error, { code: string; body: CultureUpdateBody }>(
    {
      mutationFn: ({ code, body }) => updateCulture(code, body),
      onSuccess: () => {
        // Désigner une culture par défaut retire le drapeau à l'ancienne :
        // toute la liste est relue, pas seulement la ligne modifiée.
        void queryClient.invalidateQueries({ queryKey: CULTURES_QUERY_KEY });
      },
    },
  );
}
