/**
 * TanStack Query hook for the cross-suite apps launcher menu.
 *
 * staleTime: 5 min — the list changes rarely; no need to hammer the backend.
 * refetchOnWindowFocus: false — avoids a spurious request every tab switch.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchApps } from "@/lib/appsApi";
import type { AppsResponse } from "@/schemas/apps";

export function useApps() {
  return useQuery<AppsResponse>({
    queryKey: ["apps"],
    queryFn: fetchApps,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
