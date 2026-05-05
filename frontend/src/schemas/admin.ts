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

// ─── Secret Types ──────────────────────────────────────────────────────────

export const SchemaVersionSummarySchema = z.object({
  version_uuid: z.string().uuid(),
  version: z.number(),
  created_at: z.string(),
})

export const SchemaVersionFullSchema = z.object({
  version_uuid: z.string().uuid(),
  version: z.number(),
  schema_data: z.record(z.unknown()),
  schema_ui: z.record(z.unknown()),
  // notes peut être absent (vieille version backend) ou null/string
  notes: z.string().nullable().optional(),
  created_at: z.string(),
})

export const SecretTypeListItemSchema = z.object({
  type_uuid: z.string().uuid(),
  type: z.string(),
  sous_type: z.string(),
  label: z.string().nullable(),
  description: z.string().nullable(),
  is_system: z.boolean(),
  deprecated_at: z.string().nullable(),
  current_version: SchemaVersionSummarySchema.nullable(),
  used_by_secrets_count: z.number(),
})

export type SecretTypeListItem = z.infer<typeof SecretTypeListItemSchema>

export const SecretTypeDetailSchema = SecretTypeListItemSchema.extend({
  current_version_full: SchemaVersionFullSchema.nullable(),
  all_versions: z.array(SchemaVersionFullSchema),
})

export type SecretTypeDetail = z.infer<typeof SecretTypeDetailSchema>

export const SecretTypeListResponseSchema = z.object({
  types: z.array(SecretTypeListItemSchema),
})

export type SecretTypeListResponse = z.infer<typeof SecretTypeListResponseSchema>

export const ValidateSchemaResponseSchema = z.union([
  z.object({ valid: z.literal(true) }),
  z.object({ valid: z.literal(false), error: z.string() }),
])

export type ValidateSchemaResponse = z.infer<typeof ValidateSchemaResponseSchema>

// ─── Remote backup connections ───────────────────────────────────────────────

export const RemoteBackupConnectionSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  kind: z.enum(['sftp']),
  config: z.record(z.unknown()),
  created_at: z.string(),
  updated_at: z.string(),
  created_by_user_id: z.string().nullable(),
  deleted_at: z.string().nullable(),
})

export type RemoteBackupConnection = z.infer<typeof RemoteBackupConnectionSchema>

export const RemoteBackupConnectionListResponseSchema = z.object({
  connections: z.array(RemoteBackupConnectionSchema),
})

export type RemoteBackupConnectionListResponse = z.infer<
  typeof RemoteBackupConnectionListResponseSchema
>

export const RemoteBackupTestResponseSchema = z.union([
  z.object({ ok: z.literal(true) }),
  z.object({ ok: z.literal(false), error: z.string(), message: z.string() }),
])

export type RemoteBackupTestResponse = z.infer<typeof RemoteBackupTestResponseSchema>

export const RemoteBackupPushResultSchema = z.object({
  remote_id: z.string().uuid(),
  remote_name: z.string(),
  remote_filename: z.string(),
  bytes_sent: z.number(),
})

export type RemoteBackupPushResult = z.infer<typeof RemoteBackupPushResultSchema>

// ─── Replication strategies (LOT_20) ─────────────────────────────────────────

export const ReplicationStrategySchema = z.object({
  id: z.string().uuid(),
  type: z.enum(['none', 'patroni', 'harpocrate_sync', 's3_wal']),
  label: z.string(),
  description: z.string().nullable(),
  config: z.record(z.unknown()),
  enabled: z.boolean(),
  is_active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
})

export type ReplicationStrategy = z.infer<typeof ReplicationStrategySchema>

export const ReplicationStrategyListResponseSchema = z.object({
  strategies: z.array(ReplicationStrategySchema),
})

export type ReplicationStrategyListResponse = z.infer<
  typeof ReplicationStrategyListResponseSchema
>

export const ReplicationStatusResponseSchema = z.object({
  strategy: ReplicationStrategySchema.nullable(),
  status: z.string().optional(),
  live: z
    .object({
      type: z.string(),
      status: z.string(),
      primary: z.unknown().nullable(),
      replicas: z.array(z.record(z.unknown())),
      nodes: z.array(z.record(z.unknown())).optional(),
    })
    .optional(),
})

export type ReplicationStatusResponse = z.infer<typeof ReplicationStatusResponseSchema>
