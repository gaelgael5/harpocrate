# Lot 12b — UI Admin core : dashboard + backups

> **Prérequis** : Lots 00-11, 12a.

## Objectif

Construire l'**interface web admin** pour piloter Harpocrate depuis le navigateur. Ce lot livre le squelette admin, le dashboard, et la page complète de gestion des backups (liste, création, download, upload, restore wizard, mode maintenance).

## Dépendances

- Lots 00-11, 12a

## Périmètre

### Inclus

- Layout admin distinct du layout user (couleur d'avertissement, mention "Admin mode")
- Routing `/admin/*` protégé par rôle `harpocrate-admin`
- Dashboard `/admin` avec tuiles de stats
- Page `/admin/backups` complète :
  - Tableau des backups locaux
  - Bouton "Create backup now"
  - Bouton "Upload from computer"
  - Page détail d'un backup
  - Modale wizard de restore en 4 étapes
  - Bouton verify
  - Bouton download
  - Suppression avec reverify
- Mode maintenance : toggle + countdown + diffusion WebSocket aux clients
- Indicateur de mode maintenance dans la barre de navigation

### Exclus

- Pas de gestion users (lot 12c)
- Pas d'audit log admin (lot 12c)
- Pas de page system / env (lot 12c et 12e)
- Pas d'UI de backup distant (lot 13)

## Spécifications fonctionnelles

### Routing et accès

```
/admin                   → Dashboard admin
/admin/backups           → Liste des backups
/admin/backups/{id}      → Détail d'un backup
```

Tous protégés par :
- JWT valide
- Rôle `harpocrate-admin` dans `realm_access.roles` du JWT
- `crypto unlocked` (pas obligatoire pour admin, mais recommandé pour cohérence)

Si rôle absent → redirection vers `/` avec toast "Admin access required".

### Layout admin

```
┌──────────────────────────────────────────────────────────┐
│ [Harpocrate] [Wallets] [Account] | ⚠ ADMIN MODE | Logout │  ← bandeau distinct
├──────────────────────────────────────────────────────────┤
│ Side nav                  │  Content                     │
│ ─────────                 │                              │
│ ▸ Dashboard               │                              │
│ ▸ Backups                 │  (page courante)             │
│ ▸ Users                   │                              │
│ ▸ Audit log (global)      │                              │
│ ▸ System                  │                              │
│ ▸ Maintenance             │                              │
└──────────────────────────────────────────────────────────┘
```

Couleur dominante : orange/jaune sombre (Mantine `orange` color palette) pour distinguer visuellement de la zone utilisateur classique.

### Page `/admin` — Dashboard

Quatre tuiles principales :

```
┌──────────────────────┬──────────────────────┐
│ Stats globales       │ Dernier backup       │
│                      │                      │
│ Users:        4      │ 2026-05-02 14:23     │
│ Wallets:      12     │ Size:  12.3 MB       │
│ Secrets:      87     │ Status: ✓ verified   │
│ API keys:     8 act  │                      │
│ Audit:    2,340      │ [Create backup now]  │
└──────────────────────┴──────────────────────┘
┌──────────────────────┬──────────────────────┐
│ Santé système        │ Activité récente     │
│                      │                      │
│ DB: ✓                │ 14:20 secret.read    │
│ Keycloak: ✓          │ 14:18 wallet.created │
│ Backup dest: ✓       │ 14:10 user.unlock    │
│ Maintenance: off     │ 13:45 api_key.created│
│                      │ 13:30 secret.populated│
└──────────────────────┴──────────────────────┘
```

Tuile cliquable → page détaillée correspondante.

### Page `/admin/backups`

Tableau principal avec colonnes : **Created**, **Size**, **Created by**, **Description**, **Type** (auto/manual/imported), **Actions**

Actions par ligne :
- 👁 View details
- ⬇ Download (avec confirmation)
- ↻ Verify (modal demande clé `age`)
- ⏪ Restore (lance le wizard)
- 🗑 Delete (avec reverify)

Boutons globaux en haut :
- ➕ **Create backup now** (modal description)
- ⬆ **Upload from computer** (drop zone)
- ⚙ **Backup settings** (lien vers `/admin/system`)

Filtres :
- Date range
- Type (manual / auto / imported)
- Created by

### Modal "Create backup now"

```
┌─────────────────────────────────────────────┐
│ Create a new backup                         │
│                                             │
│ This will create a full backup of the      │
│ database, encrypted with your admin age key.│
│                                             │
│ Description (optional):                     │
│ ┌─────────────────────────────────────────┐ │
│ │ Pre-migration backup                    │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ Estimated size: ~12 MB                      │
│ Estimated duration: ~10 seconds             │
│                                             │
│              [Cancel]  [Create backup]      │
└─────────────────────────────────────────────┘
```

Pendant la création : spinner + barre de progression (polling sur le backup en cours).

### Page `/admin/backups/{id}` — Détail

Affichage du manifest :
- Nom, date, taille, checksum
- Stats : compte users/wallets/secrets/api_keys/audit
- Description, créateur
- Type (manual/imported/auto)
- `age` recipient (avec fingerprint match check si plusieurs clés possibles)
- Format version, schema version

Actions :
- ⬇ Download
- ↻ Verify (modal)
- ⏪ Restore... (wizard)
- 🗑 Delete

### Wizard de restore en 4 étapes

Step 1 — Confirmation initial

```
⚠️ Restoring will REPLACE the entire database with this backup.

  Backup: harpocrate-backup-2026-05-02-14-23-00.tar.age
  Created: 2026-05-02 14:23 UTC
  Stats: 4 users, 12 wallets, 87 secrets

  All current data not in this backup WILL BE LOST.
  All active sessions will be invalidated.

  [Cancel]  [I understand, continue →]
```

Step 2 — Verification (saisie clé age)

```
Enter your admin age private key to decrypt this backup.
This key is never persisted.

  ┌─────────────────────────────────────────────┐
  │ AGE-SECRET-KEY-1QYQSZQ...                   │
  │                                             │
  │                                             │
  └─────────────────────────────────────────────┘

  □ Read from file instead

  [← Back]  [Verify and preview →]
```

Sur clic : appel à `POST /admin/backups/{id}/verify`. Si OK, affichage des stats lues du manifest déchiffré.

Step 3 — Confirmation textuelle + reverify

```
Type the following to confirm:

  RESTORE harpocrate-backup-2026-05-02-14-23-00

  ┌─────────────────────────────────────────────┐
  │                                             │
  └─────────────────────────────────────────────┘

  Maintenance mode: ☑ Auto-enable during restore (recommended)

  Now confirm your passphrase one more time:

  ┌─────────────────────────────────────────────┐
  │                                             │
  └─────────────────────────────────────────────┘

  [← Back]  [Execute restore]
```

Le bouton "Execute restore" appelle `POST /admin/backups/{id}/restore` avec :
- `age_private_key` saisie en step 2
- `confirmation` saisie en step 3
- header `X-Reverify-Token` obtenu via `/me/reverify`

Step 4 — Progression et résultat

```
🔄 Restore in progress...

  ✓ Maintenance mode enabled
  ✓ Backup decrypted
  ✓ Checksums verified
  ✓ Schema dropped
  ✓ Dump replayed
  ✓ Session epoch rotated
  ✓ Maintenance mode disabled

✅ Restore completed successfully

  Restored from: harpocrate-backup-2026-05-02-14-23-00
  New session epoch: 43 (was 42)
  Env restore file: /var/lib/harpocrate/.env.restore.1714660080

  Next steps:
  1. Review env restore file (SSH on server)
  2. All users will need to reconnect
  3. Verify your secrets are accessible

  [Done — return to backups]
```

### Mode maintenance

Bandeau global en haut du site (visible par tous les users) si actif :

```
⚠️ MAINTENANCE IN PROGRESS — Read-only access until 14:35 UTC
```

Pour l'admin, page `/admin/maintenance` avec :

```
Maintenance mode

Status: ⚠ ACTIVE
Started: 2026-05-02 14:30 UTC by gael@yoops.org
Reason: "Database restore in progress"
Estimated end: 2026-05-02 14:35 UTC

[Disable maintenance now]
```

Ou si inactif :

```
Maintenance mode

Status: ✓ OFF

Reason for enabling:
┌─────────────────────────────────────────────┐
│                                             │
└─────────────────────────────────────────────┘

Delay before effect (seconds): [30]
Estimated duration (minutes):  [5]

[Enable maintenance]
```

### Diffusion WebSocket / polling

Tous les clients UI (admin + user) écoutent le statut maintenance :
- Au login : check `GET /v1/maintenance/status` (public)
- Polling toutes les 30s ou WebSocket
- Si activé : afficher bandeau + désactiver toutes les actions mutatives en local
- Si countdown : afficher compte à rebours

## Spécifications techniques

### Structure ajoutée

```
frontend/src/
├── routes/admin/
│   ├── AdminLayout.tsx
│   ├── AdminDashboard.tsx
│   ├── BackupList.tsx
│   ├── BackupDetail.tsx
│   ├── BackupCreate.tsx       # modal
│   ├── BackupRestore.tsx      # wizard
│   ├── BackupUpload.tsx       # drop zone
│   ├── Maintenance.tsx
│   └── components/
│       ├── BackupStatusBadge.tsx
│       ├── MaintenanceBanner.tsx
│       └── RestoreWizard/
│           ├── Step1Confirm.tsx
│           ├── Step2VerifyKey.tsx
│           ├── Step3Confirm.tsx
│           └── Step4Progress.tsx
├── api/admin/
│   ├── backups.ts
│   ├── maintenance.ts
│   └── system.ts
├── stores/
│   └── admin.ts               # pas grand-chose, juste maintenance status
└── hooks/
    ├── useAdminRole.ts
    └── useMaintenanceStatus.ts
```

### Hook `useAdminRole`

```typescript
export function useAdminRole(): boolean {
  const jwt = useAuthStore(s => s.jwt);
  if (!jwt) return false;
  const decoded = decodeJwt(jwt);
  const roles = decoded.realm_access?.roles || [];
  return roles.includes('harpocrate-admin');
}
```

### Hook `useMaintenanceStatus`

```typescript
export function useMaintenanceStatus(): MaintenanceStatus {
  const [status, setStatus] = useState<MaintenanceStatus>({ active: false });

  useEffect(() => {
    const fetchStatus = () => api.get('/v1/maintenance/status').then(setStatus);
    fetchStatus();
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, []);

  return status;
}
```

### Route guard

```typescript
function RequireAdmin({ children }: { children: ReactNode }) {
  const isAdmin = useAdminRole();
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

// Routing
<Route path="/admin/*" element={<RequireAdmin><AdminLayout /></RequireAdmin>}>
  <Route index element={<AdminDashboard />} />
  <Route path="backups" element={<BackupList />} />
  <Route path="backups/:id" element={<BackupDetail />} />
  ...
</Route>
```

### Theme admin distinct

```typescript
// Dans AdminLayout
<MantineProvider theme={createTheme({
  primaryColor: 'orange',
  defaultRadius: 'sm',
  // ...
})}>
  {/* ... */}
</MantineProvider>
```

### Backup upload streaming

```typescript
async function uploadBackup(file: File, onProgress: (pct: number) => void) {
  const formData = new FormData();
  formData.append('file', file);

  return axios.post('/v1/admin/backups/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (e.total) onProgress((e.loaded / e.total) * 100);
    },
  });
}
```

### Backup download streaming

```typescript
async function downloadBackup(id: string, filename: string) {
  const response = await axios.get(`/v1/admin/backups/${id}/download`, {
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(response.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.URL.revokeObjectURL(url);
}
```

### Restore wizard gestion d'erreur

Chaque étape peut échouer, afficher l'erreur clairement et permettre de revenir en arrière. La clé `age` saisie en step 2 est gardée en state du composant (pas dans Zustand store qui serait persisté).

```typescript
function RestoreWizard({ backupId }: { backupId: string }) {
  const [step, setStep] = useState(1);
  const [agePrivateKey, setAgePrivateKey] = useState('');
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [confirmation, setConfirmation] = useState('');

  // ...

  // Important : effacer la clé après succès
  useEffect(() => {
    return () => {
      setAgePrivateKey('');
    };
  }, []);

  return ...;
}
```

## Critères de succès

1. ✅ Layout admin distinct visuellement
2. ✅ Routing `/admin/*` accessible seulement avec rôle Keycloak
3. ✅ Dashboard affiche stats correctes et dernier backup
4. ✅ "Create backup now" déclenche un backup avec progress
5. ✅ Liste des backups paginée et filtrable
6. ✅ Download fonctionne (fichier `.tar.age` reçu sur le poste)
7. ✅ Upload depuis poste fonctionne
8. ✅ Verify avec mauvaise clé → erreur dans le wizard
9. ✅ Restore wizard 4 étapes complet
10. ✅ Confirmation textuelle exacte requise
11. ✅ Reverify token demandé en step 3
12. ✅ Mode maintenance enable/disable
13. ✅ Bandeau maintenance visible côté user
14. ✅ Toutes les UI désactivent les mutations en mode maintenance
15. ✅ Après restore réussi, page de résultat affichée

## Pièges connus

- **Clé `age` en RAM** : ne JAMAIS la mettre dans Zustand persist, seulement dans state local du composant. La nettoyer au unmount.
- **Re-render perdant la clé** : si le wizard re-render (suite à une erreur), la clé saisie est perdue. C'est intentionnel — on préfère que l'admin la re-saisisse plutôt que de la garder accidentellement.
- **Download de gros backup** : si > 100 MB, le navigateur peut être lent. Mantine `Notification` avec progress.
- **Upload de gros fichier** : pareil, `axios` `onUploadProgress`.
- **Polling maintenance status 30s** : la latence avant détection peut atteindre 30s. Acceptable. Pour faire mieux, WebSocket.
- **Rôle `harpocrate-admin` absent** : vérifier d'abord côté UI (cacher le menu) ET côté serveur (refus 403). Jamais que côté UI.
- **`Content-Disposition` filename** : caractères safe seulement (`harpocrate-backup-{ts}.tar.age` est OK).
- **Erreur du wizard step 4** : si le restore plante en milieu, la base peut être dans un état incohérent. Afficher message clair "Database may be in inconsistent state, contact your administrator. Maintenance mode is still active." et NE PAS désactiver la maintenance automatiquement.
- **Dashboard refresh** : utiliser SWR ou TanStack Query pour cache + revalidation. Pas de fetch à chaque mount.

## Tests Playwright

- `test_admin_route_blocked_for_non_admin`
- `test_admin_dashboard_loads`
- `test_create_backup_flow`
- `test_list_backups_pagination`
- `test_download_backup`
- `test_upload_backup`
- `test_verify_wrong_key_shows_error`
- `test_restore_wizard_full_flow`
- `test_restore_wrong_confirmation_blocked`
- `test_maintenance_toggle`
- `test_maintenance_banner_visible_on_user_pages`
- `test_session_invalidated_after_restore`

## Ce qui suit

Le **lot 12c** ajoute les pages admin pour users, audit log global, system info, maintenance détaillée.
