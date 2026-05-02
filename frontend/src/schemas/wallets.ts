/**
 * Zod schemas for /v1/wallets/* endpoints.
 * Mirror of backend app/models/api/wallets.py.
 */
import { z } from 'zod'

const NAME_MAX = 255
const DESC_MAX = 1000

export const WalletCreateRequestSchema = z.object({
  name: z
    .string()
    .min(1, 'Name must not be empty')
    .max(NAME_MAX, `Name must not exceed ${NAME_MAX} characters`),
  description: z
    .string()
    .max(DESC_MAX, `Description must not exceed ${DESC_MAX} characters`)
    .nullable()
    .optional(),
  tags: z.array(z.string()).default([]),
  encrypted_wallet_key_for_owner: z
    .string()
    .min(1, 'encrypted_wallet_key_for_owner must not be empty'),
})

export const WalletPatchRequestSchema = z.object({
  name: z
    .string()
    .min(1)
    .max(NAME_MAX)
    .nullable()
    .optional(),
  description: z
    .string()
    .max(DESC_MAX)
    .nullable()
    .optional(),
  tags: z.array(z.string()).nullable().optional(),
})

export const WalletDeleteRequestSchema = z.object({
  confirmation: z.string().min(1),
})

export const WalletItemSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  tags: z.array(z.string()),
  owner_user_id: z.string().uuid(),
  is_owner: z.boolean(),
  my_permissions: z.number().int(),
  valued_secrets_count: z.number().int(),
  placeholder_secrets_count: z.number().int(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})

export const WalletListResponseSchema = z.object({
  wallets: z.array(WalletItemSchema),
  next_cursor: z.string().nullable(),
})

export const WalletCreateResponseSchema = z.object({
  wallet_id: z.string().uuid(),
})

export const UserLookupResponseSchema = z.object({
  user_id: z.string().uuid(),
  email: z.string().email(),
  display_name: z.string().nullable(),
  rsa_public_key: z.string().min(1),
})

export type WalletItem = z.infer<typeof WalletItemSchema>
export type WalletListResponse = z.infer<typeof WalletListResponseSchema>
export type UserLookupResponse = z.infer<typeof UserLookupResponseSchema>
