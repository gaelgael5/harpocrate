# Fragment — Authentification OIDC

> Source : globals › « Fichier d'instructions — spécificités Authentification OIDC » (révision 2026-09-02).
> Standard de référence : globals › « STANDARD — Authentification OIDC & liaison d'identité » (2026-09-15).
> Déclencheur : avant de modifier `backend/app/core/security.py`, `admin_auth.py`,
> `jwks_cache.py`, `services/auth.py`, `services/identity_governance.py`,
> `api/v1/auth*.py`, `config_keycloak.py`, `identity_management.py`, ou `frontend/src/lib/oidc.ts`.

### Authentification

- Fournisseur d'identité de la maison, royaume commun, **client dédié au projet**
- Rôles portés par le fournisseur, jamais recopiés en dur dans le code
- Le secret client vient du gestionnaire de secrets, jamais d'un fichier versionné
- **Fail closed** : une route sans autorisation explicite est refusée, pas ouverte

## Spécifique Harpocrate

- Keycloak en **client public PKCE** (`oidc-client-ts` côté front) : **pas de `client_secret`**,
  ni en base ni dans le `.env`. Ne pas en introduire.
- Admin : `require_admin` (claim `realm_access.roles` contre `HARPOCRATE_ADMIN_ROLE_NAME`).
- **Break-glass admin local** (`HARPOCRATE_ADMIN_LOCAL_*`, `api/v1/auth_local.py`,
  `services/local_admin_bootstrap.py`) : porte de secours si l'IdP est indisponible. Rate
  limité (`rate_limit_dep`). Ne jamais l'étendre à des utilisateurs non admin.
- Désactivation d'un compte : vérifiée dans `users_repo.get_by_keycloak_sub` (lève
  `UserDisabledError`, mappé en 403 par le handler global) — **pas** dans `require_jwt_user`.

### Écarts constatés avec le STANDARD OIDC (à signaler, pas à « corriger » d'office)

Ces points contredisent le standard global ; ils relèvent d'une décision de l'utilisateur,
à cadrer dans une tâche dédiée :

1. **Rôle admin lu dans le token** (`admin_auth.py` lit `realm_access.roles`) — le standard
   (§1, §9) veut les rôles en base locale, le token n'étant qu'une suggestion au premier
   provisionnement. La structure `realm_access.roles` est propre à Keycloak (§10).
2. **Nom du fournisseur dans la configuration et le schéma** : `HARPOCRATE_KEYCLOAK_*`,
   colonne `users.keycloak_sub`, `api/v1/config_keycloak.py` — le standard (§10.5) demande
   `OIDC_*`.
3. **Ancrage `(provider, external_subject)`, pas `(issuer, sub)`** : la table
   `user_external_identities` (migration `002_governance_identity.sql`) qualifie le `sub`
   par un libellé `provider`, pas par l'URL d'émetteur (§3, §10.2) ; `users.keycloak_sub`
   subsiste en parallèle.

Tant que l'utilisateur n'a pas tranché : ne pas propager ces motifs dans du code neuf
(nouvelle lecture de rôle depuis le token, nouveau nom `keycloak_*`), et ne pas les réécrire
au passage.

## Pièges connus

**Le login se dérive, il ne se lit pas.** Un identifiant utilisateur construit depuis une revendication brute (courriel, nom d'affichage) change quand l'utilisateur change d'adresse, et deux personnes peuvent produire le même. Dériver un login normalisé, le valider par regex, et le figer.

**Une revendication de rôle absente n'est pas un rôle vide** : c'est un jeton qu'on n'a pas su lire. Traiter les deux pareil ouvre l'accès à qui présente un jeton mal formé.

**Le domaine du cookie de session décide de ce qui reste connecté.** Un sous-domaine oublié déconnecte l'utilisateur à chaque navigation, et un domaine trop large expose la session à des services voisins.

**Une redirection après connexion est une entrée utilisateur.** Non validée, elle envoie l'utilisateur authentifié vers un site tiers.

## Part de checklist

- [ ] Aucune route sensible atteignable sans autorisation, et le cas est **testé**
- [ ] Aucun rôle codé en dur qui doublerait ce que porte le fournisseur
- [ ] Le secret client n'apparaît ni dans le dépôt, ni dans un log, ni dans une image
- [ ] Les cibles de redirection après connexion sont validées contre une liste connue
- [ ] Aucun nouveau motif `keycloak_*` ni lecture de rôle depuis le token ajoutés
