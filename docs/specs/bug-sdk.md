Bug à fixer dans Harpocrate (Python SDK) — collision kwarg `path` sur GET path-style

  CONTEXTE
  Le SDK Python `harpocrate` (installé via pip, code source ./harpocrate/client.py et ./harpocrate/http.py) plante avec TypeError dès
   qu'on tente une opération unitaire (GET/UPDATE/DELETE/PATCH) sur un secret nommé en path-style (nom contenant un `/`). Les
  écritures (create) et le list_secrets fonctionnent — c'est uniquement la résolution name→id du SDK qui casse.

  Erreur exacte observée :
      TypeError: VaultHttpClient.get() got multiple values for argument 'path'

  CHEMIN DU BUG
  1. Caller : agflow.docker fait `vault_client.get_secret("certificates/<uuid>/private_key")`
  2. Wrapper : `harpocrate.client.SecretsClient.get(name)` (client.py:245)
  3. → `self._http.get(self._path_for_op(name))` (client.py:252)
  4. → `_path_for_op` (client.py:116) appelle `_resolve_id_if_pathstyle(name)` car name contient `/`
  5. → `_resolve_id_if_pathstyle` (client.py:105-108) appelle :
         data = self._http.get(
             f"/v1/wallets/{self._wallet_id}/secrets",
             path=parent_path,   # ← LE BUG
         )
  6. → `VaultHttpClient.get(self, path: str, **params: Any)` (http.py:120) :
         `path` (positional) reçoit l'URL, `**params` reçoit `path=parent_path`
     Python lève TypeError : `path` reçoit deux valeurs.

  REPRODUCTION (contre n'importe quel vault Harpocrate)
      from harpocrate import VaultClient
      vc = VaultClient(token="<api_key>", base_url="<vault_url>")
      # Pré-condition : créer un secret path-style :
      vc.secrets.create("repro/bug/secret", "any-value")
      # Reproduit le bug :
      vc.secrets.get("repro/bug/secret")
      # → TypeError: VaultHttpClient.get() got multiple values for argument 'path'

  CE QUI FONCTIONNE DÉJÀ
  - `vc.secrets.create("foo/bar/baz", "value")` → OK (le secret est bien créé côté serveur)
  - `vc.secrets.list_secrets()` → OK, retourne les secrets path-style avec leur nom complet

  CONSÉQUENCE CÔTÉ CONSOMMATEUR (agflow.docker)
  Tout le sous-système qui chiffre des credentials infra via Harpocrate est cassé en lecture :
  - infra_machines_service (paths `machines/<id>/password`)
  - infra_certificates_service (`certificates/<id>/private_key` + `/passphrase`)
  - infra_swarm_clusters_service (`swarm_clusters/<id>/worker` + `/manager`)
  Les secrets sont écrits correctement mais ne peuvent plus être relus ni supprimés tant que ce bug n'est pas corrigé. Des secrets
  orphelins s'accumulent dans le vault à chaque DELETE côté agflow.

  CONTRAINTES POUR LA FIX
  1. Ne pas casser la rétro-compat des secrets nommés flat (sans `/`). `_resolve_id_if_pathstyle` retourne déjà None pour ces noms
  (client.py:96-97), donc le code patché ne doit pas changer ce comportement.
  2. Préserver les retries et l'auth gérés dans `VaultHttpClient._request` — ne pas dupliquer cette logique dans le caller.
  3. Couvrir au passage les autres call-sites internes du SDK qui pourraient avoir le même bug (chercher `_http.get(...,` ou
  `_http.{put,post,delete}(...,` avec un kwarg `path=`).

  PISTES DE FIX (au choix selon ce qui te paraît le plus propre dans ton repo)
  A) Bypass minimal sur le call-site fautif uniquement :
         data = self._http._request(
             "GET",
             f"/v1/wallets/{self._wallet_id}/secrets",
             params={"path": parent_path},
         )
  B) Renommer le 1er positionnel de VaultHttpClient.get/put/post/delete/patch de `path` vers `url` (ou `endpoint`). Plus de collision
   possible. Vérifier tous les call-sites internes + la doc.
  C) Ajouter une méthode publique `VaultHttpClient.request_with_query(method, url, query: dict)` et l'utiliser dans tous les endroits
   qui veulent passer un query param.

  Mon avis : (B) est le fix structurel le plus propre, (A) le hotfix le plus rapide. (C) ajoute une API qui ne résout pas la cause
  racine.

  DELIVERABLES ATTENDUS
  1. Fix dans client.py (+ éventuellement http.py si option B), avec commentaire explicatif sur la raison du choix.
  2. Tests unitaires :
     - Régression : `_resolve_id_if_pathstyle("foo/bar")` ne lève plus TypeError et résout correctement l'UUID (mock du HTTP).
     - Non-régression : `secrets.get("flat_name")` continue de fonctionner.
     - Couverture aussi de update/delete/patch sur path-style (mêmes call-sites).
  3. Audit du reste du SDK : grep `_http.get\|_http.put\|_http.post\|_http.delete\|_http.patch` pour vérifier qu'aucun autre
  call-site n'a le même bug latent.
  4. Bump de version (semver patch si option A, semver minor si option B avec renommage du positional — c'est techniquement breaking
  pour les callers qui passaient `path=` en kwarg).
  5. Publication (PyPI ou wheel interne selon ton circuit).

  Ne tente pas de patcher le SDK installé dans le venv du caller (agflow.docker) — ce serait perdu au prochain rebuild d'image. Le
  fix doit vivre dans le repo source du SDK, suivi d'une release.

  Une fois la nouvelle version publiée, je m'occuperai côté agflow.docker de bump la dépendance, rebuild, et relancer le smoke E2E
  (création cert + lecture private_key depuis vault + delete propre).