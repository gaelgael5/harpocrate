/**
 * Zod schemas for /v1/me/* endpoints.
 * Mirror of backend app/models/api/auth.py.
 */
import { z } from 'zod'

export const KdfParamsSchema = z.object({
  memory_kb: z.number().int().positive(),
  iterations: z.number().int().positive(),
  parallelism: z.number().int().positive(),
})

export const MeResponseSchema = z.object({
  id: z.string().uuid(),
  keycloak_sub: z.string(),
  email: z.string().email(),
  display_name: z.string().nullable(),
  has_bootstrap: z.boolean(),
  kdf_params: KdfParamsSchema,
  rsa_key_size: z.number().int(),
  created_at: z.string().datetime({ offset: true }),
  last_unlock_at: z.string().datetime({ offset: true }).nullable(),
})

export const CryptoResponseSchema = z.object({
  salt_passphrase: z.string().min(1),
  encrypted_rsa_private_key: z.string().min(1),
  encrypted_sym_key_by_pass: z.string().min(1),
  kdf_params: KdfParamsSchema,
  rsa_public_key: z.string().min(1),
})

export const RecoveryCryptoResponseSchema = z.object({
  salt_recovery: z.string().min(1),
  encrypted_sym_key_by_recovery: z.string().min(1),
})

export const BootstrapRequestSchema = z.object({
  rsa_public_key: z.string().min(1),
  salt_passphrase: z.string().min(1),
  salt_recovery: z.string().min(1),
  encrypted_rsa_private_key: z.string().min(1),
  encrypted_sym_key_by_pass: z.string().min(1),
  encrypted_sym_key_by_recovery: z.string().min(1),
  kdf_memory_kb: z.number().int().positive(),
  kdf_iterations: z.number().int().positive(),
  kdf_parallelism: z.number().int().positive(),
  rsa_key_size: z.number().int(),
})

export const BootstrapResponseSchema = z.object({
  user_id: z.string().uuid(),
})

export const PassphraseChangeRequestSchema = z.object({
  new_salt_passphrase: z.string().min(1),
  new_encrypted_rsa_private_key: z.string().min(1),
  new_encrypted_sym_key_by_pass: z.string().min(1),
  kdf_memory_kb: z.number().int().positive(),
  kdf_iterations: z.number().int().positive(),
  kdf_parallelism: z.number().int().positive(),
})

export const RecoveryRenewRequestSchema = z.object({
  new_salt_recovery: z.string().min(1),
  new_encrypted_sym_key_by_recovery: z.string().min(1),
})

export const UpdatedAtResponseSchema = z.object({
  updated_at: z.string().datetime({ offset: true }),
})

// Keycloak config from /v1/config/keycloak
export const KeycloakConfigSchema = z.object({
  realm: z.string(),
  client_id: z.string(),
  auth_url: z.string().url(),
  token_url: z.string().url(),
  jwks_url: z.string().url(),
  issuer: z.string().url(),
})

export type MeResponse = z.infer<typeof MeResponseSchema>
export type CryptoResponse = z.infer<typeof CryptoResponseSchema>
export type KdfParams = z.infer<typeof KdfParamsSchema>
export type KeycloakConfig = z.infer<typeof KeycloakConfigSchema>
export type BootstrapRequest = z.infer<typeof BootstrapRequestSchema>
