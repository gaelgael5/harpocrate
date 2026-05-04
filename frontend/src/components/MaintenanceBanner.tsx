import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchMaintenanceStatus } from '@/lib/adminApi'

export const MAINTENANCE_BANNER_HEIGHT = 36

export function MaintenanceBanner() {
  const { t } = useTranslation()

  const { data } = useQuery({
    queryKey: ['maintenance-status'],
    queryFn: fetchMaintenanceStatus,
    refetchInterval: 30_000,
    retry: false,
  })

  if (!data?.active) return null

  const message = data.reason
    ? t('maintenance.banner', { reason: data.reason })
    : t('maintenance.bannerNoReason')

  return (
    <div
      role="alert"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: MAINTENANCE_BANNER_HEIGHT,
        zIndex: 1200,
        backgroundColor: '#e67700',
        color: '#fff',
        padding: '8px 16px',
        fontSize: 13,
        fontWeight: 600,
        textAlign: 'center',
        letterSpacing: '0.5px',
        borderBottom: '2px solid #fff3bf',
        boxSizing: 'border-box',
      }}
    >
      ⚠️ {message}
    </div>
  )
}
