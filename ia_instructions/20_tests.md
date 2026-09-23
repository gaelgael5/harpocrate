# Fragment — Tests

> Source : globals › « Fichier d'instructions — Tests (agnostique) » (révision 2026-09-02)
> et forme Python de « spécificités Python ».
> Déclencheur : avant d'écrire ou de modifier un test, ou de corriger un bug.

### Tests — philosophie

La couverture est un **outil pour trouver ce qui n'est pas testé**, jamais un score à
maximiser. On teste pour avoir confiance en modifiant, pas pour cocher une case.

Un bon test prouve un comportement, **casse quand ce comportement change**, s'exécute
vite et se lit sans effort. Un test qui ne casse jamais ne prouve rien.

### Tests — ce qui est exigé

- **Règle du delta** : le code ajouté ou modifié est couvert à 90 % sur les lignes qui ont
  bougé. On ne juge pas le projet entier, on juge le changement.
- **Seuils par zone**, pas un seuil global : le cœur partagé et la logique métier critique
  se tiennent haut, l'interface d'administration bas. Un seuil unique fait mentir la moyenne.
- En dessous de 50 % sur une zone → alerte. **Au-dessus de 90 % → probablement du test
  inutile**, écrit pour le score.
- Les **cas de rejet sécurité** sont des tests, jamais des revues manuelles : traversée de
  chemin, isolation entre comptes, jeton rejoué, entrée malformée.

### Tests — ce qu'on teste obligatoirement

Par NATURE de l'unité, pas par langage :

- **Accès aux données** : chaque lecture et écriture, avec une doublure — dont le cas
  « rien trouvé », qui est celui qu'on oublie.
