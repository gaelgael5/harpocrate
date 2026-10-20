# Ressources attribuées — mémoire de l'agent

> Tenue selon le bloc « Machines de test » de `CLAUDE.md` : chaque ressource notifiée s'ajoute
> ici (nom d'hôte, alias SSH, à quoi elle sert), et s'en retire quand elle est reprise. Ce
> fichier dit **lesquelles** tu as ; les règles d'usage sont dans `CLAUDE.md`.

## Machines de test

| Alias SSH | Nom d'hôte réel | Attribuée le | Usage | Constaté |
|---|---|---|---|---|
| `test1` | `host-test-36` | 2026-10-20 | Livrer, tester et valider Harpocrate (`dev-deploy.sh`) | voir ci-dessous |

### `test1` — état constaté

- **Réattribuée le 2026-10-20 : nouvelle machine `host-test-36`** (l'ancienne `host-test-23` est reprise,
  avec son instance, ses scripts de recette et sa base jetable `harpocrate-testdb` : tout est à recréer).
- Accès : bloc « portal test-vm test1 » de `~/.ssh/config`, via le rebond `devflow-jump`.
- Constaté le 2026-10-20 : Debian 12, Docker 29.9, **git 2.39.5** sans `/etc/git/http2-github.inc`
  (piège HTTP/2 → 401 contre GitHub possible, cf. skill `test-machine-deployment`) ; 40 Go disque, 7 Go RAM.
- **Machine partagée** : photoreader, tutor, tutor-mobile, miles, `devpod-alloy-agent`,
  `devpod-alloy-metrics`, `browserless-chromium` (`:3000`). Ports pris le 2026-10-20 : 1883, 3000, 5445,
  8030, **8080** (miles-frontend), 8081, 8090. `dev-deploy.sh` choisit désormais un port libre et le
  persiste dans `.env` (`HARPOCRATE_DEV_*_PORT`).
- Pas de clé GitHub sur la machine : clone HTTPS (dépôt public) dans `/root/harpocrate`, journal
  `/root/harpocrate-deploy.log`.
- Instance déployée le 2026-10-20 (`dev-deploy.sh dev`) : UI `https://192.168.10.203:8443`, HTTP local
  `127.0.0.1:8082` (8080/8081 pris), API `127.0.0.1:8000`, Postgres `0.0.0.0:5432`. Keycloak non configuré
  (`/v1/health` « degraded », `jwks_loaded=false`) : le parcours `/connect` complet n'y est pas jouable.
  Le mot de passe admin local a été affiché dans le journal de déploiement et la session : **à faire tourner**.
- Tests backend sur vraie base : `scripts/run-integration-tests.sh /root/harpocrate [args pytest]`
  (base jetable créée puis détruite). 2026-10-20 : 1054 passés, 16 échecs = les 11 du bug « tests
  périmés » + 5 Google Drive / oauth_pending (bug JSONB), aucun autre.

## Autres ressources

| Ressource | Identifiant | Attribuée le | Usage |
|---|---|---|---|
| Workspace docflow | `harpocrate` (blocs `backlog`, `documentation`) | 2026-09-23 | Backlog et documentation du projet |
| Corpus RAG | `harpocrate-docs` (chunking `docflow-docs`, endpoint `azure`) | 2026-09-23 | Recherche dans la documentation du projet |
| Identité tchat | `admin-harpocrate.harpocrate` (session tmux `harpocrate`) | 2026-09-29 | Coordination avec les agents du groupe |
