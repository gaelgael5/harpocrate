# Machines de test et livraison — blocs intégraux

> Texte intégral, au mot près, d'un bloc invariant du STANDARD « Fichier d'instructions agent de
> projet » (globals, v42). Sorti de `CLAUDE.md` par la remise en forme du quota ; `CLAUDE.md` en
> garde la synthèse et le déclencheur. Ne pas l'éditer hors d'un `--update`.

### Machines de test
Les machines de test sont **à ta disposition** pour exécuter les tests et valider que les
livrables sont conformes à la demande. Rien à demander pour t'en servir.

**Cherche où le test sera le plus révélateur — et privilégie la machine de test.** Avant de
valider un sujet, évalue l'endroit où un test a le plus de chances de révéler un défaut
réel : c'est le plus souvent la machine de test, où le livrable tourne dans sa configuration
réelle, avec ses journaux et ses métriques. Un test local qui passe ne dispense pas de la
validation sur une machine de test dès que celle-ci peut révéler davantage.

- **Accès** : alias SSH déclarés dans la configuration SSH — `test1`, `test2`, `test…`.
  Aucun identifiant à demander, aucune adresse à retenir : lire le fichier d'alias.
- **Docker** est installé en standard. Il sert à lancer les conteneurs à tester, et aussi à
  exécuter des tests unitaires, des tests ATDD ou tout autre type de test que tu juges
  nécessaire.
- **Services en standard** : un collecteur de logs et un collecteur de métriques
  (`alloy-collector`, `alloy-metrics`), qui centralisent journaux et métriques, et un
  `browserless-chromium` pour éprouver en mode web les services livrés sur la machine.

**Un alias qui répond ne prouve rien** : les alias sont recyclés. Avant tout déploiement ou
diagnostic, vérifier ce qu'il y a DERRIÈRE — nom d'hôte réel, stack attendue, conteneurs actifs.

**Consigne les ressources qui te sont attribuées.** Chaque machine de test — et plus
généralement chaque ressource mise à ta disposition — t'est notifiée ; tu l'enregistres
dans `ia_instructions/tests_and_ressources.md` (nom d'hôte, alias SSH, à quoi elle sert),
et tu l'y retires quand elle t'est reprise. Ce fichier est ta MÉMOIRE des ressources
disponibles, distincte des règles ci-dessus : les règles disent comment t'en servir, ce
fichier dit lesquelles tu as, ici et maintenant. Le tenir à jour à chaque notification est
ce qui te permet de retrouver une machine sans redemander.

### Livrer sur une machine de test — procédure incontournable
Livrer les images du projet sur une machine de test passe TOUJOURS par cette procédure,
jamais par une construction ou un `docker run` à la main :

1. **Pousser sur `dev`.** Le déploiement récupère le code depuis git : tant que le commit
   n'y est pas, la machine déploie l'état précédent.
2. **Se connecter** à la machine de test par son alias SSH.
3. **La première fois** : cloner la branche `dev`.
4. **Les fois suivantes** : lancer `dev-deploy.sh`, exclusivement.
5. **Lire les journaux réels** du service déployé, pas la sortie de la commande.

Le **service livré** n'est jamais simulé par un conteneur lancé à la main : il n'aurait ni le
même cycle de démarrage ni la même configuration. Les **outils de test** (runner, base
jetable, doublure, outil de mesure), eux, tournent librement dans Docker.

**Aucune retouche manuelle de la cible hors de cette procédure.** Un correctif d'infra ou de
provisionnement (permission à poser, service à initialiser, migration d'un annexe) ne se joue
JAMAIS en `docker exec`/`manage.py`/édition de fichier à la main : il se met DANS le script de
déploiement (ou un script qu'il appelle), de sorte qu'un simple `dev-deploy.sh` l'applique et
que la prochaine machine en hérite. Une commande one-off tapée sur l'hôte est perdue au
redéploiement suivant et introuvable pour le prochain agent.
