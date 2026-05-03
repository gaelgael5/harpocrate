# Migration vers le coffre Harpocrate

## Contexte

Cette application stocke actuellement des secrets (API keys, mots de passe, tokens, certificats) directement dans son code, dans des fichiers `.env`, dans des configs en clair, ou via une logique de gestion de secrets ad-hoc ou dans openobao. **Tout cela doit disparaître.**

Désormais, les secrets sont centralisés dans **Harpocrate**, un coffre-fort end-to-end encrypted accessible via API REST.

Ta mission : nettoyer toute la logique existante de gestion de secrets et la remplacer par une consommation propre du coffre.


## Le coffre Harpocrate

**URL** : dev : `https://192.168.10.123` — prod : `https://vault.yoops.org`

**Spec OpenAPI** : `GET /v1/openapi-api-key.json` (ou Swagger UI sur `GET /v1/api-docs`)

Commence par lire ce spec OpenAPI. Il décrit tous les endpoints utilisables avec une API key et leurs schémas de requête/réponse. Les SDKs officiels sont téléchargeables depuis `GET /v1/sdk/python-wheel` (wheel Python) et `GET /v1/sdk/cli-bash` (CLI Bash).


## Modèle cryptographique (à comprendre avant de coder)

Harpocrate est **end-to-end encrypted** : le serveur ne stocke et ne déchiffre jamais les valeurs en clair.

- L'authentification se fait avec une **API key** au format `hrpv_1_*`
- Ce token contient deux composants distincts encodés dans sa structure : un secret d'authentification (utilisé par le serveur pour valider l'appel) et une clé de déchiffrement (utilisée localement par le client pour déchiffrer les réponses)
- Le token complet `hrpv_1_*` est envoyé dans le header `Authorization: Bearer` pour l'authentification
- Quand tu lis un secret, le serveur renvoie une valeur **chiffrée en AES-GCM**
- Tu déchiffres localement avec la clé de déchiffrement extraite du token — cette clé ne quitte jamais la RAM du client

**Tu ne fais jamais ce travail à la main**. Tu utilises le SDK officiel qui gère l'extraction des composants du token, l'authentification, le déchiffrement local, et les bonnes pratiques de sécurité.


## SDK officiel

Télécharge le SDK adapté au langage du projet depuis le coffre lui-même :

| Langage | Endpoint de téléchargement | Usage |
|---|---|---|
| Python | `GET /v1/sdk/python-wheel` | `pip install harpocrate-*.whl` |
| Bash / Shell | `GET /v1/sdk/cli-bash` | `harpocrate-cli get SECRET_NAME` |

Si le projet est dans un langage non couvert par un SDK officiel, fais des appels directs à l'API décrite dans le spec OpenAPI (`/v1/openapi-api-key.json`). Dans ce cas : envoie le token complet `hrpv_1_*` dans `Authorization: Bearer`, et utilise la clé de déchiffrement extraite du token (champ `dkey_b64url` selon le format documenté dans le spec) pour déchiffrer les `encrypted_value` reçues avec AES-256-GCM.


## Convention de référence aux secrets

Dans tout le code et toutes les configs de l'application, les références aux secrets utilisent ce format :

Secret à la racine d'un wallet :
```
${vault://<identifiant_api_key>:<nom_du_secret>}
```

Secret dans un sous-répertoire (chemin virtuel) :
```
${vault://<identifiant_api_key>:<chemin>/<nom_du_secret>}
```

**Exemples :**
```yaml
# docker-compose.yml
environment:
  GITHUB_TOKEN: ${vault://api1:GITHUB_TOKEN}
  ANTHROPIC_API_KEY: ${vault://api1:ANTHROPIC_API_KEY}
  DATABASE_PASSWORD: ${vault://api2:POSTGRES_PASSWORD}
  # Avec sous-répertoire (organisation par identité ou contexte) :
  PERSONAL_OPENAI_KEY: ${vault://api1:gaelgael5@gmail.com/OPENAI_API_KEY}
```

```python
# config.py
config = {
    "github_token": "${vault://api1:GITHUB_TOKEN}",
    "anthropic_api_key": "${vault://api1:ANTHROPIC_API_KEY}",
}
```

