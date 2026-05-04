/**
 * i18next initialization with react-i18next.
 * Languages: fr (default), en.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import fr from '@/i18n/fr.json'
import en from '@/i18n/en.json'

i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: 'fr',
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false, // React already escapes
  },
})

export default i18n
