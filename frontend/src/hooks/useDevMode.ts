/**
 * Hook TanStack Query — sonde GET /v1/config/auth-modes pour récupérer le flag dev_mode.
 *
 * Réutilise la même query que useLocalLoginAvailable (cache partagé via queryKey).
 */
import { useQuery } from '@tanstack/react-query'
import { fetchAuthModes } from '@/lib/authLocalApi'

export interface DevModeState {
  enabled: boolean
  label: string
}

export function useDevMode(): DevModeState {
  const { data } = useQuery({
    queryKey: ['auth-modes'],
    queryFn: fetchAuthModes,
    staleTime: Infinity,
    retry: false,
  })

  return {
    enabled: data?.dev_mode ?? false,
    label: data?.dev_mode_label ?? 'DEV',
  }
}
