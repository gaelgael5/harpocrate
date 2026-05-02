/**
 * Hook TanStack Query — sonde GET /v1/config/auth-modes une seule fois au montage.
 *
 * Retourne { localLoginAvailable: boolean | undefined } :
 * - undefined : probe en cours
 * - true      : local_login activé côté serveur
 * - false     : local_login désactivé ou endpoint inaccessible
 */
import { useQuery } from '@tanstack/react-query'
import { fetchAuthModes } from '@/lib/authLocalApi'

export function useLocalLoginAvailable(): { localLoginAvailable: boolean | undefined } {
  const { data, isPending } = useQuery({
    queryKey: ['auth-modes'],
    queryFn: fetchAuthModes,
    // Probe une seule fois — pas de refetch automatique
    staleTime: Infinity,
    retry: false,
  })

  if (isPending) return { localLoginAvailable: undefined }
  return { localLoginAvailable: data?.local_login ?? false }
}
