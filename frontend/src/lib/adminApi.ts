import { api } from '@/lib/api-client'
import {
  MaintenanceStatusSchema,
  BackupListResponseSchema,
  BackupSchema,
  RestoreResultSchema,
  SystemInfoSchema,
  AdminUsersResponseSchema,
  EnvConfigSchema,
  S3BackupListResponseSchema,
  S3PushResultSchema,
  SnapshotPolicySchema,
  SnapshotHistorySchema,
  TriggerResultSchema,
  SecretTypeListResponseSchema,
  SecretTypeDetailSchema,
  ValidateSchemaResponseSchema,
  RemoteBackupConnectionListResponseSchema,
  RemoteBackupConnectionSchema,
  RemoteBackupTestResponseSchema,
  RemoteBackupPushResultSchema,
  ReplicationStrategyListResponseSchema,
  ReplicationStatusResponseSchema,
  type MaintenanceStatus,
  type BackupListResponse,
  type Backup,
  type RestoreResult,
  type SystemInfo,
  type AdminUsersResponse,
  type EnvConfig,
  type S3BackupListResponse,
  type S3PushResult,
  type SnapshotPolicy,
  type SnapshotHistory,
  type TriggerResult,
  type SecretTypeListResponse,
  type SecretTypeDetail,
  type ValidateSchemaResponse,
  type RemoteBackupConnection,
  type RemoteBackupConnectionListResponse,
  type RemoteBackupTestResponse,
  type RemoteBackupPushResult,
  type ReplicationStrategyListResponse,
  type ReplicationStatusResponse,
} from '@/schemas/admin'

export async function fetchMaintenanceStatus(): Promise<MaintenanceStatus> {
  const raw = await api.get<unknown>('/admin/maintenance/status')
  return MaintenanceStatusSchema.parse(raw)
}

export async function enableMaintenance(body: {
  reason: string
  delay_seconds?: number
  estimated_duration_minutes?: number
}): Promise<MaintenanceStatus> {
  const raw = await api.post<unknown>('/admin/maintenance/enable', body)
  return MaintenanceStatusSchema.parse(raw)
}

export async function disableMaintenance(): Promise<MaintenanceStatus> {
  const raw = await api.post<unknown>('/admin/maintenance/disable', {})
  return MaintenanceStatusSchema.parse(raw)
}

export async function fetchBackups(): Promise<BackupListResponse> {
  const raw = await api.get<unknown>('/admin/backups')
  return BackupListResponseSchema.parse(raw)
}

export async function fetchBackup(id: string): Promise<Backup> {
  const raw = await api.get<unknown>(`/admin/backups/${id}`)
  return BackupSchema.parse(raw)
}

export async function createBackup(body: { description?: string }): Promise<Backup> {
  const raw = await api.post<unknown>('/admin/backups', body)
  return BackupSchema.parse(raw)
}

export async function deleteBackup(id: string): Promise<void> {
  await api.delete<void>(`/admin/backups/${id}`)
}

export function backupDownloadUrl(id: string): string {
  return `/v1/admin/backups/${id}/download`
}

export async function restoreBackup(
  id: string,
  body: { age_private_key: string; confirmation: string; auto_enable_maintenance: boolean },
): Promise<RestoreResult> {
  const raw = await api.post<unknown>(`/admin/backups/${id}/restore`, body)
  return RestoreResultSchema.parse(raw)
}

export async function fetchSystemInfo(): Promise<SystemInfo> {
  const raw = await api.get<unknown>('/admin/system/info')
  return SystemInfoSchema.parse(raw)
}

export async function fetchAdminUsers(params?: {
  limit?: number
  offset?: number
}): Promise<AdminUsersResponse> {
  const q = new URLSearchParams()
  if (params?.limit) q.set('limit', String(params.limit))
  if (params?.offset) q.set('offset', String(params.offset))
  const raw = await api.get<unknown>(`/admin/users?${q.toString()}`)
  return AdminUsersResponseSchema.parse(raw)
}

