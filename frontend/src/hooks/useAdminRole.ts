import { useQuery } from "@tanstack/react-query";
import { getAccessToken } from "@/lib/oidc";
import { useSessionStore } from "@/stores/session";

export function hasAdminRole(token: string): boolean {
  if (!token) return false;
  try {
    const parts = token.split(".");
    if (parts.length < 2) return false;
    const payload = parts[1]!;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as Record<string, unknown>;
    const realmAccess = claims["realm_access"] as
      | Record<string, unknown>
      | undefined;
    const roles = realmAccess?.["roles"];
    return Array.isArray(roles) && roles.includes("harpocrate-admin");
  } catch {
    return false;
  }
}

export function useAdminRole(): boolean {
  const localAdminToken = useSessionStore((s) => s.localAdminToken);

  const { data: oidcToken } = useQuery({
    queryKey: ["oidc-access-token"],
    queryFn: getAccessToken,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const token = oidcToken ?? localAdminToken ?? "";
  return hasAdminRole(token);
}