- **Accès aux fichiers** : avec des fichiers temporaires, jamais le dépôt lui-même.
- **Orchestration** : un test de bout en bout du flux, plus les branches qui s'arrêtent.
- **Points d'entrée outillés** (routes, commandes, tools) : le cas nominal ET les erreurs.
- **Récursivité** : profondeur 0 (arrêt immédiat), profondeur 1, profondeur maximale
  (l'erreur de profondeur doit être rendue, jamais un débordement de pile), et données
  manquantes ou circulaires.

### Tests — ce qu'on ne teste PAS

- Les journaux : vérifier qu'un message est écrit n'apporte rien.
- Les imports différés et le code d'infrastructure.
- Le code de glue qui ne fait que passer des paramètres sans décider.
- Le contenu des gabarits et des textes.
- La configuration statique : constantes, tables de correspondance.

### Tests — quand

- **Nouveau module** : tests écrits avant ou avec le code. Pas de fusion sans tests.
- **Correction de bug** : d'abord un test qui REPRODUIT le bug et qui ÉCHOUE ; puis la
  correction ; le test reste pour toujours.
- **Refactorisation** : les tests existants passent **sans modification**. Si un test casse,
  ce n'est pas une refactorisation — c'est un changement de comportement.
- **Modification d'un module** : lancer ses tests AVANT de toucher au code. S'ils échouent
  déjà, les réparer d'abord — sinon on ne saura pas ce qu'on a cassé.

### Tests — nommage et structure

Nom : `test_<ce_qui_est_testé>_<condition>_<résultat_attendu>`. Un nom qui ne dit pas le
résultat attendu oblige à lire le corps pour savoir ce qui est vérifié.

Un fichier de test par module ; les fixtures partagées dans le fichier de conftest du
cadre de test.

### Tests — l'environnement de débogage fait partie du paquet

On développe dans l'environnement ag-flow : deux moyens sont **fournis**, et ne pas s'en
servir revient à déboguer à l'aveugle.

- **Les logs centralisés.** Toute la suite pousse ses journaux vers la stack commune,
  consultable pendant une session de débogage. Devant un échec, on lit **les vrais logs du
  service**, on ne devine pas depuis un message d'erreur tronqué et on ne réinvente pas une
  instrumentation locale.
- **Des machines de test adaptées à la technologie du projet.** Elles existent déjà : on ne
  monte pas un environnement à la main pour valider un changement.

Les machines s'atteignent en SSH par leur **alias**, lisible dans le fichier de
configuration SSH — `test1` et ses voisins. Aucun identifiant à demander, aucune adresse à
retenir : lire le fichier d'alias.

**Un alias qui répond ne prouve rien.** Les alias sont recyclés : le même nom a pu désigner
plusieurs machines successives. Avant tout déploiement ou tout diagnostic, vérifier ce qu'il
y a DERRIÈRE l'alias — nom d'hôte réel, présence de la stack attendue, conteneurs qui
tournent. Un diagnostic mené sur la mauvaise machine coûte plus cher que pas de diagnostic
du tout : il produit des conclusions fausses qu'on croit vérifiées.

**Ne jamais simuler l'environnement** par un conteneur jetable lancé à la main : il n'a ni
le même cycle de démarrage, ni la même configuration, et produit des faux positifs. Déployer
sur la machine de test, puis lire les journaux réels.

### Tests — convention de déploiement sur une machine de test

L'ordre n'est pas indicatif : le script de déploiement **récupère le code depuis git**, il
ne prend pas ce qui traîne sur la machine. Livrer d'abord, déployer ensuite.

1. **Livrer sur la branche de travail** (`dev`). Tant que le commit n'y est pas, la machine
   de test déploiera l'état précédent — et l'on cherchera longtemps pourquoi le correctif
   n'a aucun effet.
2. **Se connecter à la machine de test** par son alias SSH.
3. **La première fois seulement** : cloner le dépôt.
4. **Ensuite, exclusivement `dev-deploy.sh`.** Il installe, construit et lance tout ce qu'il
   faut pour faire tourner l'application en mode quasi production. Ce que ce
   script doit garantir est décrit à part — voir plus bas. Ne pas reconstruire à la
   main, ne pas lancer un service isolé : ce qu'on teste alors n'est pas ce qui tournera.
5. **Lire les journaux réels** du service déployé, pas la sortie de la commande.

Ce qui est disponible en standard sur toute machine de test :

- **Docker**, installé.
- Des conteneurs de service déjà en place : `alloy-metrics`, `alloy-collector`,
  `browserless-chromium`.

Ces conteneurs sont **entièrement à ta disposition** pour tester — métriques, collecte de
journaux, navigateur sans interface pour éprouver une page réelle. Tu es également
**autorisé à héberger les images Docker** que tu juges nécessaires à ton travail : ajouter
une base jetable, un service doublure, un outil de mesure. Rien à demander.

## Spécifique Harpocrate

- **Machine de test : alias `test1`** (bloc « portal test-vm » de `~/.ssh/config`, via le
  rebond `devflow-jump`). Constaté le 2026-09-23 : nom d'hôte réel `host-test-23`, Debian 12,
  Docker 29.8, git 2.39.5 — et **la machine héberge déjà d'autres stacks** (`wsportal-dev-*` :
  portail, caddy, postgres, zulip, grafana/loki ; une CI `ci-fable5` dans `/root`). Donc, en
  plus des règles ci-dessus :
  - avant le **premier** déploiement Harpocrate, faire valider par l'utilisateur le
    répertoire cible et les ports (`8443`, Postgres) — ne jamais les deviner ;
  - ne jamais arrêter, purger ni modifier un conteneur, un volume ou un réseau qui n'est pas
    au projet compose `harpocrate` ; **aucun** `docker system prune` global ;
  - git 2.39.5 (bookworm) : voir le piège HTTP/2 → 401 dans `20_deploiement.md`.
- `scripts/run-test.sh` (LXC Proxmox, `docs/test.md`) est un chemin d'intégration de
  l'utilisateur, pas la machine de l'agent : ne pas le lancer sans demande.
