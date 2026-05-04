/**
 * Zod schemas for /v1/wallets/{id}/export and /v1/wallets/import endpoints.
 * Mirror of backend app/models/api/exports.py — LOT_07.
 */
import { z } from 'zod'

const SECRET_NAME_RE = /^[A-Za-z0-9_.-]+$/

// ─── Sous-modèles ─────────────────────────────────────────────────────────────

export const ExportedWalletSchema = z.object({
  name: z.string().min(1),
  description: z.string().nullable().optional(),
  tags: z.array(z.string()).default([]),
})

/**
 * GenerationDescriptor is a discriminated union — we accept it as an unknown
 * object here since the frontend only displays it, never re-validates internals.
 */
export const ExportedSecretSchema = z.object({
  name: z
    .string()
    .min(1, 'Secret name must not be empty')
    .max(256, 'Secret name exceeds 256 characters')
    .regex(SECRET_NAME_RE, 'Secret name must match ^[A-Za-z0-9_.-]+'),
  description: z.string().nullable().optional(),
  tags: z.array(z.string()).default([]),
  is_placeholder: z.boolean().default(true),
  generation_descriptor: z.record(z.unknown()).nullable().optional(),
  generation_version: z.number().int().default(1),
  linked_secret_name: z.string().nullable().optional(),
})

// ─── Format d'export complet (réponse GET) ────────────────────────────────────

export const WalletExportSchema = z
  .object({
    format_version: z.literal('1'),
    exported_at: z.string().nullable().optional(),
    exported_from: z.string().nullable().optional(),
    wallet: ExportedWalletSchema,
    secrets: z.array(ExportedSecretSchema),
  })
  .superRefine((data, ctx) => {
    // Noms uniques
    const names = data.secrets.map((s) => s.name)
    const uniqueNames = new Set(names)
    if (names.length !== uniqueNames.size) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Duplicate secret names in export',
        path: ['secrets'],
      })
    }
    // linked_secret_name valide
    for (const s of data.secrets) {
      if (s.linked_secret_name && !uniqueNames.has(s.linked_secret_name)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `linked_secret_name '${s.linked_secret_name}' not found in secrets list`,
          path: ['secrets'],
        })
      }
    }
  })

// ─── Requête d'import (POST body) ─────────────────────────────────────────────

export const WalletImportRequestSchema = z
  .object({
    format_version: z.literal('1'),
    wallet: ExportedWalletSchema,
    secrets: z.array(ExportedSecretSchema).default([]),
    encrypted_wallet_key_for_owner: z
      .string()
      .min(1, 'encrypted_wallet_key_for_owner must not be empty'),
  })
  .superRefine((data, ctx) => {
    const names = data.secrets.map((s) => s.name)
    const uniqueNames = new Set(names)
    if (names.length !== uniqueNames.size) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Duplicate secret names in import payload',
        path: ['secrets'],
      })
    }
    for (const s of data.secrets) {
      if (s.linked_secret_name && !uniqueNames.has(s.linked_secret_name)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `linked_secret_name '${s.linked_secret_name}' not found in secrets list`,
          path: ['secrets'],
        })
      }
    }
  })

// ─── Réponse d'import ─────────────────────────────────────────────────────────

export const WalletImportResponseSchema = z.object({
  wallet_id: z.string(),
  secrets_created: z.number().int(),
  skipped: z.array(z.string()).default([]),
})

// ─── Types exportés ───────────────────────────────────────────────────────────

export type ExportedWallet = z.infer<typeof ExportedWalletSchema>
export type ExportedSecret = z.infer<typeof ExportedSecretSchema>
export type WalletExport = z.infer<typeof WalletExportSchema>
export type WalletImportRequest = z.infer<typeof WalletImportRequestSchema>
export type WalletImportResponse = z.infer<typeof WalletImportResponseSchema>
