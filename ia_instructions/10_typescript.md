# Fragment — TypeScript / frontend (`frontend/`)

> Source : globals › « Fichier d'instructions — spécificités TypeScript / frontend » (révision 2026-09-02).
> Déclencheur : avant de modifier un fichier sous `frontend/` (`.ts`, `.tsx`, `.css`, `i18n/*.json`).

### Conventions frontend

- TypeScript strict : `strict: true`, `noUncheckedIndexedAccess: true`
- Composants fonctionnels et hooks ; pas de classe
- **Tout appel API passe par TanStack Query** — jamais `useEffect` + `fetch` : un effet qui appelle sans annuler laisse une réponse tardive écraser un état courant
- i18n sur **tous** les libellés visibles — une chaîne en dur ne se traduit jamais après coup
- Fichiers max 300 lignes
- Vitest + React Testing Library ; `describe` / `it`, jamais `test`

## Spécifique Harpocrate

- UI : **Mantine** uniquement (pas de Tailwind, pas de shadcn). État global : **Zustand**
  (`src/stores/` — session, crypto). Validation des réponses API : **Zod** (`src/schemas/`).
  Client HTTP : `src/lib/` (api-client, oidc, query). Formulaires de secrets typés : **RJSF**.
- i18n : `react-i18next`, deux langues **FR et EN** (`src/i18n/fr.json`, `src/i18n/en.json`) —
  toute clef ajoutée l'est dans les deux fichiers.
- Props typées via `interface`, exports nommés.
- **Crypto client : uniquement les helpers de `src/crypto/`** (Argon2id via `hash-wasm`,
  AES-256-GCM et RSA-OAEP-SHA256 via WebCrypto natif, BIP-39). Jamais de KDF ni de primitive
  maison, jamais de valeur dérivée d'un secret envoyée au serveur hors du protocole existant.
- **Sécurité UI** : aucune valeur de secret dans un `console.*`, une notification, un titre de
  page ou une URL. Masquée par défaut, dévoilée sur action explicite de l'utilisateur.
- Tests : `frontend/src/tests/`.

## Commandes essentielles

```bash
cd frontend && npm install
cd frontend && npm run dev                      # :5173, proxy /v1 -> :8000
cd frontend && npx tsc --noEmit -p tsconfig.json
cd frontend && npm run lint                     # eslint src
cd frontend && npx vitest run
cd frontend && npm run build                    # tsc --noEmit && vite build
```

Formatage : prettier est déclaré (`devDependencies`, script `format`) **sans fichier de
configuration** — ses défauts (guillemets doubles, points-virgules) sont le style du dépôt.
Ne formater **que les fichiers touchés** (`npx prettier --write <fichiers>`), jamais
`npm run format` sur tout `src/` au milieu d'une tâche : le diff serait noyé.

## Pièges connus

**Ne pas invoquer un formateur que le dépôt n'utilise pas.** `npx prettier --write` sur un dépôt sans configuration prettier télécharge l'outil et applique ses défauts — guillemets doubles, points-virgules — et reformate des fichiers entiers pour un ajout de trois lignes. Vérifier la présence d'une configuration avant, et s'en tenir à l'`eslint` du dépôt sinon.

**Un état semé depuis les props ne se recopie pas dans un effet.** `useEffect(() => setX(props.x))` fait écraser une saisie en cours par une réponse tardive ; dériver la valeur au rendu.

**Les tests qui montent un routeur ont besoin du chemin, pas seulement de l'élément.** Une route attrape-tout rend `useParams()` vide, et les tests échouent pour une raison sans rapport avec ce qu'ils vérifient.

**Un jeu d'essai qui porte déjà la valeur attendue rend le test aveugle.** Si la doublure a un champ vide et que le test vérifie qu'il est vide, il restera vert même si le code le recopie. Éprouver le test en cassant le code.

## Part de checklist

- [ ] `tsc --noEmit` et `eslint` passent
- [ ] La suite Vitest passe en entier, pas seulement les fichiers touchés
- [ ] Aucun libellé en dur : tout passe par i18n, dans **toutes** les langues du dépôt (FR + EN)
- [ ] Aucun appel API hors TanStack Query
- [ ] Aucun reformatage massif hors périmètre dans le diff
- [ ] Modification crypto : aller-retour chiffrement → déchiffrement testé, pas seulement le chiffrement
- [ ] La page modifiée charge sans erreur console
