# Fragment — Contrats d'interface et documentation

> Source : globals › « Fichier d'instructions — Contrats d'interface et documentation (agnostique) » (révision 2026-09-09).
> Déclencheur : avant de modifier une route sous `backend/app/api/`, un DTO de
> `backend/app/models/api/`, un SDK (`sdk-*/`, `cli-bash/`), `docs/vault.md`, le protocole
> de réplication MQTT (`services/sync_protocol.py`) ou un webhook.

### Contrats et documentation

**Un contrat se publie dans docflow, bloc `documentation` du workspace du projet.**
Toute interface sur laquelle un autre composant s'appuie — route HTTP, webhook, event,
format d'échange, outil MCP — a son article dans ce bloc wiki. Un contrat qui ne vit que
dans le code ou dans un fil de discussion n'existe pas : personne ne peut le chercher, et
il dérive sans que rien ne le signale.

**Un contrat de service web est publié en OpenAPI** (3.1), machine-lisible, joint à
l'article comme artefact — pas seulement décrit en prose. L'article porte l'intention, les
invariants et ce qui casse la compatibilité ; le fichier OpenAPI porte la forme, et c'est
lui qui est importable, comparable d'une version à l'autre, et vérifiable contre le service
réel. Si la spec est générée par le framework, l'article dit quelle version est publiée et
comment la régénérer.

**Chercher un contrat, dans cet ordre :**
1. la **documentation du projet** — docflow, bloc `documentation`, interrogé via le RAG
   `harpocrate-docs` ;
2. à défaut, le dépôt **`ressources`** (`contracts/<fournisseur>/<nom>.openapi.json`), où
   sont hébergés les contrats externes que le fournisseur ne publie pas lui-même ;
3. à défaut seulement, l'artefact réel : `/openapi.json` du service en marche, `--help` du
   binaire, la charge utile observée — et alors, écrire l'article qui manquait.

Jamais l'inverse. Coder de mémoire contre une interface, ou déduire un contrat d'un appel
qui a marché une fois, produit un couplage que personne n'a écrit et que personne ne
maintiendra.

**Modifier un contrat est un acte explicite.** Changer une forme de réponse, un nom de
champ, un code d'erreur ou un déclencheur d'event, c'est modifier l'article ET la spec dans
le même changement. Une documentation en retard n'est pas une documentation incomplète,
c'est un piège. Et une rupture de compatibilité se signale à l'utilisateur avant d'être
écrite, jamais livrée en silence.

## Spécifique Harpocrate — ce dépôt est un FOURNISSEUR de contrats

Tous les projets de la maison consomment Harpocrate (globals › « STANDARD — Sécurité :
secrets et coffres Harpocrate », révision 2026-09-20). Pour eux, **seuls font foi** :

| Contrat | Où il vit ici |
|---|---|
| Guide de consommation (API key, déchiffrement client, référence, cache, erreurs, logs) | `docs/vault.md` |
| Contrat API key | `GET /v1/openapi-api-key.json` (`app/api/v1/api_key_openapi.py`) |
| SDK distribués | `GET /v1/sdk/python-wheel`, `GET /v1/sdk/cli-bash` (`sdk-python/`, `cli-bash/`) |
| Format du token `hrpv_*` | `app/core/api_key_token.py` |

Toute modification de l'un d'eux est une **modification de contrat inter-projets** : la
signaler à l'utilisateur **avant** de l'écrire, mettre à jour les quatre ensemble, et
publier l'article docflow correspondant. Une rupture (champ renommé, code d'erreur changé,
format de token) casse les consommateurs sans que ce dépôt ne le voie.

Autres contrats internes à surveiller : protocole de réplication MQTT entre instances
(`services/sync_protocol.py`, `sync_apply.py`), `webhooks_notify.py`, format des exports
chiffrés et des backups `age`.

Documentation existante : le wiki bilingue `harpocrate.wiki/` (dépôt séparé
`gaelgael5/harpocrate.wiki`, branche `master`) porte la doc utilisateur/exploitation FR/EN.
Le bloc docflow `documentation` (workspace `harpocrate`, créé le 2026-09-23) reçoit les
**articles de contrat** et ce que les agents apprennent. Ne pas recopier un article dans les
deux : l'un référence l'autre.

## Pièges connus

**Une spec générée n'est pas un contrat publié.** Ce que le framework produit décrit le code d'aujourd'hui, accidents compris. Le contrat, lui, est ce qu'on s'engage à tenir : l'article dit ce qui est garanti et ce qui ne l'est pas — sans quoi le premier détail d'implémentation devient une promesse par mégarde.

**Un contrat absent de docflow est invisible au RAG.** Et le corpus muet ressemble à une réponse vide, pas à une lacune : l'agent suivant conclura qu'il n'y a pas de contrat, et en inventera un.

**Deux copies divergent toujours.** Ne pas recopier le corps de la spec dans la prose de l'article : un seul fichier fait foi sur la forme, l'article le référence. Le jour où les deux disent des choses différentes, personne ne sait laquelle est la bonne.

**Un contrat externe reconstruit à la main vieillit en silence.** L'article doit dire d'où il vient (prose du fournisseur, date de reconstruction), sinon il sera pris pour une spec officielle. Procédure d'hébergement : globals › « Héberger un contrat externe dans le git ressources → URL raw publique ».

**Les events et webhooks sont des contrats.** Ils passent souvent au travers parce qu'il n'y a pas de route à documenter — alors qu'ils portent le plus de non-dit : schéma de la charge utile, entête de signature, garantie de livraison, clef de déduplication. En OpenAPI 3.1, ils vivent dans la section racine `webhooks`.

## Part de checklist

- [ ] Toute interface ajoutée ou modifiée a son article dans le bloc `documentation` du workspace `harpocrate`
- [ ] Tout service web ajouté ou modifié a sa spec OpenAPI jointe et à jour ; aucune divergence entre l'article et la spec
- [ ] Le contrat consommé a été cherché dans la documentation du projet, puis dans `ressources`, avant toute lecture de code ou supposition
- [ ] Aucune rupture de compatibilité livrée sans l'avoir signalée explicitement
- [ ] Si `docs/vault.md`, `openapi-api-key.json`, un SDK ou le format `hrpv_*` a bougé : les quatre sont cohérents et l'utilisateur a été prévenu avant