- `vault` = source de résolution (Harpocrate)
- `<identifiant_api_key>` = alias logique local à l'application (voir section suivante)
- `<chemin>/<nom_du_secret>` = chemin virtuel dans le wallet, séparateur `/`

L'alias n'est pas transmis à Harpocrate — c'est un alias purement local. Le wallet n'a pas besoin d'être précisé : chaque API key Harpocrate est scopée à un seul wallet, l'association est implicite.

### Découverte de l'arborescence

Pour lister les secrets et sous-répertoires disponibles depuis un wallet :
- `GET /v1/wallets/{wallet_id}/tree?path=/` — retourne les sous-dossiers directs et le nombre de secrets à un niveau donné
- `GET /v1/wallets/{wallet_id}/secrets?path=/chemin/` — retourne les secrets directs d'un répertoire (non récursif)
- `GET /v1/wallets/{wallet_id}/secrets` — retourne tous les secrets du wallet (liste plate, paginée)


## Table de configuration des API keys

L'application doit maintenir une **table de configuration locale** des API keys Harpocrate qui lui sont attribuées.

Cette table associe chaque identifiant logique à ses credentials :

| Champ | Description |
|---|---|
| `identifier` | Alias logique dans `${vault://...}` (ex: `api1`, `github`, `prod-shared`) |
| `url` | URL du coffre Harpocrate |
| `token` | Token API key complet au format `hrpv_1_*` |
| `description` | Texte libre pour rappeler à quoi sert cette key |

**À toi de décider** comment matérialiser cette table en fonction du projet :

- Application stateless avec config YAML/TOML/JSON → fichier de config dédié
- Application déjà connectée à une base SQL → table dédiée
- Application avec un secrets manager local (Vault Agent, sealed secrets, etc.) → adapter à ce système

Quel que soit le format, **cette table contient des credentials sensibles** :
- Permissions strictes sur le fichier (`chmod 600` si fichier)
- Pas de commit dans git
- Backup conjoint avec les autres secrets de l'application
- Si possible, chiffrement au repos


## Loader de résolution

L'application doit avoir un **mécanisme de résolution** qui :

1. Détecte les chaînes au format `${vault://<id>:<clé>}` dans la config et l'environnement
2. Lookup `<id>` dans la table de config locale → récupère url + token
3. Appelle Harpocrate via le SDK pour récupérer le secret `<clé>`
4. Remplace la chaîne par la valeur déchiffrée
5. Cache les résultats en RAM pendant la durée de vie du process pour éviter les appels redondants

Le moment de la résolution dépend du type d'application :

- Application qui démarre une fois avec ses secrets en RAM → résolution au démarrage, valeurs gardées dans le process
- Application long-running qui peut subir des rotations → résolution paresseuse + invalidation de cache si `401` reçu de l'API
- Containers avec init script (Docker, Swarm) → résolution dans l'entrypoint, injection en env vars du process applicatif

À toi de choisir le pattern adapté.


## Cache et invalidation

