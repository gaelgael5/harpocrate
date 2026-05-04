/**
 * Zod schemas for /v1/wallets/{id}/secrets/* endpoints.
 * Mirror of backend app/models/api/secrets.py.
 */
import { z } from 'zod'

const NAME_RE = /^[A-Za-z0-9_.-]+$/
const DESC_MAX = 1000

export const SecretCreateRequestSchema = z.object({
  name: z
    .string()
    .min(1)
    .max(256)
    .regex(NAME_RE, 'name must match ^[A-Za-z0-9_.-]+ (env-var-safe)'),
  description: z.string().max(DESC_MAX).nullable().optional(),
  tags: z.array(z.string()).default([]),
  encrypted_value: z.string().min(1),
})

export const SecretPutRequestSchema = z.object({
  encrypted_value: z.string().min(1),
})

export const SecretPatchRequestSchema = z.object({
  description: z.string().max(DESC_MAX).nullable().optional(),
  tags: z.array(z.string()).nullable().optional(),
})

const CallerRefSchema = z.object({
  type: z.string(),
  id: z.string().uuid(),
})

export const SecretListItemSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  tags: z.array(z.string()),
  is_placeholder: z.boolean(),
  generation_version: z.number().int(),
  linked_secret_id: z.string().uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  created_by: CallerRefSchema.nullable(),
  updated_by: CallerRefSchema.nullable(),
})

export const SecretListResponseSchema = z.object({
  secrets: z.array(SecretListItemSchema),
  next_cursor: z.string().nullable(),
})

export const SecretDetailResponseSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  encrypted_value: z.string(),
  encrypted_wallet_key: z.string(),
  description: z.string().nullable(),
  tags: z.array(z.string()),
  is_placeholder: z.boolean(),
  generation_version: z.number().int(),
})

export const SecretCreateResponseSchema = z.object({
  secret_id: z.string().uuid(),
})

export const PopulateRequestSchema = z.object({
  encrypted_value: z.string().min(1),
})

export const PlaceholderCreateRequestSchema = z.object({
  name: z
    .string()
    .min(1)
    .max(256)
    .regex(NAME_RE, 'name must match ^[A-Za-z0-9_.-]+'),
  description: z.string().max(DESC_MAX).nullable().optional(),
  tags: z.array(z.string()).default([]),
  generation_descriptor: z.record(z.unknown()),
  linked_secret_id: z.string().uuid().nullable().optional(),
})

export type SecretListItem = z.infer<typeof SecretListItemSchema>
export type SecretDetailResponse = z.infer<typeof SecretDetailResponseSchema>

