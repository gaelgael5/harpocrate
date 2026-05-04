/**
 * Zod schemas for /v1/audit-log/* endpoints.
 * Mirror of backend app/models/api/audit_log.py.
 */
import { z } from 'zod'

export const ActorInfoSchema = z.object({
  type: z.string(),
  id: z.string().uuid().nullable(),
  email: z.string().nullable().optional(),
  display_name: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
})

export const TargetInfoSchema = z.object({
  wallet_id: z.string().uuid().nullable().optional(),
  wallet_name: z.string().nullable().optional(),
  secret_id: z.string().uuid().nullable().optional(),
  user_id: z.string().uuid().nullable().optional(),
  api_key_id: z.string().uuid().nullable().optional(),
})

export const AuditLogItemSchema = z.object({
  id: z.number().int(),
  occurred_at: z.string().datetime({ offset: true }),
  action: z.string(),
  actor: ActorInfoSchema,
  target: TargetInfoSchema,
  metadata: z.record(z.any()).nullable(),
  success: z.boolean(),
  error_code: z.string().nullable(),
  actor_ip: z.string().nullable(),
})

export const AuditLogResponseSchema = z.object({
  events: z.array(AuditLogItemSchema),
  next_cursor: z.string().nullable(),
})

export const AuditLogActionsResponseSchema = z.object({
  actions: z.array(z.string()),
})

export type AuditLogItem = z.infer<typeof AuditLogItemSchema>
export type AuditLogResponse = z.infer<typeof AuditLogResponseSchema>