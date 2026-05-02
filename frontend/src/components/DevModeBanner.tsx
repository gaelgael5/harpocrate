/**
 * Bandeau visuel permanent quand HARPOCRATE_DEV_MODE=true côté serveur.
 *
 * Aucun impact fonctionnel ou cryptographique : pur repère visuel pour
 * éviter de confondre une instance dev avec la prod.
 */
import { useTranslation } from 'react-i18next'
import { useDevMode } from '@/hooks/useDevMode'

export function DevModeBanner() {
  const { t } = useTranslation()
  const { enabled, label } = useDevMode()

  if (!enabled) return null

  return (
    <div
      role="alert"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 1000,
        backgroundColor: '#c92a2a',
        color: '#fff',
        padding: '6px 16px',
        fontSize: 13,
        fontWeight: 600,
        textAlign: 'center',
        letterSpacing: '0.5px',
        borderBottom: '2px solid #fff3bf',
      }}
    >
      <span style={{
        backgroundColor: '#fff3bf',
        color: '#c92a2a',
        padding: '2px 8px',
        borderRadius: 3,
        marginRight: 8,
        fontSize: 11,
      }}>
        {label}
      </span>
      {t('devMode.banner')}
    </div>
  )
}
