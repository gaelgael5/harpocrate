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
  type MaintenanceStatus,
  type BackupListResponse,
  type Backup,
  type RestoreResult,
  type SystemInfo,
  type AdminUsersResponse,
  type EnvConfig,
  type S3BackupListResponse,
  type S3PushResult,
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