export async function fetchEnvConfig(): Promise<EnvConfig> {
  const raw = await api.get<unknown>('/admin/system/env')
  return EnvConfigSchema.parse(raw)
}

export async function fetchS3Backups(): Promise<S3BackupListResponse> {
  const raw = await api.get<unknown>('/admin/backups/s3')
  return S3BackupListResponseSchema.parse(raw)
}

export async function pushBackupToS3(backupId: string): Promise<S3PushResult> {
  const raw = await api.post<unknown>(`/admin/backups/${backupId}/push-s3`, {})
  return S3PushResultSchema.parse(raw)
}

export async function pullBackupFromS3(s3Key: string): Promise<Backup> {
  const raw = await api.post<unknown>('/admin/backups/s3/pull', { s3_key: s3Key })
  return BackupSchema.parse(raw)
}

export async function fetchSnapshotPolicy(): Promise<SnapshotPolicy> {
  const raw = await api.get<unknown>('/admin/snapshots/policy')
  return SnapshotPolicySchema.parse(raw)
}

export async function updateSnapshotPolicy(policy: SnapshotPolicy): Promise<SnapshotPolicy> {
  const raw = await api.put<unknown>('/admin/snapshots/policy', policy)
  return SnapshotPolicySchema.parse(raw)
}

export async function triggerSnapshot(body: {
  force?: boolean
  skip_remote?: boolean
  description?: string
}): Promise<TriggerResult> {
  const raw = await api.post<unknown>('/admin/snapshots/trigger', body)
  return TriggerResultSchema.parse(raw)
}

export async function fetchSnapshotHistory(params?: {
  tier?: string
  limit?: number
}): Promise<SnapshotHistory> {
  const q = new URLSearchParams()
  if (params?.tier) q.set('tier', params.tier)
  if (params?.limit) q.set('limit', String(params.limit))
  const raw = await api.get<unknown>(`/admin/snapshots/history?${q.toString()}`)
  return SnapshotHistorySchema.parse(raw)
}

// ─── Secret Types API ─────────────────────────────────────────────────────

export async function fetchSecretTypes(params?: {
  q?: string
  include_deprecated?: boolean
}): Promise<SecretTypeListResponse> {
  const q = new URLSearchParams()
  if (params?.q) q.set('q', params.q)
  if (params?.include_deprecated) q.set('include_deprecated', 'true')
  const raw = await api.get<unknown>(`/admin/secret-types?${q.toString()}`)
  return SecretTypeListResponseSchema.parse(raw)
}

export async function fetchSecretType(typeUuid: string): Promise<SecretTypeDetail> {
  const raw = await api.get<unknown>(`/admin/secret-types/${typeUuid}`)
  return SecretTypeDetailSchema.parse(raw)
}

export async function createSecretType(body: {
  type: string
  sous_type: string
  label?: string
  description?: string
  schema_data: Record<string, unknown>
  schema_ui?: Record<string, unknown>
  notes?: string
}): Promise<{ type_uuid: string; version_uuid: string }> {
  return api.post<{ type_uuid: string; version_uuid: string }>('/admin/secret-types', body)
}

export async function addSecretTypeVersion(
  typeUuid: string,
  body: {
    schema_data: Record<string, unknown>
    schema_ui?: Record<string, unknown>
    notes?: string
    set_as_current?: boolean
  }
): Promise<{ version_uuid: string; version: number }> {
  return api.post<{ version_uuid: string; version: number }>(
    `/admin/secret-types/${typeUuid}/schemas`,
    body
  )
}

export async function deleteSecretType(typeUuid: string): Promise<void> {
  return api.delete<void>(`/admin/secret-types/${typeUuid}`)
}

export async function deleteSecretTypeVersion(
  typeUuid: string,
  versionUuid: string
): Promise<void> {
  return api.delete<void>(`/admin/secret-types/${typeUuid}/schemas/${versionUuid}`)
}

