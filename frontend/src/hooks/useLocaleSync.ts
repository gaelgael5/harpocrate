/**
 * Syncs the user's preferred_locale from the DB to i18next/localStorage.
 * Must be called after /me is loaded. DB locale > localStorage.
 */
import { useEffect } from 'react'
import { setLocale, LOCALE_STORAGE_KEY, type SupportedLocale, SUPPORTED_LOCALES } from '@/lib/i18n'

export function useLocaleSync(preferredLocale: string | undefined) {
  useEffect(() => {
    if (!preferredLocale) return
    const locale = preferredLocale as SupportedLocale
    if (!(SUPPORTED_LOCALES as readonly string[]).includes(locale)) return

    const stored = localStorage.getItem(LOCALE_STORAGE_KEY) as SupportedLocale | null
    if (stored !== locale) {
      setLocale(locale)
    }
  }, [preferredLocale])
}
