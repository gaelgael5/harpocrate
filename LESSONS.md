# Leçons

- [build] Quand on ajoute une dep Python à `backend/pyproject.toml`, l'ajouter AUSSI dans la liste hardcodée du `backend/Dockerfile` (lignes 33-50). Le commentaire ligne 52 prévient. Sinon `ModuleNotFoundError` au boot du container après `pull latest`. Refactor à venir : faire lire pyproject.toml directement.
