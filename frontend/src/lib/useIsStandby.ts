/**
 * Hook : indique si l'instance courante est asservie à un master Harpocrate.
 * Polling 60s aligné avec StandbyBanner.
 *
 * Renvoie `false` par défaut (sécurité : on ne désactive pas les actions sur
 * une simple erreur réseau). Utilisé pour griser les boutons de gestion
 * réplication quand on est en standby.
 *
 * Note : le queryKey ['standby-of'] est partagé avec StandbyBanner — les deux
 * consomment la même entrée de cache, sans double requête.
 */
import { useQuery } from "@tanstack/react-query";

import { getStandbyOf } from "./adminApi";

export function useIsStandby(): boolean {
  const q = useQuery({
    queryKey: ["standby-of"],
    queryFn: getStandbyOf,
    refetchInterval: 60_000,
    retry: false,
  });
  return q.data?.is_standby_of != null;
}
