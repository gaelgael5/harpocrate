FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Binaires système requis :
# - age : chiffrement/déchiffrement des .tar.age (LOT_12A) + age-keygen UI
# - postgresql-client-16 : pg_dump pour produire le SQL avant chiffrement age
#   (sans ça → FileNotFoundError 'pg_dump' au moment du backup).
#   On utilise le client 16 pour matcher la version du serveur Postgres
#   (sinon pg_dump-15 vs server-16 → erreur 'server version too high').
#   Le client 16 est dispo via le dépôt officiel PostgreSQL apt.
RUN apt-get update \
 && apt-get install -y --no-install-recommends age curl ca-certificates gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
    "fastapi>=0.110,<0.116" \
    "uvicorn[standard]>=0.27" \
    "pydantic>=2.6,<3" \
    "pydantic-settings>=2.2,<3" \
    "asyncpg>=0.29" \
    "structlog>=24.1" \
    "python-json-logger>=2.0" \
    "httpx>=0.27" \
    "pyjwt[crypto]>=2.9,<3" \
    "cryptography>=43,<45" \
    "argon2-cffi>=23,<25" \
    "boto3>=1.34" \
    "jsonschema>=4.26,<5" \
    "asyncssh>=2.22.0" \
    "aiomqtt>=2.3.0" \
    "aioftp>=0.21.4"

# ATTENTION : la liste ci-dessus DOIT rester en sync avec backend/pyproject.toml.
# Refactor à venir : faire lire pyproject.toml directement (pip install . avec
# stub app/__init__.py temporaire pour hatch).

# Stage dev : bind-mount du code, reload activé
FROM base AS dev
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/app"]

# Stage prod : code embarqué, user non-root
FROM base AS prod
RUN useradd -r -u 1001 -m harpocrate
COPY app ./app
COPY migrations ./migrations
COPY types ./types
# Crée le path par défaut des backups (HARPOCRATE_BACKUP_LOCAL_PATH) avec les
# bonnes permissions pour l'user non-root. Sans ça, mkdir échoue en runtime
# (Errno 13 sur /var/lib). En prod, ce path est généralement masqué par un
# volume monté depuis docker-compose.yml pour persister à travers les pulls.
RUN mkdir -p /var/lib/harpocrate/backups \
 && chown -R harpocrate:harpocrate /var/lib/harpocrate
USER harpocrate
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
