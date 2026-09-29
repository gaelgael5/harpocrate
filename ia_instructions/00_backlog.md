# Backlog — bloc intégral

> Texte intégral, au mot près, d'un bloc invariant du STANDARD « Fichier d'instructions agent de
> projet » (globals, v42). Sorti de `CLAUDE.md` par la remise en forme du quota ; `CLAUDE.md` en
> garde la synthèse et le déclencheur. Ne pas l'éditer hors d'un `--update`.

## Backlog
La gateway MCP expose une API vers docflow (workspaces ⊃ blocs ⊃ documents).
Le backlog des tâches à exécuter est dans le workspace `harpocrate`, bloc `backlog`.

**Avant de commencer, découvre les statuts réels.** Les valeurs de statut dépendent du
type de ticket et diffèrent d'un type à l'autre. Introspecte le bloc pour connaître, pour
chaque type présent, la valeur qui joue chacun de ces rôles :
- **disponible** — la tâche peut être prise ;
- **en cours** — tu travailles dessus ;
- **en revue** — tu as fini, elle attend une revue humaine ;
- **terminée** — elle est close ;
- **en attente** — elle attend une réponse de l'utilisateur (ce rôle peut ne pas exister).
N'écris JAMAIS une valeur de statut de mémoire : une valeur inexistante est refusée, et un
statut approximatif choisi au jugé fausse l'état du backlog pour tout le monde.

Quand on te demande de traiter le backlog :
- ne retiens que les tâches au rôle **disponible** — ni en cours, ni en revue, ni
  terminées, ni en attente ;
- **AVANT de toucher au code**, passe la tâche au rôle **en cours** ;
- **quand tu as fini**, passe-la au rôle **en revue**.
Ces deux écritures ne sont pas optionnelles : c'est ce qui dit aux autres — humains et
agents — qu'une tâche est prise, et ce qui permet de reprendre après une interruption.

**Le backlog est la source de vérité, jamais ta mémoire.** Ne tiens pas la liste des tâches
restantes dans ta tête : elle s'éloigne à mesure que ton contexte se remplit, et tu
t'arrêteras en croyant avoir fini. Après CHAQUE tâche, réinterroge le backlog et reprends
la suivante.

**Le statut s'écrit à chaque tâche, pas à la fin du lot.** Une session interrompue doit
pouvoir reprendre sur la seule lecture du backlog.

**Une tâche dont un prédécesseur n'est pas terminé n'est pas éligible.** Vérifie les
prédécesseurs déclarés avant de prendre une tâche, et prends la suivante éligible.

**Une question ne bloque pas la file.** Si une tâche soulève un vrai doute : écris la
question en tête de la tâche, puis passe-la au rôle **en attente** s'il existe. S'il
n'existe pas, laisse-la dans son état et signale-la explicitement à la fin du lot. Dans
les deux cas, CONTINUE avec la suivante. Ne gèle jamais le lot entier sur un doute isolé.

**Tu ne t'arrêtes que pour une de ces quatre raisons, et tu la nommes :**
1. plus aucune tâche éligible — le lot est fini ;
2. toutes les tâches restantes attendent une réponse de l'utilisateur ;
3. toutes les tâches restantes ont un prédécesseur non terminé ;
4. quelque chose a échoué — dis quoi.

Si tu t'apprêtes à conclure sans pouvoir citer l'une des quatre, c'est que tu t'arrêtes par
oubli : réinterroge le backlog et continue.
