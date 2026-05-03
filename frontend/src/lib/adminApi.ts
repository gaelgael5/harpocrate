import { api } from '@/lib/api-client'
import {
  MaintenanceStatusSchema,
  BackupListResponseSchema,
  BackupSchema,
  RestoreResultSchema,
  type MaintenanceStatus,
  type BackupListResponse,
  type Backup,
  type RestoreResult,
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
