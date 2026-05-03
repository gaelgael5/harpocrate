import { z } from 'zod'

export const MaintenanceStatusSchema = z.object({
  active: z.boolean(),
  reason: z.string().nullable(),
  started_at: z.string().nullable(),
  effective_at: z.string().nullable(),
  estimated_end_at: z.string().nullable(),
})

export type MaintenanceStatus = z.infer<typeof MaintenanceStatusSchema>

export const BackupSchema = z.object({
  id: z.string().uuid(),
  filename: z.string(),
  size_bytes: z.number(),
  checksum_sha256: z.string(),
  description: z.string().nullable(),
  created_at: z.string(),
  created_by_user_id: z.string().uuid().nullable(),
  imported: z.boolean(),
  manifest: z.unknown().nullable(),
})

export type Backup = z.infer<typeof BackupSchema>

export const BackupListResponseSchema = z.object({
  backups: z.array(BackupSchema),
})

export type BackupListResponse = z.infer<typeof BackupListResponseSchema>

export const RestoreResultSchema = z.object({
  success: z.boolean(),
  restored_from_backup_id: z.string().uuid(),
  session_epoch_new: z.number(),
  env_restore_file_path: z.string(),
  next_actions: z.array(z.string()),
})

export type RestoreResult = z.infer<typeof RestoreResultSchema>
