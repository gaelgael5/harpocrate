# SonarQube Cloud — Contrôle qualité du code

## Objectif

Contrôler automatiquement la qualité du code à chaque push sur git.
SonarQube Cloud (gratuit pour les projets open source) analyse le code
et génère un rapport avec les problèmes détectés.

## Instance

- **Plateforme** : SonarQube Cloud (sonarcloud.io)
- **Plan** : gratuit (projets publics)
- **Déclenchement** : automatique à chaque push / PR sur GitHub
- **Langages analysés** : Python, TypeScript, JavaScript, SQL, HTML, CSS

## Ce que SonarQube détecte

| Catégorie | Exemples |
|-----------|----------|
| **Bugs** | Variables non initialisées, conditions toujours vraies, null dereference |
| **Vulnérabilités** | Injection SQL, XSS, secrets dans le code, paths non sécurisés |
| **Code Smells** | Fonctions trop longues, complexité cyclomatique élevée, code dupliqué |
| **Couverture** | Lignes non couvertes par les tests (intégré avec pytest-cov) |
| **Duplication** | Blocs de code copiés-collés |
| **Dette technique** | Estimation du temps pour corriger les problèmes |

## Setup

### 1. Créer le compte SonarQube Cloud

1. Aller sur https://sonarcloud.io
2. Se connecter avec le compte GitHub
3. Importer l'organisation GitHub
4. Sélectionner le repo LandGraph

### 2. Configurer le projet

Créer `sonar-project.properties` à la racine du repo :

```properties
sonar.projectKey=langgraph
sonar.organization=gaelgael5
sonar.projectName=LandGraph

# Sources
sonar.sources=Agents,hitl,web,hitl-frontend/src
sonar.tests=hitl/tests

# Python
sonar.python.version=3.11
sonar.python.coverage.reportPaths=coverage.xml

# TypeScript
sonar.typescript.lcov.reportPaths=hitl-frontend/coverage/lcov.info

# Exclusions
sonar.exclusions=**/node_modules/**,**/static/assets/**,**/__pycache__/**,**/dist/**
sonar.test.exclusions=**/tests/**
```

### 3. GitHub Action

Créer `.github/workflows/sonarqube.yml` :

```yaml
name: SonarQube Analysis
on:
  push:
    branches: [main, test]
  pull_request:
    branches: [main]

jobs:
  sonarqube:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install pytest pytest-cov
          pip install -r hitl/requirements.txt

      - name: Run tests with coverage
        run: |
          cd hitl && python -m pytest --cov=services --cov-report=xml:../coverage.xml || true

      - name: SonarQube Scan
        uses: SonarSource/sonarqube-scan-action@v3
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

### 4. Configurer le token

1. Dans SonarQube Cloud → Mon compte → Sécurité → Générer un token
2. Dans GitHub → Settings → Secrets → Ajouter `SONAR_TOKEN`

## Process quotidien

### Déclenchement

Le contrôle SonarQube est déclenché **sur demande explicite de l'utilisateur**.
Pas de correction automatique — l'utilisateur décide quand traiter les problèmes.

### Session de correction (une fois par jour max)

1. **L'utilisateur demande** : "on fait une session SonarQube" ou "corrige les problèmes sonar"
2. **Consulter le rapport** : aller sur sonarcloud.io → projet LandGraph
3. **Trier par sévérité** :
   - **Blocker / Critical** : corriger immédiatement
   - **Major** : corriger dans la journée
   - **Minor / Info** : noter pour plus tard
4. **Corriger par lot** : regrouper les corrections par module
5. **Committer** : un commit par type de correction
6. **Vérifier** : le push déclenche une nouvelle analyse

### Ce qu'on corrige en priorité

1. **Vulnérabilités** (sécurité) — toujours
2. **Bugs** (fiabilité) — toujours
3. **Code smells critiques** (maintenabilité) — dans la session
4. **Duplication** — si > 5% sur un module
5. **Couverture** — si en dessous des seuils définis dans @docs/tests-python.md

### Ce qu'on ignore

- Les faux positifs → marquer comme "Won't fix" dans SonarQube avec justification
- Les problèmes dans le code généré (static/assets)
- Les avertissements de style qui contredisent nos conventions projet

## Quality Gate

Configurer un Quality Gate dans SonarQube Cloud :

| Métrique | Seuil |
|----------|-------|
| Nouveaux bugs | 0 |
| Nouvelles vulnérabilités | 0 |
| Nouveau code smell ratio | < 5% |
| Couverture nouveau code | > 80% |
| Duplication nouveau code | < 3% |

Le Quality Gate s'affiche sur chaque PR GitHub. Si rouge → corriger avant de merger.

## Commandes locales

```bash
# Lancer l'analyse localement (nécessite sonar-scanner)
sonar-scanner -Dsonar.token=$SONAR_TOKEN

# Générer le rapport de couverture pour SonarQube
cd hitl && python -m pytest --cov=services --cov-report=xml:../coverage.xml
```
