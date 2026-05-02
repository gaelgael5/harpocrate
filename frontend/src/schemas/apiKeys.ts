/**
 * Zod schemas for /v1/wallets/{id}/api-keys/* endpoints.
 * Mirror of backend app/models/api/api_keys.py — LOT_08.
 */
import { z } from 'zod'

// ─── Requêtes ─────────────────────────────────────────────────────────────────

export const ApiKeyCreateRequestSchema = z.object({
  name: z.string().min(1).max(256),
  description: z.string().max(1000).nullable().optional(),
  permissions: z.number().int().min(1).max(63),
  expires_at: z.string().datetime({ offset: true }).nullable().optional(),

  // Argon2id — auth_secret envoyé une seule fois pour le HMAC, jamais stocké
  auth_secret: z.string().min(1),
  auth_hash: z.string().min(1),
  auth_salt: z.string().min(1),
  auth_kdf_memory_kb: z.number().int().min(65536),
  auth_kdf_iterations: z.number().int().min(3),
  auth_kdf_parallelism: z.number().int().min(4),

  // Blobs chiffrés
  encrypted_wallet_key: z.string().min(1),
  encrypted_decryption_key_for_owner: z.string().min(1),
  decryption_key: z.string().min(1),
})

export const ApiKeyPatchRequestSchema = z.object({
  name: z.string().min(1).max(256).nullable().optional(),
  description: z.string().max(1000).nullable().optional(),
})

// ─── Réponses ─────────────────────────────────────────────────────────────────

export const ApiKeyCreateResponseSchema = z.object({
  api_key_id: z.string().uuid(),
  token: z.string().min(1),
})

export const ApiKeyItemSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  owner_user_id: z.string().uuid(),
  permissions: z.number().int(),
  expires_at: z.string().datetime({ offset: true }).nullable(),
  revoked_at: z.string().datetime({ offset: true }).nullable(),
  last_used_at: z.string().datetime({ offset: true }).nullable(),
  created_at: z.string().datetime({ offset: true }),
})

export const ApiKeyListResponseSchema = z.object({
  api_keys: z.array(ApiKeyItemSchema),
})

// ─── Types exportés ───────────────────────────────────────────────────────────

export type ApiKeyCreateRequest = z.infer<typeof ApiKeyCreateRequestSchema>
export type ApiKeyPatchRequest = z.infer<typeof ApiKeyPatchRequestSchema>
export type ApiKeyCreateResponse = z.infer<typeof ApiKeyCreateResponseSchema>
export type ApiKeyItem = z.infer<typeof ApiKeyItemSchema>
export type ApiKeyListResponse = z.infer<typeof ApiKeyListResponseSchema>

// ─── Utilitaires permissions ──────────────────────────────────────────────────

/** Noms des bits de permissions dans l'ordre croissant. */
export const PERMISSION_NAMES = ['read', 'add', 'init', 'write', 'remove', 'share'] as const
export type PermissionName = (typeof PERMISSION_NAMES)[number]

/** Décode un bitmap de permissions en tableau de noms. */
export function permissionsToBadges(perms: number): PermissionName[] {
  return PERMISSION_NAMES.filter((_, i) => (perms & (1 << i)) !== 0)
}
