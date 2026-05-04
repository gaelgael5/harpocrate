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

export const EnvConfigSchema = z.object({
  env: z.record(z.string()),
  sensitive_keys: z.array(z.string()),
})

export type EnvConfig = z.infer<typeof EnvConfigSchema>

export const SystemInfoSchema = z.object({
  users_count: z.number(),
  bootstrapped_users_count: z.number(),
  wallets_count: z.number(),
  secrets_count: z.number(),
  active_api_keys_count: z.number(),
  backups_count: z.number(),
  audit_events_count: z.number(),
})

export type SystemInfo = z.infer<typeof SystemInfoSchema>

export const AdminUserSchema = z.object({
  id: z.string().uuid(),
  email: z.string(),
  display_name: z.string().nullable(),
  created_at: z.string(),
  last_unlock_at: z.string().nullable(),
  has_bootstrap: z.boolean(),
  quarantine_until: z.string().nullable(),
  disabled_at: z.string().nullable(),
})

export type AdminUser = z.infer<typeof AdminUserSchema>

export const AdminUsersResponseSchema = z.object({
  users: z.array(AdminUserSchema),
  total: z.number(),
})

export type AdminUsersResponse = z.infer<typeof AdminUsersResponseSchema>

export const RestoreResultSchema = z.object({
  success: z.boolean(),
  restored_from_backup_id: z.string().uuid(),
  session_epoch_new: z.number(),
  env_restore_file_path: z.string(),
  next_actions: z.array(z.string()),
})

export type RestoreResult = z.infer<typeof RestoreResultSchema>

export const S3BackupItemSchema = z.object({
  key: z.string(),
  size_bytes: z.number(),
  last_modified: z.string(),
  etag: z.string(),
})

export type S3BackupItem = z.infer<typeof S3BackupItemSchema>

export const S3BackupListResponseSchema = z.object({
  backups: z.array(S3BackupItemSchema),
})

export type S3BackupListResponse = z.infer<typeof S3BackupListResponseSchema>

export const S3PushResultSchema = z.object({
  s3_key: z.string(),
})

export type S3PushResult = z.infer<typeof S3PushResultSchema>

export const GFSRetentionSchema = z.object({
  hourly: z.number().int().min(0),
  daily: z.number().int().min(0),
  weekly: z.number().int().min(0),
  monthly: z.number().int().min(0),
  yearly: z.number().int().min(0),
})

export type GFSRetention = z.infer<typeof GFSRetentionSchema>

export const SnapshotPolicySchema = z.object({
  interval_minutes: z.number().int().min(0),
  retention: GFSRetentionSchema,
  push_remote_after_snapshot: z.boolean(),
  remote_destinations_to_push: z.array(z.string()),
  skip_if_no_change: z.boolean(),
})

export type SnapshotPolicy = z.infer<typeof SnapshotPolicySchema>

export const SnapshotItemSchema = z.object({
  id: z.string().uuid(),
  filename: z.string(),
  size_bytes: z.number(),
  created_at: z.string(),
  tier: z.string().nullable(),
  description: z.string().nullable(),
  promoted_from_id: z.string().uuid().nullable(),
})

export type SnapshotItem = z.infer<typeof SnapshotItemSchema>

export const SnapshotHistorySchema = z.object({
  snapshots: z.array(SnapshotItemSchema),
})

export type SnapshotHistory = z.infer<typeof SnapshotHistorySchema>

export const TriggerResultSchema = z.union([
  z.object({ skipped: z.literal(true), reason: z.string() }),
  z.object({ skipped: z.literal(false), snapshot: SnapshotItemSchema }),
])

export type TriggerResult = z.infer<typeof TriggerResultSchema>
