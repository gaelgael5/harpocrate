# Configurer une connexion Google Drive pour les backups Harpocrate

Ce guide explique comment créer une application OAuth dans Google Cloud Console,
récupérer un Client ID + Client Secret, et finaliser la connexion côté Harpocrate.

Compter ~10 minutes la première fois.

## Prérequis

- Un compte Google (perso ou Workspace) qui hébergera les backups Drive.
- Accès admin à votre instance Harpocrate (rôle Keycloak `harpocrate-admin` ou
  équivalent mode local-admin).

## 1. Créer un projet Google Cloud

1. Ouvrir https://console.cloud.google.com/
2. En haut, cliquer sur le sélecteur de projet → **"Nouveau projet"**
3. Donner un nom (ex : `harpocrate-backup`) → **Créer**
4. Attendre que le projet soit actif (icône en haut à droite).

## 2. Activer l'API Google Drive

1. Menu hamburger (☰) → **APIs & Services** → **Library**
2. Chercher `Google Drive API` → cliquer → **Enable**

## 3. Configurer l'OAuth consent screen

1. **APIs & Services** → **OAuth consent screen**
2. User Type :
   - **External** si compte Google grand public (gmail.com)
   - **Internal** si Google Workspace (votre-domaine.com) — recommandé si dispo
3. **App information** : remplir au minimum :
   - App name (ex: `harpocrate-instance-yoops`)
   - User support email (votre adresse)
   - Developer contact (votre adresse)
4. **Scopes** → **Add or remove scopes** → ajouter manuellement le scope :
   ```
   https://www.googleapis.com/auth/drive.file
   ```
   (Un seul scope, **non-sensitive** côté Google. Pas de review formelle requise.)
5. **Test users** (uniquement en mode External, statut Testing) → ajouter votre
   adresse Google + celles des autres admins potentiels (limite 100 users en
   mode Testing).
6. **Save and continue** sur chaque étape.

## 4. Créer le Client OAuth (Web application)

1. **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**
2. **Application type** : **Web application**
3. **Name** : libre (ex: `harpocrate-prod-eu`)
4. **Authorized redirect URIs** → cliquer **+ Add URI** → coller exactement la
   valeur affichée dans le formulaire Harpocrate (bouton 📋 pour copier).
   Exemple :
   ```
   https://votre-harpocrate.example.com/v1/admin/backup-remotes/oauth/gdrive/callback
   ```
   **Attention** : la valeur doit être strictement identique (schéma, host, path,
   pas de slash final). Sinon Google refusera le flow OAuth avec
   `redirect_uri_mismatch`.
5. **Create** → une popup affiche **Client ID** et **Client Secret**. Copier les
   deux (vous pourrez les retrouver plus tard dans la liste des credentials).

## 5. Finaliser dans Harpocrate

1. Ouvrir l'UI Harpocrate → page **Connexions distantes** → **Ajouter une
   connexion**
2. **Type** : sélectionner **Google Drive**
3. Remplir :
   - **Nom** : libre (ex: `Backups perso`)
   - **Client ID** : coller la valeur de l'étape 4.5
   - **Client Secret** : coller la valeur de l'étape 4.5
   - **Nom du dossier sur Drive** : libre (défaut `Harpocrate Backups`)
4. Cliquer **"Autoriser avec Google"** → une popup s'ouvre vers
   `accounts.google.com`
5. Choisir le compte Google qui contiendra les backups
6. Si mode External Testing → écran "Google hasn't verified this app" →
   **Continue** (c'est normal car l'app n'est pas en Production).
7. Accepter les permissions : Harpocrate ne demande que `drive.file` (accès aux
   fichiers qu'il crée lui-même, pas à l'ensemble de votre Drive)
8. La popup se ferme automatiquement → le modal Harpocrate affiche
   **✓ Autorisé en tant que `votre-email@gmail.com`**
9. Cliquer **"Sauvegarder"** → la connexion apparaît dans la liste.

## Limitations à connaître

- **Mode Testing Google** : le refresh token est forcé à expirer après **7 jours
  d'inactivité**. Si Harpocrate backupe régulièrement, le refresh maintient le
  token vivant. Si vous avez une fenêtre d'inactivité > 7 jours, le token sera
  révoqué et il faudra cliquer **Re-autoriser** sur la connexion.
- **Mode Production** : pour usage durable, faire passer l'app en "Production"
  via Google Cloud Console. La verification est **automatique** sur le scope
  non-sensitive `drive.file` (généralement instantanée).
- **Mono-compte** : les backups vont dans le Drive du compte qui a autorisé.
  Pour changer de compte, supprimer la connexion et la recréer.
- **Pas de listing dans Harpocrate** : pour voir/télécharger les backups,
  ouvrir directement Google Drive (dossier `Harpocrate Backups` en racine).

## Re-autorisation

Si vous voyez **"Ré-autorisation requise"** à côté d'une connexion Drive, c'est
que le refresh token a été révoqué :
- Soit côté Google : Account → Security → Third-party apps → vous avez retiré
  Harpocrate.
- Soit délai d'inactivité atteint en mode Testing.

Cliquer sur **"Ré-autoriser"** → le même flow OAuth est relancé. Pas besoin de
re-saisir Client ID/Secret, ils sont conservés en DB.

## Dépannage

| Erreur côté Harpocrate | Cause probable | Solution |
|---|---|---|
| `redirect_uri_mismatch` à la popup Google | URI dans Google Cloud Console ≠ URI envoyée par Harpocrate | Re-coller exactement la valeur du champ "Redirect URI" du modal |
| `invalid_client` (popup) | Client Secret faux ou expiré | Régénérer le Secret dans Google Cloud Console → mettre à jour la connexion |
| `access_denied` (popup) | Vous avez cliqué "Cancel" sur le consent | Recommencer |
| `Re-autorisation requise` (table) | refresh_token révoqué | Bouton "Ré-autoriser" |
| `drive_storage_full` (push backup) | Quota Drive dépassé | Libérer de l'espace côté Drive ou changer de compte |
