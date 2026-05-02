/**
 * Zod schemas for /v1/wallets/{id}/grants/* endpoints.
 * Mirror of backend app/models/api/grants.py.
 */
import { z } from 'zod'

export const CreateGrantRequestSchema = z.object({
  grantee_user_id: z.string().uuid(),
  encrypted_wallet_key_for_grantee: z.string().min(1),
  permissions: z.number().int().min(1).max(63),
})

export const UpdateGrantRequestSchema = z.object({
  permissions: z.number().int().min(1).max(63),
  encrypted_wallet_key_for_grantee: z.string().min(1).nullable().optional(),
})

export const GrantItemSchema = z.object({
  id: z.string().uuid(),
  grantee_user_id: z.string().uuid(),
  grantee_email: z.string().email(),
  grantee_display_name: z.string().nullable(),
  permissions: z.number().int(),
  is_owner: z.boolean(),
  granted_by_user_id: z.string().uuid(),
  granted_at: z.string().datetime({ offset: true }),
})

export const GrantListResponseSchema = z.object({
  grants: z.array(GrantItemSchema),
})

export const GrantCreateResponseSchema = z.object({
  grant_id: z.string().uuid(),
})

export const MyGrantResponseSchema = z.object({
  id: z.string().uuid(),
  permissions: z.number().int(),
  encrypted_wallet_key: z.string(),
  is_owner: z.boolean(),
})

export type GrantItem = z.infer<typeof GrantItemSchema>
export type MyGrantResponse = z.infer<typeof MyGrantResponseSchema>

/**
 * Permission bitmask constants matching the backend.
 *
 * Bit 0 (1):  read
 * Bit 1 (2):  add
 * Bit 2 (4):  init
 * Bit 3 (8):  write
 * Bit 4 (16): remove
 * Bit 5 (32): share
 */
export const PERM_READ = 1
export const PERM_ADD = 2
export const PERM_INIT = 4
export const PERM_WRITE = 8
export const PERM_REMOVE = 16
export const PERM_SHARE = 32
export const PERM_ALL = 63

export function hasPermission(perms: number, bit: number): boolean {
  return (perms & bit) !== 0
}
