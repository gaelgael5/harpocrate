FROM python:3.12-slim AS base

# UV_PROJECT_ENVIRONMENT : le venv applicatif est posé en /opt/venv (hors WORKDIR)
#   pour ne pas être écrasé par le bind-mount du stage dev sur /app.
# UV_LINK_MODE=copy : sans hardlinks, plus compatible avec les drivers de
#   stockage Docker (overlay2 / vfs).
# UV_NO_CACHE=1 : pas de cache uv embarqué dans les couches → image plus légère.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Binaires système requis :
# - age : chiffrement/déchiffrement des .tar.age (LOT_12A) + age-keygen UI
# - postgresql-client-16 : pg_dump pour produire le SQL avant chiffrement age
#   (sans ça → FileNotFoundError 'pg_dump' au moment du backup).
#   On utilise le client 16 pour matcher la version du serveur Postgres
#   (sinon pg_dump-15 vs server-16 → erreur 'server version too high').
#   Le client 16 est dispo via le dépôt officiel PostgreSQL apt.
#
# IMPORTANT : on lit /etc/os-release pour piocher le repo PGDG du bon codename
# Debian (bookworm, trixie, …). Sans ça, un repo bookworm-pgdg sur une base
# trixie casse car libpq5 du repo bookworm dépend de libldap-2.5-0 qui n'existe
# pas en trixie (où c'est libldap2). python:3.12-slim peut basculer de codename
# entre deux releases — il faut que ça suive automatiquement.
RUN apt-get update \
 && apt-get install -y --no-install-recommends age curl ca-certificates gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

# Gestionnaire de dépendances officiel du projet (cf. CLAUDE.md). Installé en
# couche système ; on s'en sert ensuite pour synchroniser un venv applicatif à
# partir de pyproject.toml + uv.lock — source de vérité unique. Évite la dérive
# Dockerfile↔pyproject qui a déjà cassé la prod 4 fois (slowapi, asyncssh,
# google-*, jsonschema/boto3) — voir LESSONS.md.
RUN pip install --no-cache-dir uv

# Étape 1 — install des dépendances *seules* (pas le projet lui-même).
# On copie d'abord pyproject.toml + uv.lock pour profiter du cache Docker :
# tant que ces deux fichiers ne changent pas, cette couche est réutilisée
# même quand le code applicatif évolue.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage dev : bind-mount du code, reload activé. Le venv applicatif est en
# /opt/venv (hors /app), donc préservé du bind-mount. Le package `app` est
# accessible parce que uvicorn ajoute le cwd (=/app, monté en bind) au sys.path.
FROM base AS dev
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/app"]

# Stage prod : code embarqué + install du projet, user non-root
FROM base AS prod
COPY app ./app
COPY migrations ./migrations
COPY types ./types

# Étape 2 — installation du projet dans le venv (les deps sont déjà là). Le
# package `app` devient importable depuis n'importe quel cwd, indépendamment
# de PYTHONPATH.
RUN uv sync --frozen --no-dev

# Crée le path par défaut des backups (HARPOCRATE_BACKUP_LOCAL_PATH) avec les
# bonnes permissions pour l'user non-root. Sans ça, mkdir échoue en runtime
# (Errno 13 sur /var/lib). En prod, ce path est généralement masqué par un
# volume monté depuis docker-compose.yml pour persister à travers les pulls.
RUN useradd -r -u 1001 -m harpocrate \
 && mkdir -p /var/lib/harpocrate/backups \
 && chown -R harpocrate:harpocrate /var/lib/harpocrate /opt/venv /app

USER harpocrate
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