export async function validateJsonSchema(
  schemaData: Record<string, unknown>
): Promise<ValidateSchemaResponse> {
  const raw = await api.post<unknown>('/admin/secret-types/validate-schema', {
    schema_data: schemaData,
  })
  return ValidateSchemaResponseSchema.parse(raw)
}

// ─── Remote backup connections (LOT remote backups) ──────────────────────────

export async function fetchRemoteBackupConnections(): Promise<RemoteBackupConnectionListResponse> {
  const raw = await api.get<unknown>('/admin/backup-remotes')
  return RemoteBackupConnectionListResponseSchema.parse(raw)
}

export async function fetchRemoteBackupConnection(id: string): Promise<RemoteBackupConnection> {
  const raw = await api.get<unknown>(`/admin/backup-remotes/${id}`)
  return RemoteBackupConnectionSchema.parse(raw)
}

export interface RemoteBackupCreatePayload {
  name: string
  kind: 'sftp' | 's3' | 'ftps'
  config: Record<string, unknown>
  credentials: Record<string, unknown>
}

export async function createRemoteBackupConnection(
  body: RemoteBackupCreatePayload,
): Promise<{ id: string }> {
  return api.post<{ id: string }>('/admin/backup-remotes', body)
}

export interface RemoteBackupUpdatePayload {
  name?: string
  config?: Record<string, unknown>
  credentials?: Record<string, unknown>
}

export async function updateRemoteBackupConnection(
  id: string,
  body: RemoteBackupUpdatePayload,
): Promise<{ updated: number }> {
  return api.patch<{ updated: number }>(`/admin/backup-remotes/${id}`, body)
}

export async function deleteRemoteBackupConnection(id: string): Promise<void> {
  await api.delete<void>(`/admin/backup-remotes/${id}`)
}

export async function pushBackupToRemote(
  backupId: string,
  remoteId: string,
): Promise<RemoteBackupPushResult> {
  const raw = await api.post<unknown>(
    `/admin/backups/${backupId}/push-to-remote/${remoteId}`,
    {},
  )
  return RemoteBackupPushResultSchema.parse(raw)
}

export async function testRemoteBackupConnection(id: string): Promise<RemoteBackupTestResponse> {
  // Le backend renvoie 200 si OK, 502 si KO. api-client throw sur 502 → on catch ici
  // pour récupérer le body et exposer le message d'erreur lisible côté UI.
  try {
    const raw = await api.post<unknown>(`/admin/backup-remotes/${id}/test`, {})
    return RemoteBackupTestResponseSchema.parse(raw)
  } catch (err) {
    // ApiError contient le code/message — on les remappe en RemoteBackupTestResponse
    const e = err as { code?: string; message?: string }
    return {
      ok: false,
      error: e.code ?? 'test_failed',
      message: e.message ?? 'Connection test failed',
    }
  }
}

// ─── Age keygen (LOT_56) ─────────────────────────────────────────────────────

export interface AgeKeypair {
  public_key: string
  private_key: string
  /** True si la clé publique a été persistée en DB et est active immédiatement. */
  applied: boolean
  warning: string
}

export async function generateAgeKeypair(): Promise<AgeKeypair> {
  return api.post<AgeKeypair>('/admin/system/age-keygen', {})
}

// ─── Replication strategies (LOT_20) ─────────────────────────────────────────

export async function fetchReplicationStrategies(): Promise<ReplicationStrategyListResponse> {
  const raw = await api.get<unknown>('/admin/replication/strategies')
  return ReplicationStrategyListResponseSchema.parse(raw)
}

export async function fetchReplicationStatus(): Promise<ReplicationStatusResponse> {
  const raw = await api.get<unknown>('/admin/replication/status')
  return ReplicationStatusResponseSchema.parse(raw)
}

export async function activateReplicationStrategy(
  strategyId: string,
): Promise<{ activated: boolean; strategy_id: string }> {
  return api.post<{ activated: boolean; strategy_id: string }>(
    `/admin/replication/strategies/${strategyId}/activate`,
    {},
  )
}