- Garde les valeurs déchiffrées en RAM, pas sur disque
- Cache valide jusqu'à fin de process ou jusqu'à un `401`/`403` du coffre
- Si `401` : refresh la table de config (la key a peut-être été révoquée), re-tenter une fois, sinon échec explicite
- Pas de cache négatif (un secret introuvable n'est pas mis en cache)


## Gestion des erreurs

Le coffre peut être indisponible (maintenance, réseau, etc.). L'application doit gérer proprement :

- **Au démarrage** : si le coffre est inaccessible et que l'application a besoin de secrets pour fonctionner, échec rapide avec un message d'erreur clair (`Harpocrate unreachable at startup, cannot resolve secrets`)
- **En runtime** : retry avec backoff exponentiel sur les erreurs réseau transitoires, échec définitif après N tentatives
- **Token révoqué** : message d'erreur explicite indiquant quel alias (`api1`, `api2`) a été refusé
- **Secret introuvable** : message indiquant le nom du secret recherché et l'alias associé

Ne jamais logger en clair :
- Le contenu du token API key (`hrpv_1_*`)
- Les valeurs déchiffrées des secrets
- La clé de déchiffrement extraite du token

Loguer librement :
- Les alias logiques (`api1`, `api2`)
- Les noms de secrets (`GITHUB_TOKEN`, `ANTHROPIC_API_KEY`)
- Les codes d'erreur HTTP du coffre


## Plan de migration

Voici ce que tu dois faire concrètement, dans cet ordre :

1. **Inventaire** : liste tous les endroits où des secrets sont actuellement gérés
   - Fichiers `.env` et `.env.example`
   - Variables hardcodées dans le code source
   - Configs YAML/JSON contenant des valeurs sensibles
   - Logique custom de gestion de secrets (lecture de fichiers chiffrés, intégration cloud secrets manager, etc.)
   - Templates docker-compose, Helm charts, manifests Kubernetes
   - Scripts d'install / bootstrap / CI

2. **Conception de la table de config** : choisis le format adapté au projet (fichier YAML, table SQL, etc.) et crée la structure

3. **Implémentation du loader** : code le mécanisme de résolution `${vault://...}` adapté au cycle de vie de l'application

4. **Migration** : remplace toutes les occurrences inventoriées par des références `${vault://...}`. Les vraies valeurs des secrets seront placées dans le coffre Harpocrate (pas dans le code, pas dans la table de config).

5. **Suppression** : supprime tout l'ancien code de gestion de secrets (lecture de `.env` pour des secrets, intégration custom, etc.). Le seul mécanisme restant doit être le loader Harpocrate.

6. **Documentation** : mets à jour le README pour expliquer
   - Où se trouve la table de config locale
   - Comment ajouter une nouvelle API key Harpocrate au projet
   - Comment référencer un secret dans le code
   - Comment l'application résout les secrets au démarrage

7. **Tests** : assure-toi que les tests d'intégration utilisent une instance Harpocrate de test (ou un mock du SDK) et que les tests unitaires ne dépendent plus de secrets en clair.


## Variables d'environnement attendues

Pour t'amorcer, l'opérateur a placé ces variables dans ton environnement (fichier `.env` du projet, secrets Docker Swarm, ou équivalent) :

```bash
# Pour chaque API key Harpocrate attribuée à cette application :
HARPOCRATE_API_TOKEN_<IDENTIFIER>=hrpv_1_...   # token complet
HARPOCRATE_API_URL_<IDENTIFIER>=https://vault.yoops.org

# Exemple :
# HARPOCRATE_API_TOKEN_API1=hrpv_1_abc...xyz
# HARPOCRATE_API_URL_API1=https://vault.yoops.org
```

Au démarrage du loader, lis ces variables pour peupler la table de config initiale, **ou** importe-les depuis un fichier de config maintenu par l'opérateur (à toi de choisir selon le projet).

Si aucune variable `HARPOCRATE_API_TOKEN_*` n'est présente au démarrage, échoue clairement : `No Harpocrate API key configured, cannot resolve secrets`.


## Critères de réussite

Avant de considérer la migration terminée :

- Aucun secret n'est plus en clair dans le code, la config, ou les fichiers `.env`
- Toute valeur sensible est référencée par `${vault://<id>:<clé>}`
- Le loader résout ces références au moment approprié
- L'application démarre correctement avec un token valide et échoue proprement avec un token invalide
- L'ancien code de gestion de secrets a été supprimé, pas désactivé
- Le README documente le nouveau fonctionnement
- Les tests passent


## Points d'attention

- **Tu décides** comment matérialiser la table de config et le loader. Adapte au projet.
- **Tu décides** comment supprimer l'ancien code. Sois agressif : pas de "au cas où", pas de code mort, pas de fallback vers les anciens secrets.
- **N'invente pas** d'endpoints Harpocrate : utilise uniquement ceux du spec OpenAPI (`/v1/openapi-api-key.json`).
- **Ne jamais construire** le header Authorization à la main sans avoir lu le spec OpenAPI : si tu n'utilises pas le SDK, la séparation entre secret d'authentification et clé de déchiffrement doit être respectée exactement.
- **Si le projet a des dépendances** sur des secrets dynamiques (rotation fréquente, secrets éphémères), gère le cache avec invalidation et retry plutôt qu'un simple lookup au démarrage.

Bonne migration.
