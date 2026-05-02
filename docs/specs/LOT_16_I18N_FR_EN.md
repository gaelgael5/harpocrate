# Lot 16 — Internationalisation FR / EN

> **Prérequis** : Lots 00-15.

## Objectif

Rendre l'**interface utilisateur entièrement bilingue** (français et anglais), avec sélection manuelle ou détection automatique. Persistance de la préférence côté DB pour cohérence multi-device. Couvre l'UI user (lot 11) et l'UI admin (lots 12b, 12c, 15).

L'**API backend** ne renvoie pas de messages traduits — elle renvoie des **codes d'erreur stables** que le client traduit. Cette séparation préserve la zero-trust côté client et permet d'ajouter d'autres langues sans toucher au backend.

## Dépendances

- Lots 00-15

## Périmètre

### Inclus

- Migration `007_user_locale.sql` : colonne `users.preferred_locale TEXT NOT NULL DEFAULT 'en'`
- Endpoint `PATCH /v1/me/preferences` pour modifier la préférence
- `GET /v1/me` retourne `preferred_locale`
- Frontend : intégration `react-i18next` + `i18next-browser-languagedetector`
- Fichiers `locales/fr.json` et `locales/en.json` couvrant **toute l'UI existante** (lots 11, 12b, 12c, 15)
- Composant `<LocaleSwitcher />` accessible depuis le menu user et le menu admin
- Détection automatique au premier chargement : `navigator.language` (fallback `en`)
- Persistance : localStorage côté client + DB côté user
- Synchronisation : si user logué, locale DB > localStorage
- Format des dates et nombres adapté à la locale (Intl API)
- Codes d'erreur backend → traductions client (mapping centralisé)
- Direction `ltr` uniquement (pas de RTL pour FR/EN)

### Exclus

- Pas de traduction du contenu user-defined (noms de wallets, tags, descriptions de secrets, labels de types)
- Pas d'autres langues (espagnol, allemand, etc.) — extensible mais non livré
- Pas de pluriels complexes (Intl PluralRules ne couvre que cas standards)
- Pas de format des unités (KB/MB/GB) traduit (universellement compris)

## Spécifications fonctionnelles

### Modèle de données

```sql
-- migrations/007_user_locale.sql

ALTER TABLE users
    ADD COLUMN preferred_locale TEXT NOT NULL DEFAULT 'en'
        CHECK (preferred_locale IN ('en', 'fr'));
```

Choix du défaut `'en'` : langue technique standard, utilisateurs internationaux par défaut. La détection navigator.language au premier login basculera en FR pour les francophones.

### Endpoints

#### `PATCH /v1/me/preferences`

- **Auth** : JWT
- **Body partiel** :
```json
{
  "preferred_locale": "fr"
}
```
- **Validations** : `preferred_locale ∈ ['en', 'fr']`
- **Réponse** : `200 { "preferred_locale": "fr" }`
- **Audit** : pas d'audit log (action triviale, volume potentiellement gros)

#### `GET /v1/me` (modifié)

Ajout du champ `preferred_locale` dans la réponse :

```json
{
  "id": "...",
  "email": "...",
  "preferred_locale": "fr",
  "...": "..."
}
```

### Détection initiale

Ordre de priorité au démarrage de l'UI :

1. **localStorage `harpocrate_locale`** : si présent et valide, utiliser
2. **`/me.preferred_locale`** si user logué et localStorage absent : utiliser et persister localStorage
3. **`navigator.language`** : si commence par `fr`, utiliser `fr`. Sinon `en`. Persister localStorage.

Quand le user change de locale via UI :
- Update i18next instance immédiate
- PATCH `/v1/me/preferences` (si logué)
- Update localStorage

### Conflits localStorage vs DB

