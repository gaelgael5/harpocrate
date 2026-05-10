/**
 * Hook TanStack Query — sonde GET /v1/config/auth-modes une seule fois au montage.
 *
 * Retourne { localLoginAvailable, oidcAvailable } :
 * - undefined : probe en cours
 * - true      : mode activé côté serveur
 * - false     : mode désactivé ou endpoint inaccessible
 */
import { useQuery } from '@tanstack/react-query'
import { fetchAuthModes } from '@/lib/authLocalApi'

export function useLocalLoginAvailable(): {
  localLoginAvailable: boolean | undefined
  oidcAvailable: boolean | undefined
} {
  const { data, isPending } = useQuery({
    queryKey: ['auth-modes'],
    queryFn: fetchAuthModes,
    // Probe une seule fois — pas de refetch automatique
    staleTime: Infinity,
    retry: false,
  })

  if (isPending) {
    return { localLoginAvailable: undefined, oidcAvailable: undefined }
  }
  return {
    localLoginAvailable: data?.local_login ?? false,
    oidcAvailable: data?.oidc ?? false,
  }
}
