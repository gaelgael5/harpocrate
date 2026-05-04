# Harpocrate — Design Brief (frontend-design skill)

## Contexte produit

**Harpocrate** est un gestionnaire de secrets E2E zero-knowledge : les valeurs des secrets ne quittent jamais le navigateur en clair. Le serveur ne voit que des blobs chiffrés (AES-256-GCM). La cryptographie est entièrement côté client (WebCrypto API + Argon2id WASM).

**Utilisateurs cibles :** développeurs, équipes DevOps, security engineers. Profil technique élevé. Habitués à des outils comme 1Password, HashiCorp Vault, Bitwarden ou Infisical.

**Valeur centrale :** confiance absolue — personne, même l'admin du serveur, ne peut lire tes secrets. C'est la promesse fondamentale de l'interface.

---

## Pages & flux existants (React 18 + Mantine v7 + Vite)

### Flux d'authentification
- **LoginPage** — choix entre OIDC Keycloak ou compte admin local (username/password)
- **OAuthCallbackPage** — callback OIDC silencieux
- **UnlockPage** — saisie de la passphrase pour dériver la clé RSA (Argon2id → AES-GCM → clé privée en RAM). Écran critique de sécurité, affiché à chaque session.
- **FirstLoginPage** — génération des clés RSA + chiffrement avec la passphrase (onboarding)

### Espace utilisateur
- **WalletsPage** — liste des "wallets" (coffres-forts), cards avec nom/tags/compteurs. Point d'entrée principal.
- **WalletDetailPage** — arborescence des secrets d'un wallet. Navigation par dossier (breadcrumb), grille dossiers + liste secrets. Bouton "Nouveau secret".
- **WalletNewPage** — formulaire création wallet
- **WalletImportPage** — import d'un wallet depuis un fichier JSON chiffré
- **SecretDetailPage** — détail d'un secret : valeur chiffrée (déchiffrée à la demande), métadonnées, tags, historique de version, partages. Bouton "Edit".
- **SecretNewPage** — création d'un secret : nom, valeur (texte libre ou formulaire JSON Schema via RJSF si un type est sélectionné)
- **GrantsPage** — partage d'un wallet avec d'autres users (bitmap de permissions : READ, WRITE, ADD, REMOVE, INIT)
- **ApiKeysPage** — gestion des clés API (tokens `hrpv_*` pour l'automation)
- **AuditLogPage** — journal d'audit paginé (qui a fait quoi, quand)
- **AccountPage** — paramètres compte : changement de passphrase, recovery key, locale
- **ExportAllPage** — export global de tous les wallets en clair (parachute migration)
- **IntegrationPage** — téléchargement du SDK Python + CLI bash, snippets de code

### Espace admin (rôle `harpocrate-admin`)
- **AdminBackupsPage** — gestion des backups PostgreSQL (local + S3), scheduling, restore
- **AdminSnapshotsPage** — snapshots automatiques (cron + rotation GFS)
- **AdminSecretTypesPage** — catalogue des types de secrets (JSON Schema 2020-12)
- **AdminSecretTypeCreatePage** — création d'un type avec Monaco editor (JSON Schema + UI Schema RJSF)
- **AdminSecretTypeDetailPage** — détail d'un type, gestion des versions de schéma
- **AdminUsersPage** — liste des users, bootstrap, désactivation
- **AdminSystemPage** — infos système (compteurs), état de la DB
- **AdminEnvPage** — exposition des variables d'environnement serveur (read-only)

### Composants globaux
- **Layout** — AppShell Mantine : header (logo, LocaleSwitcher FR/EN, theme toggle 🌙/☀️, lock 🔒, logout) + navbar gauche (220px) + main content
- **LocaleSwitcher** — bascule FR/EN persistée en DB
- **TypedSecretForm** — formulaire RJSF généré depuis JSON Schema (widget PasswordWidget custom)
- **JsonEditorMonaco** — éditeur Monaco intégré pour éditer des JSON Schemas
- **AppsMenu** — launcher vers d'autres apps du même écosystème

---

## État actuel du design

L'interface utilise **Mantine v7 avec son thème par défaut** sans personnalisation marquée :
- Typographie : font système par défaut
- Couleurs : bleu Mantine standard (#228be6)
- Layout : navbar simple liste de liens, cards avec bordure standard
- Pas d'identité visuelle propre — ressemble à tout autre app Mantine
- Le thème dark/light fonctionne mais les deux modes sont génériques

**Ce qui manque :**
- Une identité visuelle forte liée à la sécurité et à la cryptographie
- Des moments "wow" sur les écrans critiques (Unlock, WalletDetail)
- Une cohérence typographique avec caractère
- Des micro-interactions qui rassurent sur les opérations crypto

---

## Direction créative souhaitée

**Ton :** sécurité, confiance, précision technique. Ni banquier ennuyeux, ni startup flashy. Quelque chose entre **outil de sécurité professionnel** et **interface hacker élégante**.

**Références d'inspiration :**
- HashiCorp Vault (densité, sérieux)
- Linear (élégance, rapidité, dark-first)
- Raycast (minimalisme avec personnalité)
- Terminal / crypto tools (monospace, précision)

**Ce qui doit être mémorable :**
- L'écran **Unlock** : c'est le rituel d'accès au coffre. Doit inspirer confiance et gravité.
- Les **WalletCards** : doivent communiquer clairement la notion de "coffre sécurisé"
- La **navbar admin** : doit se distinguer visuellement de l'espace user

**Contraintes techniques :**
- Framework : React 18 + **Mantine v7** (composants existants à conserver)
- Thème : personnalisation via `MantineProvider` + `createTheme()`
- Dark mode natif : le toggle est déjà en place, le redesign doit supporter les deux
- i18n : tous les labels via `useTranslation()`, pas de strings hardcodées
- Pas de refonte des pages une par une — priorité au **thème global** + **Layout** + les 3 pages les plus visitées (UnlockPage, WalletsPage, WalletDetailPage)
- Performance : pas de librairies d'animation lourdes (le bundle est déjà ~1.4MB)

---

## Priorité de livraison

1. **Thème Mantine global** (`frontend/src/lib/theme.ts`) — couleurs, typographie, radius, shadows, composants overrides
2. **Layout.tsx** — navbar redesignée, header
3. **UnlockPage** — l'écran le plus vu, l'identité du produit
4. **WalletsPage** — les cards wallets
5. *(optionnel)* WalletDetailPage — navigation dossiers/secrets