Si `localStorage.harpocrate_locale = 'fr'` mais `user.preferred_locale = 'en'` (l'user a changé sur un autre device), au prochain login on utilise **DB > localStorage** et on update localStorage. Cohérence garantie côté serveur.

Edge case : un user qui n'a pas encore loadé `/me` au moment du choix d'i18n initial. Workflow :
1. App démarre, `i18next` initialise avec localStorage ou navigator.language
2. App fait `/me`, reçoit `preferred_locale`
3. Si différent de l'instance i18next courante, on bascule

Côté UX : un petit flash si conflit. Acceptable car rare.

### Composant `<LocaleSwitcher />`

Dans le menu user header (à droite) et dans le menu admin :

```
[🇬🇧 English ▾]
   ▾
   ┌──────────┐
   │ 🇬🇧 English│
   │ 🇫🇷 Français│
   └──────────┘
```

Click → bascule immédiate, persistance.

### Couverture des chaînes

**Lot 11 (UI user)** :
- Login / unlock screen
- Dashboard
- Wallets list / detail
- Secrets list / detail / create / edit
- Grants management
- API keys
- Account settings
- Password / recovery management
- Quarantine notice
- Anomaly notifications
- Reverify modal
- Tous les boutons, labels de form, messages d'erreur, tooltips

**Lot 12b (UI admin core)** :
- Admin dashboard
- Backup list
- Backup detail
- Restore wizard (4 steps)
- Maintenance toggle
- Maintenance banner

**Lot 12c (UI admin reste)** :
- Users list / detail
- Identity management modals
- Anomaly acknowledge
- Audit log viewer
- System info page

**Lot 15 (UI admin types)** :
- Secret types list
- Type create / detail
- Schema version create / detail

**Toasts / notifications transverses** :
- Success messages
- Validation errors
- API error codes mapping

### Codes d'erreur backend → traductions

Le backend renvoie des codes string stables :

```json
{
  "error": "wallet_not_found",
  "error_args": { "wallet_name": "prod" }
}
```

Le client traduit :

```json
// fr.json
"errors": {
  "wallet_not_found": "Wallet « {{wallet_name}} » introuvable",
  "user_in_quarantine": "Compte en quarantaine jusqu'au {{quarantine_until}}",
  "reverify_required": "Veuillez confirmer votre passphrase",
  "...": "..."
}
```

Liste des codes d'erreur à couvrir (~60-80) :
- Tous les codes des lots 02-14
- Validations Pydantic standard (mappées via i18next)

### Format des dates et nombres

```typescript
// Utility
export function formatDate(date: string | Date, locale: string): string {
  return new Intl.DateTimeFormat(locale === 'fr' ? 'fr-FR' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(date));
}

export function formatRelativeTime(date: string | Date, locale: string): string {
  const diff = Date.now() - new Date(date).getTime();
  const rtf = new Intl.RelativeTimeFormat(locale === 'fr' ? 'fr-FR' : 'en-US', { numeric: 'auto' });
  // logique de bucket (minutes, heures, jours...)
  // ...
}

export function formatBytes(bytes: number, locale: string): string {
  // Utilise Intl.NumberFormat pour la séparation des milliers
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) {
    const kb = (bytes / 1024).toFixed(1);
    return `${new Intl.NumberFormat(locale === 'fr' ? 'fr-FR' : 'en-US').format(parseFloat(kb))} KB`;
  }
  // ...
}
```

## Spécifications techniques

### Stack

- **`i18next`** : moteur i18n
- **`react-i18next`** : intégration React (hook `useTranslation`)
- **`i18next-browser-languagedetector`** : détection navigator + localStorage
- **`i18next-http-backend`** : NON utilisé (on bundle les traductions, pas de chargement réseau)

### Structure de fichiers

```
frontend/src/
├── i18n/
│   ├── index.ts              # config i18next
│   ├── locales/
│   │   ├── en.json
│   │   └── fr.json
│   └── error_codes.ts        # mapping codes backend → clés i18n
├── components/
│   ├── LocaleSwitcher.tsx
│   └── ...
├── utils/
│   └── formatters.ts         # formatDate, formatBytes, etc.
└── ...
```

### Configuration i18next

```typescript
// frontend/src/i18n/index.ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './locales/en.json';
import fr from './locales/fr.json';

const SUPPORTED = ['en', 'fr'] as const;
type SupportedLocale = typeof SUPPORTED[number];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: 'en',
    supportedLngs: SUPPORTED as unknown as string[],
    nonExplicitSupportedLngs: true,  // 'fr-FR' → 'fr'

    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'harpocrate_locale',
      caches: ['localStorage'],
    },

    resources: {
      en: { translation: en },
      fr: { translation: fr },
    },

    interpolation: {
      escapeValue: false,  // React échappe déjà
    },
  });

export async function syncLocaleFromUser(userLocale: string) {
  if (SUPPORTED.includes(userLocale as SupportedLocale)) {
    if (i18n.language !== userLocale) {
      await i18n.changeLanguage(userLocale);
      localStorage.setItem('harpocrate_locale', userLocale);
    }
  }
}

export async function setLocale(locale: SupportedLocale, persistToServer: boolean = true) {
  await i18n.changeLanguage(locale);
  localStorage.setItem('harpocrate_locale', locale);
  if (persistToServer) {
    await fetch('/v1/me/preferences', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preferred_locale: locale }),
    });
  }
}

export default i18n;
```

### Composant `<LocaleSwitcher />`

```typescript
import { useTranslation } from 'react-i18next';
import { Menu } from '@mantine/core';
import { setLocale } from '@/i18n';

const FLAGS = { en: '🇬🇧', fr: '🇫🇷' };
const NAMES = { en: 'English', fr: 'Français' };

export function LocaleSwitcher() {
  const { i18n } = useTranslation();
  const current = i18n.language as 'en' | 'fr';

  return (
    <Menu>
      <Menu.Target>
        <button>{FLAGS[current]} {NAMES[current]}</button>
      </Menu.Target>
      <Menu.Dropdown>
        {(['en', 'fr'] as const).map((loc) => (
          <Menu.Item
            key={loc}
            onClick={() => setLocale(loc)}
            disabled={loc === current}
          >
            {FLAGS[loc]} {NAMES[loc]}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
```

### Hook de synchronisation au login

```typescript
// frontend/src/hooks/useLocaleSync.ts
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { syncLocaleFromUser } from '@/i18n';
import { api } from '@/api';

export function useLocaleSync() {
  const { data: me } = useQuery(['me'], () => api.get('/v1/me').then(r => r.data));

  useEffect(() => {
    if (me?.preferred_locale) {
      syncLocaleFromUser(me.preferred_locale);
    }
  }, [me?.preferred_locale]);
}
```

Appelé dans le layout principal après login.

### Mapping codes d'erreur

```typescript
// frontend/src/i18n/error_codes.ts

import { i18n } from '@/i18n';

export function translateApiError(error: ApiError): string {
  const code = error.error || 'unknown_error';
  const args = error.error_args || {};
  const key = `errors.${code}`;

  // Si la clé n'existe pas, fallback à un message générique avec le code
  if (!i18n.exists(key)) {
    return i18n.t('errors.unknown_with_code', { code });
  }

  return i18n.t(key, args);
}
```

### Exemple `en.json` (extrait)

```json
{
  "common": {
    "save": "Save",
    "cancel": "Cancel",
    "delete": "Delete",
    "edit": "Edit",
    "create": "Create",
    "loading": "Loading...",
    "search": "Search",
    "yes": "Yes",
    "no": "No"
  },
  "auth": {
    "login": "Log in",
    "logout": "Log out",
    "unlock_passphrase_label": "Enter your passphrase to unlock",
    "unlock_button": "Unlock",
    "first_login_title": "Welcome to Harpocrate",
    "first_login_subtitle": "Let's set up your account"
  },
  "wallets": {
    "list_title": "Your wallets",
    "create_button": "New wallet",
    "owned_label": "Owned by you",
    "shared_label": "Shared with you",
    "empty_state": "You don't have any wallets yet."
  },
  "secrets": {
    "list_title": "Secrets in {{wallet_name}}",
    "create_button": "Add secret",
    "placeholder_badge": "Placeholder",
    "linked_badge": "Linked"
  },
  "permissions": {
    "read": "Read",
    "add": "Add",
    "init": "Init",
    "write": "Write",
    "remove": "Remove",
    "share": "Share"
  },
  "admin": {
    "title": "Admin mode",
    "warning_banner": "⚠ You are in admin mode",
    "dashboard": "Dashboard",
    "backups": "Backups",
    "users": "Users",
    "audit_log": "Audit log",
    "system": "System",
    "secret_types": "Secret types"
  },
  "secret_types": {
    "list_title": "Secret types",
    "new_button": "New type",
    "current_version": "Current: v{{version}}",
    "used_by_count": "{{count}} secret",
    "used_by_count_plural": "{{count}} secrets",
    "schema_data_label": "Schema data (JSON Schema)",
    "schema_ui_label": "Schema UI (RJSF)",
    "validate_button": "Validate"
  },
  "errors": {
    "unknown_error": "An unexpected error occurred",
    "unknown_with_code": "Error: {{code}}",
    "wallet_not_found": "Wallet \"{{wallet_name}}\" not found",
    "user_in_quarantine": "Your account is in quarantine until {{quarantine_until}}",
    "reverify_required": "Please confirm your passphrase",
    "reverify_token_invalid_or_expired": "Confirmation expired, please try again",
    "secret_type_already_exists": "A type with this (type, sous_type) already exists",
    "cannot_delete_system_type": "System types cannot be deleted",
    "cannot_delete_current_version": "Cannot delete the current version. Set another version as current first.",
    "secret_type_in_use": "This type is in use by {{count}} secrets and cannot be deleted",
    "invalid_json_schema": "Invalid JSON Schema: {{message}}",
    "session_invalidated_by_restore": "The server has been restored. Please reconnect.",
    "maintenance_in_progress": "Harpocrate is in maintenance. Estimated end: {{estimated_end_at}}"
  },
  "datetime": {
    "just_now": "just now",
    "minutes_ago": "{{count}} minute ago",
    "minutes_ago_plural": "{{count}} minutes ago",
    "hours_ago": "{{count}} hour ago",
    "hours_ago_plural": "{{count}} hours ago",
    "days_ago": "{{count}} day ago",
    "days_ago_plural": "{{count}} days ago"
  }
}
```

### Exemple `fr.json` (extrait)

```json
{
  "common": {
    "save": "Enregistrer",
    "cancel": "Annuler",
    "delete": "Supprimer",
    "edit": "Modifier",
    "create": "Créer",
    "loading": "Chargement...",
    "search": "Rechercher",
    "yes": "Oui",
    "no": "Non"
  },
  "auth": {
    "login": "Se connecter",
    "logout": "Se déconnecter",
    "unlock_passphrase_label": "Saisissez votre phrase de passe pour déverrouiller",
    "unlock_button": "Déverrouiller",
    "first_login_title": "Bienvenue sur Harpocrate",
    "first_login_subtitle": "Configurons votre compte"
  },
  "wallets": {
    "list_title": "Vos coffres",
    "create_button": "Nouveau coffre",
    "owned_label": "Vous appartenant",
    "shared_label": "Partagé avec vous",
    "empty_state": "Vous n'avez pas encore de coffre."
  },
  "secrets": {
    "list_title": "Secrets de {{wallet_name}}",
    "create_button": "Ajouter un secret",
    "placeholder_badge": "Placeholder",
    "linked_badge": "Lié"
  },
  "permissions": {
    "read": "Lecture",
    "add": "Ajout",
    "init": "Initialisation",
    "write": "Écriture",
    "remove": "Suppression",
    "share": "Partage"
  },
  "admin": {
    "title": "Mode administrateur",
    "warning_banner": "⚠ Vous êtes en mode administrateur",
    "dashboard": "Tableau de bord",
    "backups": "Sauvegardes",
    "users": "Utilisateurs",
    "audit_log": "Journal d'audit",
    "system": "Système",
    "secret_types": "Types de secrets"
  },
  "secret_types": {
    "list_title": "Types de secrets",
    "new_button": "Nouveau type",
    "current_version": "Courante : v{{version}}",
    "used_by_count": "{{count}} secret",
    "used_by_count_plural": "{{count}} secrets",
    "schema_data_label": "Données du schéma (JSON Schema)",
    "schema_ui_label": "UI du schéma (RJSF)",
    "validate_button": "Valider"
  },
  "errors": {
    "unknown_error": "Une erreur inattendue est survenue",
    "unknown_with_code": "Erreur : {{code}}",
    "wallet_not_found": "Coffre « {{wallet_name}} » introuvable",
    "user_in_quarantine": "Votre compte est en quarantaine jusqu'au {{quarantine_until}}",
    "reverify_required": "Veuillez confirmer votre phrase de passe",
    "reverify_token_invalid_or_expired": "Confirmation expirée, veuillez réessayer",
    "secret_type_already_exists": "Un type avec ce couple (type, sous_type) existe déjà",
    "cannot_delete_system_type": "Les types système ne peuvent pas être supprimés",
    "cannot_delete_current_version": "Impossible de supprimer la version courante. Définissez une autre version comme courante d'abord.",
    "secret_type_in_use": "Ce type est utilisé par {{count}} secrets et ne peut pas être supprimé",
    "invalid_json_schema": "JSON Schema invalide : {{message}}",
    "session_invalidated_by_restore": "Le serveur a été restauré. Veuillez vous reconnecter.",
    "maintenance_in_progress": "Harpocrate est en maintenance. Fin estimée : {{estimated_end_at}}"
  },
  "datetime": {
    "just_now": "à l'instant",
    "minutes_ago": "il y a {{count}} minute",
    "minutes_ago_plural": "il y a {{count}} minutes",
    "hours_ago": "il y a {{count}} heure",
    "hours_ago_plural": "il y a {{count}} heures",
    "days_ago": "il y a {{count}} jour",
    "days_ago_plural": "il y a {{count}} jours"
  }
}
```

### Pluriels

`react-i18next` gère automatiquement les pluriels via le suffixe `_plural` (anglais) ou les CLDR rules (français : `_one`, `_other`, etc.). Pour MVP simple :

```typescript
t('secret_types.used_by_count', { count: 5 })
// EN: "5 secrets"
// FR: "5 secrets"
```

### Page `/account/preferences` (mineur)

Une nouvelle section dans la page Account déjà existante :

```
─── Preferences ───

Language:  [🇬🇧 English ▾]
                ▾
                🇬🇧 English
                🇫🇷 Français
```

## Critères de succès

1. ✅ Migration applique : colonne `preferred_locale` ajoutée avec CHECK
2. ✅ `PATCH /me/preferences` met à jour la locale
3. ✅ `GET /me` retourne `preferred_locale`
4. ✅ Au démarrage UI : ordre localStorage > navigator respecté
5. ✅ Après login : sync DB locale → i18next + localStorage
6. ✅ `<LocaleSwitcher />` change immédiatement la langue
7. ✅ Persistance localStorage et DB simultanée
8. ✅ Toutes les chaînes UI lots 11+12+15 traduites en EN et FR
9. ✅ Codes d'erreur API → traductions correctes
10. ✅ Code d'erreur inconnu → fallback générique avec code visible
11. ✅ Dates formatées selon la locale (fr: 02/05/2026, en: 5/2/2026)
12. ✅ Pluriels EN/FR corrects
13. ✅ Pas de chaînes hardcoded dans le code (aucun `<button>Save</button>` direct)
14. ✅ Switch de langue ne casse pas le state de l'app (formulaires en cours préservés)
15. ✅ Quarantaine, anomalies, reverify modals traduits

## Pièges connus

- **Chaînes oubliées (hardcoded)** : difficile à détecter à l'œil. Utiliser `i18next-parser` ou `eslint-plugin-i18next` pour scan automatique en CI.
- **Pluriels FR vs EN** : règles différentes. `count: 0` → "0 secret" en FR (singulier), "0 secrets" en EN (pluriel). i18next gère mais à tester.
- **Variables avec `'`** : `"L'utilisateur"` casse le JSON. Utiliser `\u2019` (apostrophe typographique) ou échapper proprement.
- **Order des chaînes interpolées** : EN "Created by {{user}}" peut donner FR "Créé par {{user}}" mais aussi "{{user}} l'a créé". Ne pas supposer l'ordre.
- **Format des dates** : la fonction `formatDate` doit prendre la locale courante en paramètre. Si on passe juste `'fr-FR'` en dur, on perd la cohérence avec le state i18next.
- **localStorage rempli au mauvais moment** : si la détection initiale persist dans localStorage avant l'arrivée de `/me`, on peut écraser une préférence DB plus récente. Solution : ne pas persister localStorage sur la détection navigator initiale, attendre que l'user fasse un choix manuel ou que `/me` arrive.
- **Synchro inter-onglets** : si l'user a 2 onglets ouverts et change la locale dans l'un, l'autre ne se met pas à jour automatiquement. Solution post-MVP : `storage` event listener. Au MVP : pas de synchro, c'est OK.
- **i18next loaded async** : si le composant rend avant que les ressources soient chargées, on voit la clé en clair (`secrets.list_title`). Avec `bundle import`, c'est synchrone, pas de souci.
- **Babel/Vite tree-shaking** : les fichiers `fr.json` et `en.json` sont importés statiquement → bundlés dans le main JS. Acceptable (~50 KB total). Si volume explose, code-splitting par namespace.
- **Pas d'i18n des données user** : un wallet nommé "Production secrets" reste en anglais même si l'UI est en FR. Documenté pour l'user.
- **Quarantaine et timestamps** : la traduction `"jusqu'au {{quarantine_until}}"` doit utiliser `formatDate`, pas le timestamp brut. Wrapper côté composant.
- **Tests E2E** : Playwright doit savoir tester en FR et en EN. Variable d'environnement `LOCALE` ou data-testid plutôt que sélecteurs textuels.
- **Codes d'erreur sans entrée i18n** : tomber sur le fallback générique. Bonne pratique : ajouter un test qui parcourt tous les codes d'erreur backend connus et vérifie qu'ils ont une entrée FR ET EN.

## Tests

### Backend

- `test_patch_preferences_locale_valid`
- `test_patch_preferences_locale_invalid_400`
- `test_get_me_returns_preferred_locale`

### Frontend (Vitest unit)

- `test_localeSwitcher_changes_i18n`
- `test_setLocale_persists_to_localStorage`
- `test_setLocale_calls_api_when_logged_in`
- `test_syncLocaleFromUser_overrides_localStorage`
- `test_translateApiError_known_code`
- `test_translateApiError_unknown_fallback`
- `test_formatDate_fr_format`
- `test_formatDate_en_format`
- `test_pluralization_works`

### Frontend (Playwright E2E)

- `test_default_language_detection`
- `test_switch_to_french_persists_after_reload`
- `test_login_syncs_user_preferred_locale`
- `test_all_pages_render_in_french`
- `test_all_pages_render_in_english`
- `test_error_messages_translated`

### CI lint

- `i18next-parser` détecte des clés hardcoded → CI fail si trouvé
- Test : tous les codes d'erreur backend ont une entrée FR et EN

## Ce qui suit

Le **lot 17** branche les types et schemas du lot 15 sur les secrets, avec rendu RJSF dynamique.
