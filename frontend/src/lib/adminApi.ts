import { api } from '@/lib/api-client'
import {
  MaintenanceStatusSchema,
  BackupListResponseSchema,
  BackupSchema,
  RestoreResultSchema,
  SystemInfoSchema,
  AdminUsersResponseSchema,
  EnvConfigSchema,
  SnapshotPolicySchema,
  SnapshotHistorySchema,
  TriggerResultSchema,
  SecretTypeListResponseSchema,
  SecretTypeDetailSchema,
  ValidateSchemaResponseSchema,
  RemoteBackupConnectionListResponseSchema,
  RemoteBackupTestResponseSchema,
  RemoteBackupPushResultSchema,
  ScheduledBackupListResponseSchema,
  CronValidationResponseSchema,
  ScheduledBackupRunResultSchema,
  ReplicationStrategyListResponseSchema,
  ReplicationStatusResponseSchema,
  type MaintenanceStatus,
  type BackupListResponse,
  type Backup,
  type RestoreResult,
  type SystemInfo,
  type AdminUsersResponse,
  type EnvConfig,
  type SnapshotPolicy,
  type SnapshotHistory,
  type TriggerResult,
  type SecretTypeListResponse,
  type SecretTypeDetail,
  type ValidateSchemaResponse,
  type RemoteBackupConnectionListResponse,
  type RemoteBackupTestResponse,
  type RemoteBackupPushResult,
  type ScheduledBackupListResponse,
  type CronValidationResponse,
  type ScheduledBackupRunResult,
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

// ─── Test de connexion (deux endpoints, deux usages) ────────────────────────
//
// Le backend renvoie TOUJOURS 200 — le résultat (ok:true ou ok:false avec
// message) est dans le body. Évite que Cloudflare avale un 5xx et masque
// l'erreur du provider. Le catch reste utile pour les vraies erreurs réseau.

export interface TestRemoteBackupNewPayload {
  kind: 'sftp' | 's3' | 'ftps'
  config: Record<string, unknown>
  credentials: Record<string, unknown>
  path: string
}

/** Teste un path avec config + creds fournis (création / nouveaux creds). */
export async function testRemoteBackupConnectionConfig(
  body: TestRemoteBackupNewPayload,
): Promise<RemoteBackupTestResponse> {
  try {
    const raw = await api.post<unknown>('/admin/backup-remotes/test', body)
    return RemoteBackupTestResponseSchema.parse(raw)
  } catch (err) {
    const e = err as { code?: string; message?: string }
    return {
      ok: false,
      error: e.code ?? 'test_failed',
      message: e.message ?? 'Connection test failed',
    }
  }
}

export interface TestRemoteBackupStoredPayload {
  path: string
  /** Optionnel : surcharge le `config` stocké en DB (test sans sauvegarder). */
  config?: Record<string, unknown>
}

/** Teste un path avec creds stockés en DB (édition sans resaisir creds). */
export async function testRemoteBackupConnectionStored(
  id: string,
  body: TestRemoteBackupStoredPayload,
): Promise<RemoteBackupTestResponse> {
  try {
    const raw = await api.post<unknown>(`/admin/backup-remotes/${id}/test`, body)
    return RemoteBackupTestResponseSchema.parse(raw)
  } catch (err) {
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

export async function deactivateReplicationStrategy(
  strategyId: string,
): Promise<{ deactivated: boolean; strategy_id: string }> {
  return api.post<{ deactivated: boolean; strategy_id: string }>(
    `/admin/replication/strategies/${strategyId}/deactivate`,
    {},
  )
}

// ─── Streaming replication nodes (LOT réplication itération 1) ───────────────

import {
  ReplicationNodeListResponseSchema,
  ReplicationNodeAddResponseSchema,
  type ReplicationNodeListResponse,
  type ReplicationNodeAddResponse,
} from '@/schemas/admin'

export async function fetchStreamingNodes(): Promise<ReplicationNodeListResponse> {
  const raw = await api.get<unknown>('/admin/replication/streaming/nodes')
  return ReplicationNodeListResponseSchema.parse(raw)
}

export interface AddStreamingNodePayload {
  label: string
  host: string
  port: number
  role: 'standby_ro' | 'standby_failover_ready' | 'archive_only'
  notes?: string | null
  master_host: string
  master_port: number
  standby_data_dir?: string
}

export async function addStreamingNode(
  body: AddStreamingNodePayload,
): Promise<ReplicationNodeAddResponse> {
  const raw = await api.post<unknown>('/admin/replication/streaming/nodes', body)
  return ReplicationNodeAddResponseSchema.parse(raw)
}

export async function deleteStreamingNode(id: string): Promise<void> {
  await api.delete<void>(`/admin/replication/streaming/nodes/${id}`)
}

export async function reloadPgHba(): Promise<{ reloaded: boolean }> {
  return api.post<{ reloaded: boolean }>(
    '/admin/replication/streaming/reload-pg-hba',
    {},
  )
}

// ─── (it2) test connect / observations / lag thresholds ────────────────────

import {
  TcpPingResultSchema,
  ReplicationNodeObservationsResponseSchema,
  LagThresholdsSchema,
  type TcpPingResult,
  type ReplicationNodeObservationsResponse,
  type LagThresholds,
} from '@/schemas/admin'

export async function testStreamingNodeConnect(id: string): Promise<TcpPingResult> {
  const raw = await api.post<unknown>(
    `/admin/replication/streaming/nodes/${id}/test-connect`,
    {},
  )
  return TcpPingResultSchema.parse(raw)
}

export async function fetchStreamingNodeObservations(
  id: string,
  hours: number = 24,
): Promise<ReplicationNodeObservationsResponse> {
  const raw = await api.get<unknown>(
    `/admin/replication/streaming/nodes/${id}/observations?hours=${hours}`,
  )
  return ReplicationNodeObservationsResponseSchema.parse(raw)
}

export async function fetchLagThresholds(): Promise<LagThresholds> {
  const raw = await api.get<unknown>('/admin/replication/streaming/lag-thresholds')
  return LagThresholdsSchema.parse(raw)
}

export async function updateLagThresholds(
  body: LagThresholds,
): Promise<LagThresholds> {
  const raw = await api.patch<unknown>(
    '/admin/replication/streaming/lag-thresholds',
    body,
  )
  return LagThresholdsSchema.parse(raw)
}

// ─── Scheduled backups (cron-like) ───────────────────────────────────────────

export async function fetchScheduledBackups(): Promise<ScheduledBackupListResponse> {
  const raw = await api.get<unknown>('/admin/scheduled-backups')
  return ScheduledBackupListResponseSchema.parse(raw)
}

export interface ScheduledBackupCreatePayload {
  name: string
  cron_expression: string
  remote_id: string | null
  miss_threshold_minutes: number
  description?: string | null
  enabled?: boolean
}

export async function createScheduledBackup(
  body: ScheduledBackupCreatePayload,
): Promise<{ id: string }> {
  return api.post<{ id: string }>('/admin/scheduled-backups', body)
}

export interface ScheduledBackupPatchPayload {
  name?: string
  cron_expression?: string
  /** Pour effacer : remote_id=null + set_remote_id=true. Pour ne pas toucher : omettre. */
  remote_id?: string | null
  set_remote_id?: boolean
  miss_threshold_minutes?: number
  description?: string | null
  set_description?: boolean
  enabled?: boolean
}

export async function updateScheduledBackup(
  id: string,
  body: ScheduledBackupPatchPayload,
): Promise<{ updated: number }> {
  return api.patch<{ updated: number }>(`/admin/scheduled-backups/${id}`, body)
}

export async function deleteScheduledBackup(id: string): Promise<void> {
  await api.delete<void>(`/admin/scheduled-backups/${id}`)
}

export async function runScheduledBackupNow(id: string): Promise<ScheduledBackupRunResult> {
  const raw = await api.post<unknown>(`/admin/scheduled-backups/${id}/run-now`, {})
  return ScheduledBackupRunResultSchema.parse(raw)
}

export async function validateCronExpression(
  cron_expression: string,
): Promise<CronValidationResponse> {
  const raw = await api.post<unknown>('/admin/scheduled-backups/validate-cron', {
    cron_expression,
  })
  return CronValidationResponseSchema.parse(raw)
}

