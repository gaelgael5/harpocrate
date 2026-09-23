# Fragment — Observabilité et logs

> Source : globals › « Fichier d'instructions — Observabilité et logs (agnostique) » (révision 2026-09-02).
> Standard de référence : globals › « STANDARD — Gestion des logs (émission structlog, collecte Alloy→Loki→Grafana, interrogation) ».
> Déclencheur : avant d'ajouter ou de modifier un appel de journalisation, un middleware HTTP,
> ou la configuration de `infra/alloy-agent/`.

### Journalisation

- **Journalisation structurée**, jamais d'écriture directe sur la sortie standard. Un
  message libre ne se filtre pas et ne s'agrège pas.
- **Aucun secret dans un log**, y compris dans un chemin d'erreur. Ce qui part vers
  l'agrégateur s'y réplique et s'y conserve selon une rétention qui n'est pas la nôtre :
  un secret journalisé se règle par rotation, pas par effacement.
- **Une charge utile non authentifiée ne se journalise pas telle quelle** : la recopier
  revient à écrire dans nos journaux ce qu'un inconnu a envoyé.
- Journaliser les **décisions**, pas les étapes : ce qui a été refusé et pourquoi, ce qui a
  été appliqué et à quoi. Une trace par étape noie la seule ligne qui comptait.
- Les journaux sont centralisés et consultables : ils font partie du diagnostic, pas d'un
  fichier local qu'on ira chercher en dernier recours.

## Spécifique Harpocrate

- Émission : `structlog.get_logger(__name__)`, sortie JSON (`app/core/logging.py`).
- Middleware `log_requests` (`app/main.py`) : **ne lit jamais le body** ; ne jamais le
  contourner ni ajouter de lecture de body, en particulier sur `/secrets`.
- Ne jamais journaliser : valeur de secret (même chiffrée), passphrase, phrase de récupération,
  clé privée RSA, token `hrpv_*` complet ou tronqué, clé de déchiffrement (`dkey`), en-tête
  `Authorization`, **ni une donnée dérivée qui vaut authentification** (HMAC attendu complet).
  Journaliser librement : identifiants de wallet, chemins de secrets, codes HTTP, motifs d'échec.
- Collecte : Grafana Alloy (`infra/alloy-agent/`, `scripts/install-alloy.sh`) vers Loki —
  **optionnelle**, pas un prérequis de fonctionnement.

## Pièges connus

**Le silence ressemble à un système en bon ordre.** Un flux qui ne parvient plus ne produit aucune erreur — il produit rien. Ce qui doit alerter, c'est l'absence de message attendu, et ça se surveille explicitement.

**Une clef réservée du journaliseur casse à l'exécution, pas au lint.** La plupart des bibliothèques structurées réservent un nom pour le message lui-même ; le passer en argument nommé lève une erreur en production et jamais pendant les vérifications.

**Un journal n'est pas un rattrapage.** Écrire « échec » au niveau erreur ne répare rien et n'est lu par personne au bon moment. Si l'échec doit être retenté, il faut un état persistant qui le porte, pas une ligne de journal.

**La collecte se fait sur le flux du conteneur, pas sur un fichier.** Écrire dans un fichier à l'intérieur du conteneur produit des journaux que personne ne collecte et qui disparaissent au redémarrage.

## Part de checklist

- [ ] Aucune écriture directe sur la sortie standard ajoutée
- [ ] Aucun log ajouté ne peut contenir un secret, même en cas d'erreur
- [ ] Les messages ajoutés portent une décision, pas une étape
- [ ] Aucune clef réservée du journaliseur employée comme nom d'argument
