/**
 * i18next initialization with react-i18next and browser language detector.
 * Priority: localStorage(harpocrate_locale) > navigator.language > 'en'
 */
import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import fr from "@/i18n/fr.json";
import en from "@/i18n/en.json";

export const LOCALE_STORAGE_KEY = "harpocrate_locale";
export const SUPPORTED_LOCALES = ["en", "fr"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      fr: { translation: fr },
      en: { translation: en },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "fr"],
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: ["localStorage"],
    },
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;

export function setLocale(locale: SupportedLocale): void {
  void i18n.changeLanguage(locale);
  localStorage.setItem(LOCALE_STORAGE_KEY, locale);
}

export function currentLocale(): SupportedLocale {
  const lng = i18n.language?.slice(0, 2);
  return (SUPPORTED_LOCALES as readonly string[]).includes(lng ?? "")
    ? (lng as SupportedLocale)
    : "en";
}
