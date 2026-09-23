# Fragment — Commentaires de code

> Source : globals › « Fichier d'instructions — Commentaires de code (agnostique) » (révision 2026-09-06).
> Déclencheur : avant d'écrire ou de modifier du code (`.py`, `.ts`, `.tsx`, `.sh`, `.sql`) —
> en même temps que le fragment du langage.

### Commentaires — le POURQUOI, jamais le QUOI

Le code dit déjà ce qu'il fait. Un commentaire qui paraphrase la ligne suivante est
du bruit : il se désynchronise au premier changement et apprend à ne plus lire les
commentaires.

Ce qui manque, et que le code ne peut pas porter :

- **La raison** d'un choix qui n'est pas le choix évident.
- **L'alternative écartée** et pourquoi elle l'a été.
- **La conséquence** de faire autrement — c'est ce qui arrête la main du prochain.

Trois cas où le commentaire est OBLIGATOIRE :

1. **Toute règle de sécurité, à son point d'application.** Enforcement recalculé
   plutôt que lu d'un cache, point d'injection unique d'un secret, vérification
   fail-closed. Ce sont les lignes qui ressemblent le plus à de l'inefficacité.
2. **Tout écart assumé** par rapport à une convention, un standard maison, ou le
   comportement d'un autre module dont on s'inspire. Dire que c'est une divergence
   VOLONTAIRE et laquelle, sinon elle sera lue comme une erreur et « corrigée ».
3. **Tout repli volontaire** (valeur de secours, dégradation silencieuse, cas
   fail-safe). Un repli non commenté est indiscernable d'un bug.

Ce qu'on ne commente pas :

- Ce que le nom dit déjà. Si le commentaire est nécessaire pour comprendre CE que
  fait la fonction, c'est le nom qu'il faut corriger.
- Le contenu du ticket. Deux ou trois lignes de raison, pas la recopie de la
  spécification : une duplication longue diverge comme toutes les duplications.
- L'historique. Qui a changé quoi et quand, c'est le rôle du gestionnaire de
  versions. Du code commenté « au cas où » se supprime, il est dans l'historique.

### Commentaires — articulation avec le ticket

Une décision inscrite dans un ticket ne s'arrête pas au code qui l'applique : elle
doit s'y **lire**.

- Le **ticket** porte la décision et sa justification complète, et exige explicitement
  son report en commentaire.
- Le **code** porte la version courte : la raison et l'alternative écartée.
- La **documentation** porte l'analyse longue, et le code y renvoie si le détour
  se justifie — jamais l'inverse, une doc ne sait pas quelles lignes elle protège.

**Critère de revue** : une décision listée dans le ticket qui n'apparaît nulle part
en commentaire dans le diff n'est pas terminée. Ce n'est pas une préférence de style,
c'est la condition pour que la décision survive à sa propre implémentation.

## Spécifique Harpocrate

Densité de référence : celle du code existant (docstrings de module courtes, commentaires
`# RÈGLE DE SÉCURITÉ : …` au point d'application — ex. middlewares de `app/main.py`). Langue : celle
du fichier touché (majoritairement français côté backend, anglais dans une partie du front) —
ne pas mélanger dans un même fichier.

## Pièges connus

**Le commentaire qui paraphrase entretient la méfiance.** Un dépôt où la moitié des commentaires redisent le code apprend à les survoler tous — y compris les trois qui protégeaient une règle de sécurité. La densité n'est pas la qualité.

**Un commentaire faux est pire que pas de commentaire.** Modifier une ligne sans relire le commentaire au-dessus, c'est produire une affirmation fausse qui sera crue. Le commentaire fait partie du diff, il se relit comme le code.

**Le commentaire au mauvais endroit ne protège rien.** En tête de fichier ou de fonction, il ne sera pas vu par qui modifie la ligne trente lignes plus bas. Il se pose **au point d'application**, collé à ce qu'il justifie.

**« Le code doit être auto-documenté » ne s'applique qu'au QUOI.** Un nom bien choisi supprime le besoin d'expliquer ce que fait la fonction. Aucun nom, jamais, ne dit pourquoi on a écarté l'autre approche.

**Une justification longue en commentaire diverge.** Passé quelques lignes, elle devient une seconde documentation à maintenir. Au-delà, on renvoie vers la documentation par un lien stable.

**Un agent qui génère du code produit spontanément des commentaires de paraphrase.** C'est la forme la plus fréquente dans les corpus. L'exigence du POURQUOI doit être explicite dans le fichier d'instructions, sinon c'est le QUOI qu'on obtient.

## Part de checklist

- [ ] Chaque décision du ticket apparaît en commentaire au point du code qui l'applique
- [ ] Aucun commentaire ajouté qui paraphrase la ligne suivante
- [ ] Toute règle de sécurité touchée porte sa raison à son point d'application
- [ ] Tout écart assumé vis-à-vis d'une convention est signalé comme volontaire
- [ ] Tout repli volontaire est commenté comme tel, pas laissé lisible comme un bug
- [ ] Les commentaires des lignes modifiées ont été relus, pas seulement le code
- [ ] Aucun code commenté laissé en place