- Backend : **pytest + pytest-asyncio** (`asyncio_mode = "auto"`), `backend/tests/` à plat,
  un `test_<module>.py` par module. Il n'y a **pas** de fixture `client` partagée : les tests
  d'API construisent un `httpx.AsyncClient(transport=ASGITransport(app=…))` (modèle :
  `_make_client` dans `test_api_keys.py`) ; fixtures communes dans `conftest.py`
  (`mock_db_conn`, `real_db_pool`, `mock_admin_user_resolver`…). Fichiers temporaires via
  `tmp_path`, jamais le dépôt.
- Les variables `HARPOCRATE_*` se posent **au niveau module** dans `backend/tests/conftest.py`
  (pas dans une fixture) — cf. `LESSONS.md` [tests].
- Tests d'intégration Postgres : actifs seulement avec `HARPOCRATE_DB_DSN_TEST` ; pas de mock
  pour ce qui prétend tester l'intégration.
- Frontend : Vitest + React Testing Library, `frontend/src/tests/`, `describe` / `it`.
- **Crypto et audit : TDD strict** (rouge → vert → commit), et tout test crypto couvre
  l'**aller-retour** (chiffrer puis déchiffrer), pas seulement le chiffrement.
- Ne pas compter sur `docs/tests-python.md` : ses seuils par zone sont ceux d'un autre projet
  (LandGraph) ; les critères de succès par zone sont dans `docs/specs/LOT_*.md`.

```bash
cd backend && uv run pytest -v
cd backend && uv run pytest tests/test_<module>.py -v
cd backend && uv run pytest -x -v
cd frontend && npx vitest run
```

## Pièges connus

**Le script de déploiement se met à jour lui-même depuis git avant de déployer.** Le réseau et l'accès au dépôt sont donc un prérequis, pas un confort : il n'existe pas de mode « déploie ce qui est déjà là ». Un dépôt public reste par ailleurs soumis à un quota de requêtes anonymes par adresse IP — franchi, il fait répondre « authentifie-toi » sur un dépôt pourtant ouvert, ce qui ressemble à un problème de droits alors que c'en est un de débit.

**Un test écrit après le code n'a pas prouvé qu'il mord.** La seule preuve est de l'avoir vu rouge. À défaut, casser volontairement le code et vérifier qu'il échoue — sinon on garde un test aveugle qui donne une fausse assurance.

**Un jeu d'essai qui porte déjà la valeur attendue rend le test inutile.** Si la doublure a un champ vide et que le test vérifie qu'il est vide, il reste vert même quand le code recopie la valeur. Choisir des valeurs **discriminantes**.

**Comparer un nombre d'échecs ne prouve pas l'absence de régression.** Deux suites peuvent afficher le même total avec des échecs différents. Comparer l'**ensemble** des tests en échec, pas leur compte.

**Une suite partagée entre deux exécutions concurrentes se détruit elle-même.** Deux campagnes sur la même base jetable effacent mutuellement leurs tables : une base par exécution.

**Un test qui dépend de l'horloge ou de l'aléatoire échoue un jour sur cent**, toujours chez quelqu'un d'autre. Injecter l'instant et la graine.

**Des tests comptent les appels `fetchrow`** (`test_wallets.py`, lookup users…) : ajouter une
requête dans un chemin chaud (ex. `require_jwt_user`) les casse — cf. `LESSONS.md` [auth].

## Part de checklist

- [ ] Le code ajouté ou modifié est couvert à 90 % sur les lignes changées
- [ ] Chaque correction de bug est accompagnée du test qui le reproduisait
- [ ] Les tests écrits après le code ont été éprouvés en cassant le code
- [ ] Les cas de rejet sécurité sont des tests, pas des intentions
- [ ] La suite complète passe, et l'ensemble des échecs préexistants est inchangé
- [ ] Tout diagnostic s'appuie sur les journaux réels du service, pas sur une supposition
- [ ] Les tests skippés (DB d'intégration absente) sont signalés comme tels, pas comptés comme verts
- [ ] Si une machine de test existe : la machine derrière l'alias SSH a été vérifiée, le commit est poussé sur `dev` AVANT le déploiement, et le déploiement est passé par `dev-deploy.sh`
