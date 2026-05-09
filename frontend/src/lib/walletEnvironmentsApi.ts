/**
 * Client API pour /v1/me/wallet-environments (LOT_58).
 *
 * Liste / création / suppression des environnements de l'utilisateur courant.
 * Convention : "None" est un item virtuel côté UI (id=null) — non retourné
 * par l'API, le frontend l'ajoute en tête.
 */
import { z } from 'zod'

import { api } from '@/lib/api-client'

export const WalletEnvironmentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  created_at: z.string().datetime({ offset: true }),
})

export const WalletEnvironmentListResponseSchema = z.object({
  environments: z.array(WalletEnvironmentSchema),
})

export type WalletEnvironment = z.infer<typeof WalletEnvironmentSchema>

export async function fetchWalletEnvironments(): Promise<WalletEnvironment[]> {
  const raw = await api.get<unknown>('/me/wallet-environments')
  const parsed = WalletEnvironmentListResponseSchema.parse(raw)
  return parsed.environments
}

export async function createWalletEnvironment(name: string): Promise<WalletEnvironment> {
  const raw = await api.post<unknown>('/me/wallet-environments', { name })
  // Le backend retourne {id, name} — on enrichit côté client avec un
  // created_at synthétique pour matcher le schema (sera écrasé au prochain
  // refetch).
  const parsed = z
    .object({ id: z.string().uuid(), name: z.string() })
    .parse(raw)
  return {
    id: parsed.id,
    name: parsed.name,
    created_at: new Date().toISOString(),
  }
}

export async function deleteWalletEnvironment(envId: string): Promise<void> {
  await api.delete<void>(`/me/wallet-environments/${envId}`)
}
