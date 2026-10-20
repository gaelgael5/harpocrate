# Publier une version du SDK Python

Le SDK est publié sur [PyPI](https://pypi.org/project/harpocrate/) sous le nom
`harpocrate`, **uniquement par la CI** (`.github/workflows/publish-sdk-python.yml`).
Aucun upload depuis un poste, aucun jeton d'API PyPI : l'authentification passe par le
*Trusted Publishing* (OIDC) — PyPI fait confiance au fichier de workflow et à
l'environnement GitHub déclarés chez lui.

## Sortir une version

1. Sur `dev` : mettre à jour `__version__` dans `harpocrate/__init__.py` (seule source de
   la version, lue par `pyproject.toml`) et ajouter l'entrée correspondante dans
   `CHANGELOG.md`. Une version publiée sur PyPI ne se reprend pas et un numéro ne se
   réutilise jamais, même après suppression.
2. *(Facultatif, recommandé pour un changement de packaging)* Répétition sur TestPyPI :
   GitHub → Actions → `publish-sdk-python` → **Run workflow** sur la branche voulue
   (le bouton n'apparaît que si le workflow existe déjà sur `main`, branche par défaut).
   Vérifier ensuite : `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ harpocrate==<version>`.
3. Fusionner sur `main` (décision humaine).
4. Poser et pousser le tag sur le commit de `main` :

   ```bash
   git tag sdk-python-v<version> <commit-de-main>
   git push origin sdk-python-v<version>
   ```

Le workflow refuse de publier si :

- un contrôle échoue (ruff, `ruff format --check`, mypy, pytest sur Python 3.10 à 3.13) ;
- le tag ne désigne pas un commit de `main` ;
- la version du tag diffère de celle construite (`__version__`) ;
- les métadonnées ne passent pas `twine check --strict`, ou le wheel ne s'installe pas
  et ne s'importe pas dans un environnement neuf.

Relancer la publication d'une version déjà présente sur pypi.org échoue explicitement
(PyPI refuse un fichier existant). Si un run a été interrompu entre l'envoi du wheel et
celui du sdist, publier la version suivante plutôt que de compléter à la main.

## Configuration initiale (une fois, par un mainteneur)

Sur **pypi.org** puis sur **test.pypi.org**, compte du mainteneur → *Your projects* →
*Publishing* → *Add a new pending publisher* → GitHub :

| Champ | pypi.org | test.pypi.org |
|---|---|---|
| PyPI Project Name | `harpocrate` | `harpocrate` |
| Owner | `gaelgael5` | `gaelgael5` |
| Repository name | `harpocrate` | `harpocrate` |
| Workflow name | `publish-sdk-python.yml` | `publish-sdk-python.yml` |
| Environment name | `pypi` | `testpypi` |

Sur GitHub, *Settings* → *Environments* : créer `pypi` et `testpypi`. Sur `pypi`, une
règle *Required reviewers* impose une approbation humaine avant chaque publication ;
une règle *Deployment branches and tags* limitée à `sdk-python-v*` empêche toute autre
référence de l'utiliser.
