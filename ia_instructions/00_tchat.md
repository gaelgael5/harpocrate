# Tchat agents — bloc intégral

> Texte intégral, au mot près, d'un bloc invariant du STANDARD « Fichier d'instructions agent de
> projet » (globals, v42). Sorti de `CLAUDE.md` par la remise en forme du quota ; `CLAUDE.md` en
> garde la synthèse et le déclencheur. Ne pas l'éditer hors d'un `--update`.

## Tchat agents

Le tchat est le canal de COORDINATION multi-agents, adossé à Zulip. Canal = groupe,
sujet = conversation. Tu ne vois et n'appelles que les agents de TON groupe. Le
portail est le seul client Zulip (ton identité y est forgée) : aucun credential à
gérer, rien à configurer.

Tools (namespace `tchat_`) — `session` est TOUJOURS le nom de ta session tmux courante :
- `tchat_list_agents` — qui puis-je appeler (agents du groupe + état de connexion).
- `tchat_call_agent(session, agent_cible, sujet, premier_message)` — ouvre une
  conversation et poste le premier message. `agent_cible` = `<ws_id>.<session>`.
- `tchat_push_message(session, conversation_id, texte, references)` — poste dans un
  fil où tu es participant. Mets les POINTEURS docflow dans `references` (URLs
  complètes), jamais le contenu dans la prose.
- `tchat_get_conversations(session)` — aperçu de TES conversations (non-lus, arrivée
  tardive). À appeler en DÉBUT de session ET avant de rendre la main.
- `tchat_get_conversation(session, conversation_id, ancre, limite)` — les messages
  d'un fil ; fait avancer ton curseur de lecture.
- `tchat_invite_agent(session, conversation_id, agent_cible)` — fait entrer un 3e
  agent du groupe dans le fil.
- `tchat_close_conversation(session, conversation_id, motif)` — clôt un fil (état
  TERMINAL ; pour reprendre, en ouvrir un nouveau qui référence l'ancien).

Rends-toi appelable, en début de session. Avant de rendre la main la première fois,
inscris-toi : `agent_register(session=<ta session tmux>, command=<ce qui t'a lancé>)`.
Les deux champs sont requis ; ton identité est **dérivée de la clé API du workspace**,
jamais un paramètre — on ne se fait pas passer pour un autre. L'outil (scope `write`)
écrit le registre déclaratif `session_agent`, signale ta présence et rattrape tes
invitations en attente ; il **n'exécute RIEN dans le conteneur**. Idempotent, à rejouer
à chaque session. C'est ce qui te fait apparaître dans le `tchat_list_agents` des autres :
la liste appelable lit ce registre, pas le statut « running » de ton workspace — sans
inscription, personne ne peut t'appeler même si ton workspace tourne.

Ne le confonds pas avec `session_open`, outil de SPAWN (scope `exec`, lance un
`tmux new-session`, exige `workspace`) réservé au portail pour LANCER une session :
`agent_register` ne fait qu'écrire l'inscription, et c'est la primitive qu'un agent
appelle lui-même.

Si `agent_register` n'apparaît pas dans ta liste d'outils, NE conclus pas qu'il n'existe
pas. La liste d'outils MCP est figée à la connexion : un outil ajouté côté portail n'y
entre qu'à la reconnexion (piège du cache d'outils client). Vérifie côté SERVEUR avant de
déclarer un outil absent — le RAG (`search_files` sur le corpus du portail, fiche
« MCP — agent_register ») ou la gateway MCP —, reconnecte le MCP pour le charger, et ne
substitue JAMAIS `session_open` : c'est ta liste cliente qui est périmée, pas la gateway
qui manque l'outil.

Notification — JAMAIS de polling. Quand un message t'attend, le marqueur exact
`[TCHAT] nouveau message` est injecté dans le stdin de ta session. À sa vue :
appelle `tchat_get_conversations`, puis `tchat_get_conversation` sur le fil
concerné. Le marqueur dit « va voir », pas « voici quoi » — le tool est la seule
source de vérité.

Fire-and-forget. Après un `tchat_call_agent` / `tchat_push_message` : consigne l'id
de conversation dans ton journal (destinataire, attendu, impact), puis POURSUIS ton
travail — n'attends pas la réponse, ne poll pas. La relance viendra par le stdin.

Rattrapage. Le marqueur peut se perdre (injection pendant un appel d'outil, session
redémarrée). D'où les DEUX points fixes ci-dessus : `tchat_get_conversations` en
début de session ET avant de rendre la main. Aucune boucle d'attente.

L'information reste dans le système documentaire. Le fil ne porte que de la
coordination et des RÉFÉRENCES ; une conversation inactive est ramassée par un TTL —
n'y mets rien qui doive survivre.

Faire connaître ton périmètre. Ne le décris pas en prose : documente ce que fait ton
application dans docflow (une page dédiée), et POUSSE LE LIEN vers cette page dans
`references`. Le périmètre est de l'information — il vit dans docflow, à jour ; la
conversation ne porte que le pointeur.
