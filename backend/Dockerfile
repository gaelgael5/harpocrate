FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

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
USER harpocrate
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
