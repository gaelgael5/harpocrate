# Ressources attribuées — mémoire de l'agent

> Tenue selon le bloc « Machines de test » de `CLAUDE.md` : chaque ressource notifiée s'ajoute
> ici (nom d'hôte, alias SSH, à quoi elle sert), et s'en retire quand elle est reprise. Ce
> fichier dit **lesquelles** tu as ; les règles d'usage sont dans `CLAUDE.md`.

## Machines de test

| Alias SSH | Nom d'hôte réel | Attribuée le | Usage | Constaté |
|---|---|---|---|---|
| `test1` | `host-test-23` | 2026-09-23 | Livrer, tester et valider Harpocrate (`dev-deploy.sh`) | voir ci-dessous |

### `test1` — état constaté

- Accès : bloc « portal test-vm test1 » de `~/.ssh/config`, via le rebond `devflow-jump`.
- Constaté le 2026-09-23 : Debian 12, Docker 29.8, **git 2.39.5** (piège HTTP/2 → 401 contre
  GitHub, cf. docflow « Fragment — Déploiement »).
- **Machine partagée** : héberge déjà `wsportal-dev-*` (portail, caddy, postgres, zulip, grafana,
  loki, victoriametrics), `devpod-alloy-*`, `browserless-chromium`, une CI `ci-fable5` dans `/root`.
- Ports libres le 2026-09-23 pour la stack dev : `5432`, `8000`, `8080`, `8443` — **à revérifier
  au moment de chaque déploiement**, jamais tenus pour acquis.
- Pas de clé GitHub sur la machine : cloner en HTTPS (dépôt public).
- **Harpocrate déployé** le 2026-10-03 (branche `dev`, `dev-deploy.sh`) : clone `/root/harpocrate`, journal
  `/root/harpocrate-deploy.log`, UI `https://192.168.10.179:8443` (cert auto-signé), conteneurs
  `harpocrate-backend|frontend|postgres`, Postgres publié sur `0.0.0.0:5432`.
- Admin local de l'instance de test : identifiants dans `/root/harpocrate/.env` (**à faire tourner** :
  le mot de passe a été affiché dans une session le 2026-10-03) ; crypto initialisée, passphrase de test
  dans `/root/harpocrate-test-passphrase` (600). Ne jamais afficher ces valeurs : les lire sur la machine.
- Script de validation UI réutilisable : `/root/harpocrate-ui-check.py` (pilote `browserless` sur
  `127.0.0.1:3000`, sans jeton ; clics par le DOM, les contrôles Mantine n'étant pas cliquables par Puppeteer).
- Recette « Se connecter avec Harpocrate » (2026-10-03) : `/root/harpocrate-connect-check.py` (API, exécuté DANS
  `harpocrate-backend` : `docker cp` puis `docker exec … python`, identifiants lus dans l'environnement du conteneur ;
  laisse une application `recette-*` désactivée dans le registre) et `/root/harpocrate-connect-ui-check.py`
  (navigateur, `/connect`). La Keycloak configurée sur l'instance (`keycloak.yoops.org`, realm `yoops`) refuse l'origine
  `https://192.168.10.179:8443` (CORS) : le parcours complet demande un client Keycloak public valide pour cette origine.
- **Base jetable de tests d'intégration** : conteneur `harpocrate-testdb` (`postgres:16-alpine`,
  labels `projet=harpocrate`, `usage=tests-jetables`), `127.0.0.1:55433`, utilisateur `harpo` ; bases
  `harpocrate_test`, `harpocrate_existing`, `harpocrate_blank`, `harpocrate_032`. Accès depuis le
  devcontainer par tunnel `ssh -fN -L 127.0.0.1:55433:127.0.0.1:55433 test1`. À supprimer quand il ne sert plus.

## Autres ressources

| Ressource | Identifiant | Attribuée le | Usage |
|---|---|---|---|
| Workspace docflow | `harpocrate` (blocs `backlog`, `documentation`) | 2026-09-23 | Backlog et documentation du projet |
| Corpus RAG | `harpocrate-docs` (chunking `docflow-docs`, endpoint `azure`) | 2026-09-23 | Recherche dans la documentation du projet |
| Identité tchat | `admin-harpocrate.harpocrate` (session tmux `harpocrate`) | 2026-09-29 | Coordination avec les agents du groupe |
