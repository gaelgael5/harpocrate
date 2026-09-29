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
- Harpocrate n'y est **pas encore déployé** (état au 2026-09-29).

## Autres ressources

| Ressource | Identifiant | Attribuée le | Usage |
|---|---|---|---|
| Workspace docflow | `harpocrate` (blocs `backlog`, `documentation`) | 2026-09-23 | Backlog et documentation du projet |
| Corpus RAG | `harpocrate-docs` (chunking `docflow-docs`, endpoint `azure`) | 2026-09-23 | Recherche dans la documentation du projet |
| Identité tchat | `admin-harpocrate.harpocrate` (session tmux `harpocrate`) | 2026-09-29 | Coordination avec les agents du groupe |
